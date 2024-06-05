from flask import Flask, request, jsonify
import subprocess
import os
import logging
import sys
import json
from celery import Celery
from flask_caching import Cache


app = Flask(__name__)
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 20})

# Read API_KEY from environment variable
API_KEY = os.environ.get('API_KEY', '')
SERVER_ID = os.environ.get('SERVER_ID', '')
DEVICE = os.environ.get('DEVICE', '')
DEBUG = os.environ.get('DEBUG', '').lower() == 'true'
# SERVERID = os.environ.get('SERVERID', '').lower() == 'true'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

def filter_access_points(access_points):
    try:
        ssid_signal_map = {}
        filtered_access_points = []
        seen_ssids = set()

        for ap in access_points:
            ssid = ap['SSID']
            signal_strength = ap['signal_strength']
            if ssid not in ssid_signal_map or signal_strength > ssid_signal_map[ssid]:
                ssid_signal_map[ssid] = signal_strength

        for ap in access_points:
            ssid = ap['SSID']
            signal_strength = ap['signal_strength']
            if ssid != "" and signal_strength == ssid_signal_map[ssid] and ssid not in seen_ssids:
                filtered_access_points.append(ap)
                seen_ssids.add(ssid)

        return filtered_access_points
    except Exception as e:
        logging.error(str(e))
        return "error"

@celery.task(bind=True, default_retry_delay=300, max_retries=5)
def run_speedtest(self, serverid):
    try:
        command = ["speedtest-cli", "--server", f'{SERVER_ID}', "--json"] if serverid else ["speedtest-cli", "--json"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        result.check_returncode()
        output_data = json.loads(result.stdout)
        output_data["status"] = "success"
        output_data["download_mbps"] = "{:.0f}".format(output_data["download"] / 10**6 * 8)
        output_data["upload_mbps"] = "{:.0f}".format(output_data["upload"] / 10**6 * 8)
        return output_data
    except subprocess.CalledProcessError as e:
        logging.error(f"Command error: {str(e)}")
        raise self.retry(exc=e)
    except subprocess.TimeoutExpired as e:
        logging.error(f"Command timeout: {str(e)}")
        raise self.retry(exc=e)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise self.retry(exc=e)

@app.route('/speedtest', methods=['GET'])
def speed():
    api_key = request.args.get('api_key', "")
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    try:
        result = run_speedtest.apply(args=[SERVER_ID], throw=True).get()
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500

@celery.task(bind=True, default_retry_delay=300, max_retries=5)
def run_ping(self, ip):
    try:
        
        result = subprocess.run(['ping', '-c', '1', ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"Command error: {str(e)}")
        raise self.retry(exc=e)
    except subprocess.TimeoutExpired as e:
        logging.error(f"Command timeout: {str(e)}")
        raise self.retry(exc=e)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise self.retry(exc=e)

@app.route('/ping/<ip>', methods=['GET'])
def ping_device(ip):
    api_key = request.args.get('api_key', "")
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    response = run_ping.apply(args=[ip], throw=True).get()
    if response.returncode == 0:
        return jsonify({'status': 'success'}), 200
    else:
        return jsonify({'status': 'error'}), 404

@app.route('/tcp-check/<ip>/<port>', methods=['GET'])
def tcp_check(ip, port):
    api_key = request.args.get('api_key', "")
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    try:
        response = subprocess.run(['nc', '-zv', ip, port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if response.returncode == 0:
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error'}), 404
    except Exception as e:
        logging.error(str(e))
        return jsonify({'status': 'error'}), 500

@celery.task(bind=True, default_retry_delay=300, max_retries=5)
def scan_access_points(self, device):
    try:
        command = f'iw dev {device} scan | egrep "SSID|signal"'
        scan_result = subprocess.check_output(command, universal_newlines=True, shell=True, timeout=100)
        access_points = []
        current_ap = {}
        for line in scan_result.split('\n'):
            try:
                if 'SSID:' in line:
                    current_ap['SSID'] = line.split('SSID: ')[1]
                    if len(current_ap) == 2:
                        access_points.append(current_ap.copy())
                        current_ap = {}
                elif 'signal:' in line:
                    current_ap['signal_strength'] = float(line.split('signal: ')[1].split(' dBm')[0])
                    if len(current_ap) == 2:
                        access_points.append(current_ap.copy())
                        current_ap = {}
            except Exception as e:
                logging.error(f"Error parsing line: {line}, Error: {str(e)}")

        filtered_access_points = filter_access_points(access_points)
        return filtered_access_points
    except subprocess.CalledProcessError as e:
        logging.error(f"Command error: {str(e)}")
        raise self.retry(exc=e)
    except subprocess.TimeoutExpired as e:
        logging.error(f"Command timeout: {str(e)}")
        raise self.retry(exc=e)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise self.retry(exc=e)

@app.route('/accesspoints', methods=['GET'])
def access_points():
    api_key = request.args.get('api_key', '')
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    cached_result = cache.get('access_points')
    if cached_result:
        return jsonify({'status': 'success', 'access_points': cached_result}), 200

    try:
        result = scan_access_points.apply(args=[DEVICE], throw=True).get()
        cache.set('access_points', result)
        return jsonify({'status': 'success', 'access_points': result}), 200
    except Exception as e:
        logging.error(f"Error during access points scan: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

if __name__ == '__main__':
    app.config['API_KEY'] = API_KEY
    app.run(debug=True, host='0.0.0.0')
