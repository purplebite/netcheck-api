FROM python:3.8-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y cron curl netcat-openbsd iputils-ping iw wget gnupg1 apt-transport-https dirmngr build-essential && \
    rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV API_KEY=""
ENV DEVICE="wlan0"
ENV PORT=80
ENV SERVER_ID=38461
ENV DEBUG=False
ENV SCAN_CRON=30
ENV SERVERID=False

# Add and set up cron
COPY setup-cron.sh /usr/local/bin/setup-cron.sh
RUN chmod +x /usr/local/bin/setup-cron.sh
RUN touch /var/log/cron.log

# Set the working directory
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install Python packages
RUN pip install --no-cache-dir Flask gunicorn speedtest-cli redis celery Flask-Caching

# Expose the desired port
EXPOSE $PORT

# Start the cron and Flask app with Celery worker
CMD /usr/local/bin/setup-cron.sh && \
    celery -A app.celery worker --loglevel=info & \
    gunicorn -w 4 -b 0.0.0.0:$PORT --timeout 120 app:app
