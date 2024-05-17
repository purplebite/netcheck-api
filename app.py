from flask import Flask, request, jsonify, current_app
import subprocess
import os
import logging
import sys


app = Flask(__name__)


# Read API_KEY from environment variable
API_KEY = os.environ.get('API_KEY', '')
DEVICE = os.environ.get('DEVICE', '')
DEBUG = os.environ.get('DEBUG', '').lower() == 'true'

logging.basicConfig(

    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)



def filter_access_points(access_points):
    ssid_signal_map = {}
    filtered_access_points = []
    seen_ssids = set()

    # Iterate through access points to find the highest signal strength for each SSID .
    for ap in access_points:
        ssid = ap['SSID']
        signal_strength = ap['signal_strength']

        # Update the signal strength for the SSID if it's higher
        if ssid not in ssid_signal_map or signal_strength > ssid_signal_map[ssid]:
            ssid_signal_map[ssid] = signal_strength

    # Iterate through access points again to filter out entries with empty SSID and duplicates
    for ap in access_points:
        ssid = ap['SSID']
        signal_strength = ap['signal_strength']

        # Check if the SSID is not empty, it has the highest signal strength, and it's not a duplicate
        if ssid != "" and signal_strength == ssid_signal_map[ssid] and ssid not in seen_ssids:
            filtered_access_points.append(ap)
            seen_ssids.add(ssid)

    return filtered_access_points



@app.route('/ping/<ip>', methods=['GET'])
def ping_device(ip):
    api_key = request.args.get('api_key',"")

    # Check if the API key is correct
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    # Ping the device
    response = subprocess.run(['ping', '-c', '1', ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Check the return code to determine if the device is up
    if response.returncode == 0:
        return jsonify({'status': 'success'}), 200
    else:
        return jsonify({'status': 'error'}), 404

@app.route('/tcp-check/<ip>/<port>', methods=['GET'])
def tcp_check(ip, port):
    api_key = request.args.get('api_key',"")

    # Check if the API key is correct
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401

    # Check if the port is reachable
    try:
        response = subprocess.run(['nc', '-zv', ip, port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if response.returncode == 0:
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error'}), 404
    except Exception as e:
        if DEBUG:
            logging.error(str(e))
            return jsonify({'status': 'error'}), 500
        return jsonify({'status': 'error'}), 500




@app.route('/accesspoints', methods=['GET'])
def access_points():
    api_key = request.args.get('api_key', '')

    # Check if the API key is correct
    if api_key != API_KEY:
        return jsonify({'error': 'Invalid API key'}), 401
    
    scan_result=''

    try:
        # Run the command to scan for nearby access points
        # scan_result = subprocess.check_output(['iw', 'dev', DEVICE, 'scan','|','egrep','SSID|signal'], universal_newlines=True)
        command = 'iw dev ' + DEVICE + ' scan | egrep \'SSID|signal\''
        scan_result = subprocess.check_output(command, universal_newlines=True, shell=True)
        
        # Extract SSID and signal strength from the scan result
        access_points = []
        current_ap = {}
        for line in scan_result.split('\n'):
            # print(line) optional 
            try:
                if 'SSID:' in line:
                    current_ap['SSID'] = line.split('SSID: ')[1]
                    if len(current_ap) == 2:
                        access_points.append(current_ap.copy())
                elif 'signal:' in line:
                    current_ap['signal_strength'] = float(line.split('signal: ')[1].split(' dBm')[0])
                    if len(current_ap) == 2:
                        access_points.append(current_ap.copy())
            except:
                pass
        # access_points=access_points[1]
        if DEBUG and access_points > 0:
            logging.info(str(access_points))
        filtered_access_points = filter_access_points(access_points)
        return jsonify({'status': 'success', 'access_points': filtered_access_points}), 200
    except subprocess.CalledProcessError as e:
        # If the device is not found, return an empty list of access points
        if DEBUG:
            logging.error(str(e))
            return jsonify({'status': 'error'}), 500
        if e.returncode == 237 or 'No such device' in e.output:
            # return jsonify({'status': 'success', 'access_points': []}), 200
            return jsonify({'status': 'error'}), 500
        else:
            return jsonify({'status': 'error'}), 500
    except Exception as e:
        if DEBUG:
            logging.error(str(e))
            return jsonify({'status': 'error'}), 500
        return jsonify({'status': 'error'}), 500



if __name__ == '__main__':
    app.config['API_KEY'] = API_KEY
    app.run(debug=True, host='0.0.0.0')
