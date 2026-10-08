# E-Waste AI Workload — MobileNetV2 Image Classification
# Optimized for CPU-only old/retired hardware

FROM python:3.10-slim

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install minimal system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy model files (baked into image to avoid runtime downloads)
COPY models/ /models/

# Copy inference script
COPY run_inference.py .

# Define input/output mount points
VOLUME ["/data/input", "/data/output"]

# Container entrypoint
CMD ["python", "run_inference.py"]
