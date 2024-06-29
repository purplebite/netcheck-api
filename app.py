from flask import Flask, request, jsonify
import subprocess
import os
import logging
import sys
import json
from celery import Celery
from flask_caching import Cache
# from ping3 import ping
from multiprocessing import Lock
import time


app = Flask(__name__)
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

app.config['CACHE_TYPE'] = 'RedisCache'
app.config['CACHE_REDIS_HOST'] = 'localhost'
app.config['CACHE_REDIS_PORT'] = 6379
app.config['CACHE_REDIS_DB'] = 0
app.config['CACHE_REDIS_URL'] = 'redis://localhost:6379/0'

celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 1200})
cache = Cache(app)

scan_lock = Lock()
ping_lock = Lock()
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
        # print("1 \n")
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
        # print("1 \n")
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
        with ping_lock:  # Acquire ping_lock

            result = subprocess.run(['ping', '-c', '1', ip], capture_output=True, text=True)
            if result.returncode == 0:
                # Extract the ping response time from the output
                output = result.stdout
                # Example output: "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=14.2 ms"
                # Extract the time value from the output
                time_line = next(line for line in output.split('\n') if 'time=' in line)
                response_time = time_line.split('time=')[1].split()[0]
                response_time = int(float(response_time))
                return {'status': 'success', 'response_time': response_time}
            else:
                return {'status': 'error'}
    except subprocess.CalledProcessError as e:
        logging.error(f"Command error: {str(e)}")
        raise self.retry(exc=e)
    except subprocess.TimeoutExpired as e:
        logging.error(f"Command timeout: {str(e)}")
        raise self.retry(exc=e)
    except Exception as e:
        logging.error(f"Error in run_ping: {str(e)}")
        raise self.retry(exc=e)
    
@app.route('/ping/<ip>', methods=['GET'])
def ping_device(ip):
    api_key = request.args.get('api_key', "")
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    response = run_ping.apply(args=[ip], throw=True).get()
    if response['status'] == 'success':
        return jsonify({'status': 'success', 'response_time': response['response_time']}), 200
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
    def run_scan():
        with scan_lock:  # Acquire the lock
            command = f'iw dev {device} scan | egrep "SSID|signal"'
            retries = 5
            initial_delay = 2  # initial delay in seconds
            delay = initial_delay
            resource_busy_error_code = 16  # Error code for "Device or resource busy"


            for attempt in range(retries):
                try:
                    result = subprocess.check_output(command, universal_newlines=True, shell=True, timeout=100)
                    return result
                except subprocess.CalledProcessError as e:
                    error_message = e.output
                    logging.error(f"Attempt {attempt + 1}: Command error: {error_message}")
                    if "Device or resource busy" in error_message:
                        logging.info(f"Attempt {attempt + 1}: Device or resource busy. Waiting before retrying.")
                    else:
                        return 'error'
                except subprocess.TimeoutExpired as e:
                    logging.error(f"Attempt {attempt + 1}: Command timeout: {str(e)}")
                    return 'error'

                if attempt < retries - 1:
                    logging.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                    delay *= 2  # exponential backoff
                else:
                    raise Exception(f"Failed to execute command after {retries} attempts")


    try:
        scan_result = run_scan()
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
    print(cached_result)
    if cached_result :
        return jsonify({'status': 'success', 'access_points': cached_result}), 200

    return jsonify({'status': 'success', 'access_points': 'no cache available'}), 200

@app.route('/set_accesspoints', methods=['GET'])
def set_accesspoints():
    api_key = request.args.get('api_key', '')
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    
    try:
        result1 = scan_access_points.apply(args=[DEVICE], throw=True).get()
        time.sleep(5)
        result2 = scan_access_points.apply(args=[DEVICE], throw=True).get()
        unique_dict = {}
        seen_ssids = set()
        result=[]
        
        if result1 not in ['busy', 'error'] and result2 not in ['busy', 'error']:
            for item in result1+result2:
                ssid = item['SSID']
                if ssid not in seen_ssids:
                    seen_ssids.add(ssid)
                    result.append(item)
        else:
            # Handle cases where one of the results is an error or busy
            if isinstance(result1, list):
                result = result1
            elif isinstance(result2, list):
                result = result2
            else:
                result = []

        print("--------------")
        print(result1)
        print("--------------")
        print(result2)
        print("--------------")
        print(result2)
        # Convert the dictionary back to a list of dictionaries
        # result = [{k: v} for k, v in unique_dict.items()]
        if result == 'busy':
            return jsonify({'status': 'busy'}), 200
        if result == 'error':
            return jsonify({'status': 'error'}), 200
        if result == [] :
            return jsonify({'status': 'error'}), 200
        if result != 'error' and result != 'busy' and result != [] and result != None:
            cache.set('access_points', result)
        return jsonify({'status': 'success'}), 200
    except Exception as e:
        logging.error(f"Error during access points scan: {str(e)}")
        return jsonify({'status': 'error', 'error': str(e)}), 500


if __name__ == '__main__':
    app.config['API_KEY'] = API_KEY
    app.run(debug=True, host='0.0.0.0')
