# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the required files into the container
COPY timelapse_downloader.py requirements.txt ./

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Set default environment variables (can be overridden at runtime)
ENV FTP_HOST=192.168.1.1 \
    FTP_PORT=990 \
    FTP_USER=bblp \
    FTP_PASS=12345678 \
    REMOTE_FOLDER=timelapse \
    LOCAL_FOLDER=/timelapse \
    DELETE_FILES=false \
    CRON_SCHEDULE='*/5 * * * *'

# Command to run the script
CMD ["python", "-u", "timelapse_downloader.py"]