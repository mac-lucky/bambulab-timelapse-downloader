<img src="icon.svg" width="96" align="right" alt="">

# bambulab-timelapse-downloader

Automated tool to download and convert timelapse videos from Bambu Lab 3D printers.

[![Docker Pulls](https://img.shields.io/docker/pulls/maclucky/bambulab-timelapse-downloader)](https://hub.docker.com/r/maclucky/bambulab-timelapse-downloader)
[![Docker Image Version](https://img.shields.io/docker/v/maclucky/bambulab-timelapse-downloader/latest)](https://hub.docker.com/r/maclucky/bambulab-timelapse-downloader/tags)
[![GitHub Actions Workflow Status](https://github.com/mac-lucky/bambulab-timelapse-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/mac-lucky/bambulab-timelapse-downloader/actions/workflows/ci.yml)
[![Platform](https://img.shields.io/badge/platform-amd64%20%7C%20arm64-blue)](https://hub.docker.com/r/maclucky/bambulab-timelapse-downloader/tags)

## Features

- Automatic download of timelapse videos from Bambu Lab printer via FTP
- Converts .avi files to .mp4 format
- Configurable scheduling using cron expressions
- Optional automatic deletion of source files after download
- Docker support for easy deployment

## Prerequisites

Before this tool can connect to your printer, you need to enable LAN access on the printer itself. The menu path **differs per model**:

| Model | Path on printer touchscreen |
|---|---|
| X1 / X1C / X1E / H2 / P2S | Settings → **LAN Only** → enable **LAN Only Mode** (and **Developer Mode** if shown) |
| P1P / P1S | Settings → **WLAN** → **LAN Only Mode** |
| A1 / A1 mini | Settings → scroll to page 3 → **LAN Only Mode** |

Then:

1. Note the **Access Code** (8-digit code) shown on the same settings page — this is your `FTP_PASS`.
2. The FTP user is always `bblp` and the port is `990` (FTPS / implicit TLS).
3. On current firmware you may also need to enable **Developer Mode** to expose FTPS to third-party clients.
4. Make sure port `990` isn't blocked by a firewall/VLAN between the container and the printer.

> Note: **LAN Only Mode** severs the Bambu Cloud connection (no Handy app / remote printing). **LAN Mode Liveview** is a separate sub-toggle for the camera stream, not required for FTP.

References: [Enable LAN Mode](https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode) · [Enable Developer Mode](https://wiki.bambulab.com/en/knowledge-sharing/enable-developer-mode)

## Setup

### Environment Variables

- `FTP_HOST`: Printer IP address (default: 192.168.1.1)
- `FTP_PORT`: FTP port (default: 990)
- `FTP_USER`: FTP username (default: bblp)
- `FTP_PASS`: FTP password (default: 12345678)
- `REMOTE_FOLDER`: Remote folder path (default: timelapse)
- `LOCAL_FOLDER`: Local download directory (default: /timelapse)
- `DELETE_FILES`: Whether to delete source files after download (default: false)
- `CRON_SCHEDULE`: Schedule for running downloads (default: */5 * * * *)

## Usage

### Using Pre-built Docker Images

You can use the pre-built Docker images from Docker Hub or GitHub Container Registry:

```bash
# From Docker Hub
docker pull maclucky/bambulab-timelapse-downloader:latest

# From GitHub Container Registry
docker pull ghcr.io/mac-lucky/bambulab-timelapse-downloader:latest
```

Both AMD64 and ARM64 architectures are supported.

### Using Docker

1. Build the container:
```bash
docker build -t bambulab-timelapse-downloader .
```

2. Run the container:
```bash
docker run -d \
  -e FTP_HOST=your_printer_ip \
  -e FTP_PASS=your_password \
  -e CRON_SCHEDULE="*/5 * * * *" \
  -v /path/to/local/folder:/timelapse \
  bambulab-timelapse-downloader
```
or prebuilt image:
```bash
docker run -d \
  -e FTP_HOST=your_printer_ip \
  -e FTP_PASS=your_password \
  -e CRON_SCHEDULE="*/5 * * * *" \
  -v /path/to/local/folder:/timelapse \
  maclucky/bambulab-timelapse-downloader
```

### Running Locally

1. Install dependencies using uv:
```bash
uv pip install -r pyproject.toml
```

Or using pip:
```bash
pip install moviepy croniter
```

2. Run the script:
```bash
python timelapse_downloader.py
```

## Requirements

- Python 3.12+
- moviepy>=2.2.1
- croniter>=6.0.0

## How It Works

The script connects to your Bambu Lab printer via FTP, downloads timelapse videos (`.avi` format), converts them to `.mp4`, and optionally deletes the source files. It runs on a schedule defined by the CRON_SCHEDULE environment variable.

