FROM python:3.12-slim

# Runtime tools only: iw (Wi-Fi scan), ping, iproute2 (ip-info)
# upgrade pulls in Debian security fixes released after the base image was built
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends iw iputils-ping iproute2 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV PORT=2025 \
    DEVICE=wlan0 \
    SCAN_CRON=5 \
    WORKERS=2 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
# pip is only needed at build time; removing it drops its CVEs from the final image
RUN pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pip
COPY app.py common.py scanner.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE $PORT
CMD ["/app/entrypoint.sh"]
