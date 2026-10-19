FROM python:3.12-slim

# Install system libraries needed by OpenCV, Open3D, and PyCOLMAP
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libegl1 \
    libglib2.0-0 \
    libgomp1 \
    libusb-1.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source and scripts
COPY src/ /app/src/
COPY scripts/ /app/scripts/

# Create ephemeral directory for outputs
RUN mkdir -p /app/outputs

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV VISIONFORGE_OUTPUTS_ROOT=/app/outputs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "uvicorn visionforge.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
