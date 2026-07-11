FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home whalebot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY app ./app
COPY config ./config

RUN mkdir -p /app/data /app/logs && chown -R whalebot:whalebot /app

USER whalebot

ENV WHALEBOT_HOST=0.0.0.0 \
    PORT=8080 \
    WHALEBOT_DATA_DIR=/app/data \
    WHALEBOT_LOG_DIR=/app/logs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8080\")}/healthz', timeout=4)"

CMD ["python", "main.py"]
