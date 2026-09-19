FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    YTTV_EPG_PORT=8095 \
    YTTV_EPG_DATA_DIR=/data \
    ENABLE_CHROME=1 \
    DISPLAY=:99 \
    CHROME_PROFILE=/data/chrome-profile

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        fonts-dejavu-core \
        fonts-liberation \
        novnc \
        openbox \
        python3-websockify \
        x11vnc \
        xvfb \
    && mkdir -p /etc/chromium/policies/managed \
    && rm -rf /var/lib/apt/lists/*

COPY chromium-policy.json /etc/chromium/policies/managed/yttv.json
COPY pyproject.toml requirements.txt README.md LICENSE ./
COPY src ./src
COPY entrypoint.sh /app/entrypoint.sh

RUN pip install --no-cache-dir . \
    && chmod +x /app/entrypoint.sh

VOLUME ["/data"]
EXPOSE 8095 7900

HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8095/health', timeout=4)"

ENTRYPOINT ["/app/entrypoint.sh"]
