
FROM python:3.8-slim

RUN apt-get update && apt-get install -y netcat-openbsd iputils-ping iw && rm -rf /var/lib/apt/lists/*

ENV API_KEY=""

ENV DEVICE="wlan0"

# ENV DEDUPLICATE=True

# Default port
ENV PORT=80

ENV DEBUG=False

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir Flask gunicorn

EXPOSE $PORT


CMD ["/bin/sh", "-c", "gunicorn -w 4 -b 0.0.0.0:$PORT app:app"]
