from flask import Flask, request, jsonify
import subprocess
import os
import logging
import sys
import json
from celery import Celery

app = Flask(__name__)
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Read API_KEY from environment variable
API_KEY = os.environ.get('API_KEY', '')
DEVICE = os.environ.get('DEVICE', '')
DEBUG = os.environ.get('DEBUG', '').lower() == 'true'
SERVERID = os.environ.get('SERVERID', '').lower() == 'true'

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

@celery.task
def run_speedtest(serverid):
    try:
        if serverid:
            result = subprocess.run(["speedtest-cli", "--server", "24161", "--json"], capture_output=True, text=True)
        else:
            result = subprocess.run(["speedtest-cli", "--json"], capture_output=True, text=True)
        if result.returncode == 0:
            output_data = json.loads(result.stdout)
            output_data["status"] = "success"
            output_data["download_mbps"] = "{:.0f}".format(output_data["download"] / 10**6 * 8)
            output_data["upload_mbps"] = "{:.0f}".format(output_data["upload"] / 10**6 * 8)
            return output_data
        else:
            return {"status": "error"}
    except Exception as e:
        logging.error(str(e))
        return {"status": "error"}

@app.route('/speedtest', methods=['GET'])
def speed():
    api_key = request.args.get('api_key', "")
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    task = run_speedtest.apply_async(args=[SERVERID])
    result = task.get()

    return jsonify(result), 200

@app.route('/ping/<ip>', methods=['GET'])
def ping_device(ip):
    api_key = request.args.get('api_key', "")
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    response = subprocess.run(['ping', '-c', '1', ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

@celery.task
def scan_access_points(device):
    command = f'iw dev {device} scan | egrep "SSID|signal"'
    scan_result = subprocess.check_output(command, universal_newlines=True, shell=True)
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

@app.route('/accesspoints', methods=['GET'])
def access_points():
    api_key = request.args.get('api_key', '')
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    task = scan_access_points.apply_async(args=[DEVICE])
    result = task.get()

    return jsonify({'status': 'success', 'access_points': result}), 200

if __name__ == '__main__':
    app.config['API_KEY'] = API_KEY
    app.run(debug=True, host='0.0.0.0')
