# NetCheck API

NetCheck API is a small network monitoring API for Raspberry Pi (works on any Linux machine).
Run it next to a monitoring tool such as Uptime Kuma to check reachability of devices on the local network,
see which Wi-Fi networks are around, and look up the machine's own addresses.

## Installation

```
docker run -d --name netcheck --privileged --network host --restart=always \
  -e API_KEY=your-secret-key \
  -e PORT=2025 \
  -e DEVICE=wlan0 \
  -e SCAN_CRON=10 \
  purplebite/netcheck-api:latest
```

No Redis or other containers are needed.

| Variable | Default | Meaning |
|---|---|---|
| `API_KEY` | (required) | The container refuses to start without it |
| `PORT` | `2025` | Port the API listens on |
| `DEVICE` | `wlan0` | Wi-Fi interface used for access point scans |
| `SCAN_CRON` | `5` | Minutes between Wi-Fi scans |
| `STALE_AFTER` | 3 × scan interval | Seconds after which a scan result counts as stale |
| `WORKERS` | `2` | Gunicorn worker processes |

## Authentication

Send the API key in one of these ways (header is preferred, so the key doesn't end up in proxy logs):

```
X-API-Key: your-secret-key
Authorization: Bearer your-secret-key
?api_key=your-secret-key
```

## Endpoints

### `GET /ping/<host>`
ICMP ping (2 s timeout). `200 {"status":"success","response_time":12}` or `404 {"status":"error"}`.

### `GET /tcp-check/<host>/<port>`
TCP connect test (3 s timeout). `200 {"status":"success","response_time":4}` or `404 {"status":"error"}`.

### `GET /accesspoints`
Result of the latest background Wi-Fi scan (strongest signal per SSID, hidden networks left out).

```
200 {"status":"success","access_points":[{"SSID":"Office","signal_strength":-51.0}],
     "scanned_at":1792313559,"age_seconds":42,"last_error":null}
```

Returns `503` with `"status":"stale"` when the last good scan is older than `STALE_AFTER`,
and `503` with `"status":"error"` when no scan has succeeded yet, so monitoring notices broken scanning.

### `GET /ip-info`
Shows every network address of the machine, so you can see at a glance which box answered and how it is connected.

```
200 {"status":"success",
     "hostname":"rpi-01",
     "summary":{"lan_ipv4":"172.28.0.50",
                "vpn":[{"provider":"netbird","interface":"wt0","ipv4":"100.64.90.129","ipv6":null}],
                "public_ipv4":"203.0.113.10","public_ipv6":null},
     "default_route":{"interface":"eth0","gateway":"172.28.0.1"},
     "public_checked_at":1792313537,
     "interfaces":[...]}
```

| Field | Meaning |
|---|---|
| `status` | `success`, or `error` (HTTP 500) when the addresses could not be read |
| `hostname` | Name of the machine that answered; useful to confirm a tunnel URL reaches the right box |
| `summary.lan_ipv4` | Local network address, preferring the interface that carries the default route |
| `summary.vpn` | One entry per VPN/overlay interface; empty list `[]` when the machine has none |
| `summary.public_ipv4` / `public_ipv6` | Address the internet sees, looked up via Cloudflare and cached 5 minutes; `null` when there is none or the lookup failed |
| `default_route` | Interface and gateway used for internet traffic |
| `interfaces` | Every interface with its `type` (`physical`, `vpn`, `docker`), MAC address, and each address with its `role` (`lan`, `vpn`, `docker`, `link-local`, `public`) |

VPN detection is generic: any WireGuard or tun-type interface, or an address in the 100.64.0.0/10 range,
counts as VPN. The `provider` is a best guess from the interface name: `wt*` → `netbird`, `tailscale*` → `tailscale`,
`zt*` → `zerotier`, `wg*` → `wireguard`, `tun*` → `openvpn`, otherwise `unknown`.

## Notes

- Scan results and the public-IP cache live in `/dev/shm` (RAM), so nothing is written to the SD card.
- `--privileged` (or `--cap-add NET_ADMIN`) and `--network host` are needed for Wi-Fi scans and to see the host's interfaces.
- The easiest way to expose the API securely is a Cloudflare Tunnel.

## Releasing

- **Publishing a GitHub release** builds and pushes `:<version>` and `:latest`. Machines running Watchtower pick up `:latest` automatically.
- **Actions → Docker Build and Push → Run workflow** builds a test tag only (e.g. `:test`), for trying a change on one machine first.
