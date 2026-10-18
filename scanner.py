"""Background Wi-Fi scanner.

Scans every SCAN_INTERVAL seconds and stores the result in RAM (/dev/shm), where the API reads it.
Only this single process ever scans, so scans can't collide ("Device or resource busy").
Each round does two scans a few seconds apart and merges them, because one scan often misses APs.
"""
import logging
import subprocess
import time

from common import AP_FILE, DEVICE, SCAN_INTERVAL, now, read_json, write_json_atomic

SCANS_PER_ROUND = 2
PAUSE_BETWEEN_SCANS = 5
BUSY_RETRIES = 5


def iw_scan(device):
    """Run one `iw scan`, retrying with backoff while the radio is busy. Returns raw output."""
    delay = 2
    for attempt in range(1, BUSY_RETRIES + 1):
        proc = subprocess.run(['iw', 'dev', device, 'scan'], capture_output=True, text=True, timeout=60)
        if proc.returncode == 0:
            return proc.stdout
        err = (proc.stderr or proc.stdout).strip()
        if 'busy' in err.lower() and attempt < BUSY_RETRIES:
            logging.info('Scan attempt %d: device busy, retrying in %ds', attempt, delay)
            time.sleep(delay)
            delay *= 2
            continue
        raise RuntimeError(f'iw scan failed: {err}')
    raise RuntimeError('iw scan failed: device stayed busy')


def parse_iw(output):
    """Parse `iw scan` output per BSS block, so one odd entry can't shift SSID/signal pairs."""
    aps, signal, ssid = [], None, None

    def flush():
        if ssid and signal is not None:
            aps.append({'SSID': ssid, 'signal_strength': signal})

    for raw in output.splitlines():
        line = raw.strip()
        if raw.startswith('BSS '):
            flush()
            signal, ssid = None, None
        elif line.startswith('signal:'):
            try:
                signal = float(line.split()[1])
            except (IndexError, ValueError):
                signal = None
        elif line.startswith('SSID:'):
            ssid = line[len('SSID:'):].strip() or None  # hidden networks have an empty SSID
    flush()
    return aps


def strongest_per_ssid(aps):
    best = {}
    for ap in aps:
        if ap['SSID'] not in best or ap['signal_strength'] > best[ap['SSID']]['signal_strength']:
            best[ap['SSID']] = ap
    return sorted(best.values(), key=lambda a: a['signal_strength'], reverse=True)


def scan_round():
    found, errors = [], []
    for i in range(SCANS_PER_ROUND):
        if i:
            time.sleep(PAUSE_BETWEEN_SCANS)
        try:
            found += parse_iw(iw_scan(DEVICE))
        except Exception as e:  # keep going: the other scan may still succeed
            errors.append(str(e))
    return strongest_per_ssid(found), errors


def main():
    logging.info('Scanner started: device=%s interval=%ds', DEVICE, SCAN_INTERVAL)
    while True:
        started = time.monotonic()
        state = read_json(AP_FILE) or {}
        state['last_attempt'] = now()
        try:
            aps, errors = scan_round()
            if aps:
                state.update(access_points=aps, scanned_at=now(), last_error=None)
                logging.info('Scan OK: %d access points', len(aps))
            else:
                state['last_error'] = '; '.join(errors) or 'no access points found'
                logging.warning('Scan returned nothing: %s', state['last_error'])
        except Exception as e:
            state['last_error'] = str(e)
            logging.error('Scan failed: %s', e)
        write_json_atomic(AP_FILE, state)
        time.sleep(max(5, SCAN_INTERVAL - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
