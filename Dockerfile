# Build stage - Use official uv image for fast dependency installation.
# Pinned to an exact uv release: the floating python3.12-alpine tag moves
# underneath the resolver and would change what gets installed between builds.
FROM ghcr.io/astral-sh/uv:0.12.2-python3.12-alpine@sha256:2f78017b6eb469a2f838c7dd77cc3018a9f86489f68af399526b5721a23d6d78 AS builder

# Install build dependencies
RUN apk add --no-cache \
    gcc \
    musl-dev \
    python3-dev \
    ffmpeg

# Set working directory
WORKDIR /app

# Copy project files. uv.lock, not just pyproject.toml: installing from the
# loose ranges in pyproject resolves whatever is newest at build time, so the
# image would not contain the versions CI tested against with --locked.
COPY pyproject.toml uv.lock .
COPY timelapse_downloader.py .

ENV UV_PROJECT_ENVIRONMENT=/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# --no-install-project skips building the script's own wheel, which is what
# makes it safe to copy only the files above.
RUN uv sync --locked --no-dev --no-install-project

# Runtime stage - same pinned image as the builder, for a matching Python build
FROM ghcr.io/astral-sh/uv:0.12.2-python3.12-alpine@sha256:2f78017b6eb469a2f838c7dd77cc3018a9f86489f68af399526b5721a23d6d78

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
