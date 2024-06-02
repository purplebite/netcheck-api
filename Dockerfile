
FROM python:3.8-slim

RUN apt-get update && apt-get install -y  netcat-openbsd iputils-ping iw curl wget gnupg1 apt-transport-https dirmngr redis-server  build-essential && rm -rf /var/lib/apt/lists/*

ENV API_KEY=""

ENV DEVICE="wlan0"

ENV PORT=80

ENV DEBUG=False

ENV SERVERID=False

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir Flask gunicorn speedtest-cli redis celery Flask-Caching
# RUN pip install redis celery


EXPOSE $PORT


CMD ["/bin/sh", "-c", "gunicorn -w 4 -b 0.0.0.0:$PORT  --timeout 120 app:app & redis-server --daemonize yes & celery -A app.celery worker --loglevel=info"]
