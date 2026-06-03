FROM python:3.11-slim

# Install system packages including espeak and ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    espeak \
    espeak-ng \
    flite \
    libespeak1 \
    libespeak-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY app.py .
COPY logo.png .

# Start the app
CMD gunicorn app:app --timeout 600 --workers 1 --bind 0.0.0.0:$PORT
