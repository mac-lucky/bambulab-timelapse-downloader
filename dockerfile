# Build stage - Use Alpine for smaller size and faster builds
FROM python:3.12-alpine AS builder

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    && python -m venv /venv \
    && /venv/bin/pip install --upgrade pip setuptools wheel

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN /venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY timelapse_downloader.py .

# Runtime stage - Use distroless Python image for maximum security
FROM gcr.io/distroless/python3-debian12

# Copy virtual environment and application
COPY --from=builder /venv /venv
COPY --from=builder /app/timelapse_downloader.py /app/

# Set working directory and environment
WORKDIR /app
ENV PATH="/venv/bin:$PATH"

# Set default environment variables (can be overridden at runtime)
ENV FTP_HOST=192.168.1.1 \
    FTP_PORT=990 \
    FTP_USER=bblp \
    FTP_PASS=12345678 \
    REMOTE_FOLDER=timelapse \
    LOCAL_FOLDER=/timelapse \
    DELETE_FILES=false \
    CRON_SCHEDULE='*/5 * * * *'

# Run application
ENTRYPOINT ["/venv/bin/python", "-u", "timelapse_downloader.py"]