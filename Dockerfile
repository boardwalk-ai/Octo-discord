FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The bot connects out to Discord over a WebSocket; it exposes no ports.
# Provide secrets via --env-file .env and persist the SQLite DB with a volume.
CMD ["python", "bot.py"]
