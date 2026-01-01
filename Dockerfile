# Use Python 3.12 slim image
FROM python:3.12-slim

# Install system dependencies (FFmpeg)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Set Python path
ENV PYTHONPATH=/app

# Default command (expected to be overridden by Cloud Run Job arguments)
ENTRYPOINT ["python", "-m", "app.main"]
