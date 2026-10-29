# paperbot – Papier-Handel (nur Spielgeld, keine Orders, keine Schlüssel nötig)
# Bauen:   docker build -t paperbot .
# Starten: docker run -d -p 8080:8080 -v paperbot-data:/app/data paperbot
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PAPERBOT_STATE_DIR=/app/data/paperbot \
    PAPERBOT_REPORT_DIR=/app/data/reports \
    PORT=8080

WORKDIR /app
COPY requirements-paperbot.txt .
RUN pip install --no-cache-dir -r requirements-paperbot.txt

COPY paperbot/ paperbot/
COPY tests/ tests/
COPY docs/ docs/
COPY results/ results/
# Kein Start ohne grüne Tests (u. a. der Nur-Papiergeld-Test)
RUN python -m pytest tests -q -p no:cacheprovider

# Ohne Root laufen; Zustand liegt im Volume /app/data
RUN useradd --create-home bot && mkdir -p /app/data && chown -R bot /app/data
USER bot

EXPOSE 8080
HEALTHCHECK --interval=5m --timeout=10s --start-period=2m \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/health', timeout=5)"

CMD ["python", "-m", "paperbot", "serve", "--source", "kalshi", "--interval", "30"]
