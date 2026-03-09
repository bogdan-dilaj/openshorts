# Multi-stage build for smaller final image
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
# Copy and install Python dependencies
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

# Install FFmpeg, OpenCV dependencies, and Node.js (for yt-dlp JS challenges)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    fonts-noto-color-emoji \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV HOME=/tmp
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV XDG_CONFIG_HOME=/tmp/.config
ENV XDG_CACHE_HOME=/tmp/.cache
ENV HF_HOME=/tmp/.cache/huggingface
ENV HUGGINGFACE_HUB_CACHE=/tmp/.cache/huggingface/hub
ENV TRANSFORMERS_CACHE=/tmp/.cache/huggingface/transformers
ENV NUMBA_CACHE_DIR=/tmp/.cache/numba
ENV YOLO_MODEL_PATH=/tmp/Ultralytics/yolov8n.pt

# Always upgrade yt-dlp to latest (YouTube bot-detection changes frequently)
RUN pip install --upgrade --no-cache-dir yt-dlp

# Copy application code
COPY . .

# Create a non-root user (Moved up)
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

# Create writable runtime/cache directories outside the bind mount
RUN mkdir -p /app/uploads /app/output /tmp/Ultralytics /tmp/matplotlib /tmp/.config /tmp/.cache/huggingface /tmp/.cache/numba
# Fix permissions for app data and all runtime caches
RUN chown -R appuser:appuser /app /tmp/Ultralytics /tmp/matplotlib /tmp/.config /tmp/.cache

# Switch to non-root user
USER appuser

# Pre-download YOLO model into a writable runtime path that is not hidden by the /app bind mount
RUN python -c "from ultralytics import YOLO; YOLO('/tmp/Ultralytics/yolov8n.pt')"

# Expose FastAPI port
EXPOSE 8000

# Run FastAPI app
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
