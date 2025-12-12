# Build stage - Use Alpine with uv for fast dependency installation
FROM python:3.12-alpine AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    ffmpeg

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY timelapse_downloader.py .

# Create virtual environment and install dependencies
RUN uv venv /venv && \
    uv pip install --python /venv/bin/python -r pyproject.toml

# Runtime stage - Use Alpine for smaller image
FROM python:3.12-alpine

# Install runtime dependencies (ffmpeg needed for moviepy)
RUN apk add --no-cache ffmpeg

# Set working directory
WORKDIR /app

# Copy virtual environment and application from builder
COPY --from=builder /venv /venv
COPY --from=builder /app/timelapse_downloader.py /app/

# Set environment path
ENV PATH="/venv/bin:$PATH"

# Create non-root user
RUN addgroup -g 1000 appgroup && \
    adduser -u 1000 -G appgroup -s /bin/sh -D appuser && \
    chown -R appuser:appgroup /app

# Switch to non-root user
USER appuser

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
