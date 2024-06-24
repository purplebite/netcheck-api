#!/bin/bash

# Ensure PORT is set, otherwise default to 80
PORT=${PORT:-80}

# Create a cron job that runs every minute
echo "* * * * * root curl http://127.0.0.1:$PORT/set_accesspoints >> /var/log/cron.log 2>&1" > /etc/cron.d/mycron

# Give execution rights on the cron job
chmod 0644 /etc/cron.d/mycron

# Apply cron job
crontab /etc/cron.d/mycron

# Start cron in the foreground (useful for Docker)
cron
