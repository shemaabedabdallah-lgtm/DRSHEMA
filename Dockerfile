FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    espeak \
    espeak-ng \
    libespeak1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY logo.png* ./

CMD gunicorn app:app --timeout 600 --workers 1 --bind 0.0.0.0:$PORT
