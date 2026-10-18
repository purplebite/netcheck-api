"""NetCheck API: small network-monitoring API for Raspberry Pis.

Endpoints (all require the API key):
  GET /ping/<host>               ICMP ping, returns response time in ms
  GET /tcp-check/<host>/<port>   TCP connect test, returns connect time in ms
  GET /accesspoints              Last Wi-Fi scan from the background scanner
  GET /ip-info                   All IP addresses of the machine: LAN, NetBird, Docker, public

The API key may be sent as `X-API-Key: <key>`, `Authorization: Bearer <key>`, or `?api_key=<key>`.
"""
import hmac
import ipaddress
import json
import logging
import re
import socket
import ssl
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request

from common import API_KEY, AP_FILE, STALE_AFTER, STATE_DIR, now, read_json, write_json_atomic

if not API_KEY:
    raise SystemExit('API_KEY is not set; refusing to start without authentication.')

app = Flask(__name__)
app.json.sort_keys = False  # keep 'status' first, as built

HOSTNAME_RE = re.compile(r'^(?!-)[A-Za-z0-9.-]{1,253}$')
CGNAT_NET = ipaddress.ip_network('100.64.0.0/10')
PUBLIC_IP_FILE = f'{STATE_DIR}/public_ip.json'
PUBLIC_IP_TTL = 300


# ---------- helpers ----------

def provided_key():
    key = request.headers.get('X-API-Key')
    if not key:
        auth = request.headers.get('Authorization', '')
        if auth.lower().startswith('bearer '):
            key = auth[7:].strip()
    return key or request.args.get('api_key', '')


@app.before_request
def require_api_key():
    if not hmac.compare_digest(provided_key().encode(), API_KEY.encode()):
        return jsonify({'status': 'error', 'error': 'Invalid API key'}), 401


def valid_host(host):
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(HOSTNAME_RE.match(host))


def bad_request(msg):
    return jsonify({'status': 'error', 'error': msg}), 400


# ---------- ping / tcp-check ----------

@app.route('/ping/<host>')
def ping(host):
    if not valid_host(host):
        return bad_request('invalid host')
    try:
        proc = subprocess.run(['ping', '-c', '1', '-W', '2', host],
                              capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return jsonify({'status': 'error'}), 404
    match = re.search(r'time=([\d.]+)', proc.stdout)
    if proc.returncode == 0 and match:
        return jsonify({'status': 'success', 'response_time': int(float(match.group(1)))}), 200
    return jsonify({'status': 'error'}), 404


@app.route('/tcp-check/<host>/<port>')
def tcp_check(host, port):
    if not valid_host(host):
        return bad_request('invalid host')
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        return bad_request('invalid port')
    start = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=3):
            pass
    except OSError:
        return jsonify({'status': 'error'}), 404
    return jsonify({'status': 'success', 'response_time': int((time.monotonic() - start) * 1000)}), 200


# ---------- access points ----------

@app.route('/accesspoints')
def access_points():
    state = read_json(AP_FILE)
    if not state or not state.get('access_points'):
        error = (state or {}).get('last_error') or 'no scan result yet'
        return jsonify({'status': 'error', 'error': error}), 503
    age = now() - state['scanned_at']
    body = {
        'status': 'success',
        'access_points': state['access_points'],
        'scanned_at': state['scanned_at'],
        'age_seconds': age,
        'last_error': state.get('last_error'),
    }
    if age > STALE_AFTER:
        body['status'] = 'stale'
        return jsonify(body), 503
    return jsonify(body), 200


# ---------- ip-info ----------

def ip_json(*args):
    out = subprocess.run(['ip', '-j', *args], capture_output=True, text=True, timeout=5).stdout
    return json.loads(out or '[]')


# Interface kinds (from `ip -d`) that mean "this is a VPN/overlay tunnel".
VPN_KINDS = {'wireguard', 'tun', 'ppp', 'gre', 'ipip', 'sit', 'vti'}
VPN_PROVIDERS = (('wt', 'netbird'), ('tailscale', 'tailscale'), ('zt', 'zerotier'),
                 ('wg', 'wireguard'), ('tun', 'openvpn'), ('ppp', 'ppp'))
DOCKER_PREFIXES = ('docker', 'br-', 'veth', 'podman', 'cni')


def interface_kind(link):
    """'vpn', 'docker' or 'physical', based on the kernel's interface type and the name."""
    name = link.get('ifname', '')
    kind = link.get('linkinfo', {}).get('info_kind', '')
    if kind in VPN_KINDS or name.startswith(('wt', 'wg', 'tailscale', 'zt')):
        return 'vpn'
    if name.startswith(DOCKER_PREFIXES):
        return 'docker'
    # Some VPNs run without a recognisable type: CGNAT range is the giveaway (NetBird, Tailscale).
    if any(a.get('family') == 'inet' and ipaddress.ip_address(a['local']) in CGNAT_NET
           for a in link.get('addr_info', [])):
        return 'vpn'
    return 'physical'


def vpn_provider(name):
    return next((p for prefix, p in VPN_PROVIDERS if name.startswith(prefix)), 'unknown')


def classify(iface_kind, addr):
    ip = ipaddress.ip_address(addr)
    if ip.is_link_local:
        return 'link-local'
    if iface_kind in ('vpn', 'docker'):
        return iface_kind
    return 'lan' if ip.is_private else 'public'


def fetch_public_ip(url):
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(url, timeout=3, context=ctx) as r:
            for line in r.read().decode().splitlines():
                if line.startswith('ip='):
                    return line[3:]
    except Exception as e:
        logging.info('Public IP lookup via %s failed: %s', url, e)
    return None


def public_ips():
    cached = read_json(PUBLIC_IP_FILE)
    if cached and now() - cached.get('checked_at', 0) < PUBLIC_IP_TTL:
        return cached
    with ThreadPoolExecutor(2) as pool:
        v4 = pool.submit(fetch_public_ip, 'https://1.1.1.1/cdn-cgi/trace')
        v6 = pool.submit(fetch_public_ip, 'https://[2606:4700:4700::1111]/cdn-cgi/trace')
        result = {'ipv4': v4.result(), 'ipv6': v6.result(), 'checked_at': now()}
    if result['ipv4'] or result['ipv6']:  # don't cache a failed lookup
        write_json_atomic(PUBLIC_IP_FILE, result)
    return result


@app.route('/ip-info')
def ip_info():
    try:
        interfaces = []
        for link in ip_json('-d', 'addr', 'show'):
            name = link.get('ifname', '')
            kind = interface_kind(link)
            if name == 'lo' or name.startswith('veth'):
                continue
            addrs = [
                {'address': a['local'], 'prefix': a['prefixlen'],
                 'family': 'ipv6' if a['family'] == 'inet6' else 'ipv4',
                 'role': classify(kind, a['local'])}
                for a in link.get('addr_info', []) if a.get('family') in ('inet', 'inet6')
            ]
            if not addrs:
                continue
            iface = {'name': name, 'type': kind, 'state': link.get('operstate'),
                     'mac': link.get('address'), 'addresses': addrs}
            if kind == 'vpn':
                iface['provider'] = vpn_provider(name)
            interfaces.append(iface)

        route = (ip_json('route', 'show', 'default') or [{}])[0]
        default_if = route.get('dev')

        def first(iface, role, family='ipv4'):
            return next((a['address'] for a in iface['addresses']
                         if a['role'] == role and a['family'] == family), None)

        lan = [i for i in interfaces if i['type'] == 'physical' and first(i, 'lan')]
        lan.sort(key=lambda i: i['name'] != default_if)  # default-route interface first
        vpns = [{'provider': i['provider'], 'interface': i['name'],
                 'ipv4': first(i, 'vpn'), 'ipv6': first(i, 'vpn', 'ipv6')}
                for i in interfaces if i['type'] == 'vpn']
        public = public_ips()

        return jsonify({
            'status': 'success',
            'hostname': socket.gethostname(),
            'summary': {
                'lan_ipv4': first(lan[0], 'lan') if lan else None,
                'vpn': vpns,
                'public_ipv4': public.get('ipv4'),
                'public_ipv6': public.get('ipv6'),
            },
            'default_route': {'interface': default_if, 'gateway': route.get('gateway')},
            'public_checked_at': public.get('checked_at'),
            'interfaces': interfaces,
        }), 200
    except Exception as e:
        logging.error('ip-info failed: %s', e)
        return jsonify({'status': 'error', 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=2025)
