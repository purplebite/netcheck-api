"""Settings and helpers shared by the API (app.py) and the background scanner (scanner.py)."""
import json
import logging
import os
import sys
import tempfile
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
)

API_KEY = os.environ.get('API_KEY', '')
DEVICE = os.environ.get('DEVICE', 'wlan0')

# SCAN_CRON is kept for backwards compatibility with existing `docker run` commands (minutes).
try:
    SCAN_INTERVAL = max(60, int(float(os.environ.get('SCAN_CRON', '5')) * 60))
except ValueError:
    SCAN_INTERVAL = 300

# A scan result older than this is reported as stale (HTTP 503) so monitoring notices.
STALE_AFTER = int(os.environ.get('STALE_AFTER', str(SCAN_INTERVAL * 3)))

# /dev/shm is RAM-backed: nothing is written to the SD card.
STATE_DIR = os.environ.get('STATE_DIR', '/dev/shm/netcheck')
AP_FILE = os.path.join(STATE_DIR, 'access_points.json')


def write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def now():
    return int(time.time())
