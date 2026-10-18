#!/bin/sh
# Background Wi-Fi scanner; restarted automatically if it ever exits.
(while true; do python /app/scanner.py; echo "scanner exited, restarting in 10s"; sleep 10; done) &

# API in the foreground. Short timeout: no request should take longer than a few seconds.
exec gunicorn -w "${WORKERS:-2}" -b "0.0.0.0:${PORT:-2025}" --timeout 30 --chdir /app app:app
