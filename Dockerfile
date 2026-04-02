FROM python:3.11-slim

# Install FFmpeg and fonts
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

# Set working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot/ ./bot/

# Create temp directory with correct permissions
RUN mkdir -p temp && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Run bot
# NOTE: Make sure to pass .env file when running:
# docker run -d --env-file .env --name circle-bot circle-overlay-bot
CMD ["python", "-m", "bot"]
