import ftplib
import ssl
import os
import time
from moviepy import VideoFileClip
from croniter import croniter
from datetime import datetime


FTP_HOST = os.getenv('FTP_HOST', '192.168.1.1')
FTP_PORT = int(os.getenv('FTP_PORT', 990))
FTP_USER = os.getenv('FTP_USER', 'bblp')
FTP_PASS = os.getenv('FTP_PASS', '12345678')
REMOTE_FOLDER = os.getenv('REMOTE_FOLDER', 'timelapse')
DOWNLOAD_FOLDER = os.getenv('LOCAL_FOLDER', '/Users/maclucky/Downloads/scripts/timelapse')
DELETE_FILES = os.getenv('DELETE_FILES', 'false')
CRON_SCHEDULE = os.getenv('CRON_SCHEDULE', '*/5 * * * *')  # Default: every 5 minutes

class ImplicitFTP_TLS(ftplib.FTP_TLS):
    """FTP_TLS subclass that automatically wraps sockets in SSL to support implicit FTPS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        """Return the socket."""
        return self._sock

    @sock.setter
    def sock(self, value):
        """When modifying the socket, ensure that it is ssl wrapped."""
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value

def convert_avi_to_mp4(input_file, output_file):
    """Convert .avi to .mp4 using moviepy."""
    try:
        print(f'Converting {input_file} to {output_file}')
        video_clip = VideoFileClip(input_file)
        video_clip.write_videofile(output_file, codec='libx264', bitrate='10000k')
        video_clip.close()
        print(f'Conversion to {output_file} successful.')
        os.remove(input_file)  # Delete the .avi file after conversion
        print(f'Removed original file {input_file}.')
    except Exception as e:
        print(f'Failed to convert {input_file} to {output_file}: {e}')

def ftp_download():
    try:
        if not os.path.exists(DOWNLOAD_FOLDER):
            os.makedirs(DOWNLOAD_FOLDER)

        downloaded_files = [f for f in os.listdir(DOWNLOAD_FOLDER) if f.endswith('.avi') or f.endswith('.mp4')]

        print(f'Connecting to printer {FTP_USER}@{FTP_HOST}:{FTP_PORT}')
        ftp_client = ImplicitFTP_TLS()
        ftp_client.connect(host=FTP_HOST, port=990)
        ftp_client.login(user=FTP_USER, passwd=FTP_PASS)
        ftp_client.prot_p()
        print('Connected.')
    except Exception as e:
        print(f'FTP connection failed, error: "{e}"')

    try:
        if REMOTE_FOLDER in ftp_client.nlst():
            ftp_client.cwd(REMOTE_FOLDER)
            try:
                print('Looking avi files for download.')
                ftp_timelapse_files = [f for f in ftp_client.nlst() if f.endswith('.avi')]
                ftp_timelapse_files = [f for f in ftp_timelapse_files if f not in downloaded_files]

                total_files = len(ftp_timelapse_files)
                if total_files:
                    print(f'Found {total_files} files for download.')
                    for idx, f in enumerate(ftp_timelapse_files, start=1):  # Track index using enumerate
                        mp4_file_name = f.replace('.avi', '.mp4')
                        if mp4_file_name in downloaded_files:
                            if DELETE_FILES == 'true':
                                try:
                                    ftp_client.delete(f)
                                except Exception as e:
                                    print(f'Failed to delete file {f} after download, continuing to next file.')
                                    continue
                            else:
                                print(f'Skipping {f} as {mp4_file_name} already exists.')
                                continue

                        filesize = ftp_client.size(f)
                        filesize_mb = round(filesize / 1024 / 1024, 2)
                        download_file_name = f
                        download_file_path = f'{DOWNLOAD_FOLDER}/{download_file_name}'
                        if filesize == 0:
                            print(f'Filesize of file {f} is 0, skipping file and continue')
                            continue
                        try:
                            print(f'Downloading file "{f}" ({idx} out of {total_files}), size: {filesize_mb} MB')
                            with open(download_file_path, 'wb') as fhandle:
                                ftp_client.retrbinary('RETR %s' % f, fhandle.write)

                            # Convert to mp4 after downloading
                            mp4_file_path = download_file_path.replace('.avi', '.mp4')
                            convert_avi_to_mp4(download_file_path, mp4_file_path)

                            if DELETE_FILES == 'true':
                                try:
                                    ftp_client.delete(f)
                                except Exception as e:
                                    print(f'Failed to delete file {f} after download, continuing to next file.')
                                    continue
                        except Exception as e:
                            if os.path.exists(download_file_path):
                                os.remove(download_file_path)
                            print(f'Failed to download file {f}: {e}, continuing with next file.')
                            continue
            except ftplib.error_perm as resp:
                if str(resp) == "550 No files found":
                    print("No files in this directory.")
                else:
                    raise
        else:
            print(f'{REMOTE_FOLDER} not found on FTP server.')
    except Exception as e:
        print(f'Program failed: {e}')

def get_next_run():
    """Calculate the next run time based on cron schedule."""
    iter = croniter(CRON_SCHEDULE, datetime.now())
    return iter.get_next(datetime)

# Main loop with cron scheduling
while True:
    ftp_download()
    next_run = get_next_run()
    now = datetime.now()
    wait_seconds = (next_run - now).total_seconds()
    print(f'Next run scheduled at {next_run.strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'Waiting for {int(wait_seconds)} seconds...')
    time.sleep(wait_seconds)
