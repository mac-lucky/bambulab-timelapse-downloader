# FTP over implicit TLS (FTPS) is required by Bambu Lab printers.
import ftplib  # nosec B402
import os
import posixpath
import ssl
import time
from datetime import datetime

from croniter import croniter
from moviepy import VideoFileClip

FTP_HOST = os.getenv("FTP_HOST", "192.168.1.1")
FTP_PORT = int(os.getenv("FTP_PORT", "990"))
FTP_USER = os.getenv("FTP_USER", "bblp")
FTP_PASS = os.getenv("FTP_PASS", "12345678")
REMOTE_FOLDER = os.getenv("REMOTE_FOLDER", "timelapse")
DOWNLOAD_FOLDER = os.getenv("LOCAL_FOLDER", "/timelapse")
DELETE_FILES = os.getenv("DELETE_FILES", "false").strip().lower() in (
    "true",
    "1",
    "yes",
    "on",
)
CRON_SCHEDULE = os.getenv("CRON_SCHEDULE", "*/5 * * * *")  # Default: every 5 minutes

VIDEO_SUFFIXES = (".avi", ".mp4")


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

    def ntransfercmd(self, cmd, rest=None):
        """Override to reuse the TLS session for data connections (required by some printers like P2S)."""
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session
            )
        return conn, size


def mp4_name(name):
    """Return the .mp4 name a given .avi converts to."""
    return name[: -len(".avi")] + ".mp4"


def remove_quietly(path):
    """Delete a file, ignoring the case where it is not there."""
    try:
        os.remove(path)
    except OSError:
        pass


def convert_avi_to_mp4(input_file, output_file):
    """Convert .avi to .mp4 using moviepy. Returns True on success."""
    try:
        print(f"Converting {input_file} to {output_file}")
        # The context manager closes the ffmpeg reader subprocess even if the write fails.
        with VideoFileClip(input_file) as video_clip:
            video_clip.write_videofile(output_file, codec="libx264", bitrate="10000k")
        print(f"Conversion to {output_file} successful.")
        os.remove(input_file)
        print(f"Removed original file {input_file}.")
        return True
    except Exception as e:
        print(f"Failed to convert {input_file} to {output_file}: {e}")
        # A partial .mp4 would look like a finished conversion on the next run.
        remove_quietly(output_file)
        return False


def safe_local_name(remote_name):
    """Map a remote listing entry to a basename safe to join onto DOWNLOAD_FOLDER.

    Returns None for entries we refuse to touch. Rejecting CRLF also keeps the
    entry out of the FTP command stream, where it would mean command injection.
    """
    if "\r" in remote_name or "\n" in remote_name or "\x00" in remote_name:
        return None
    # posixpath, not os.path: FTP pathnames are always "/"-separated (RFC 959),
    # whatever the OS this happens to run on.
    name = posixpath.basename(remote_name.rstrip("/"))
    if not name or name in (".", ".."):
        return None
    return name


def list_remote_files(ftp_client, downloaded_files):
    """Return (remote entry, local name) pairs for timelapses we do not have yet."""
    pending = []
    for entry in ftp_client.nlst():
        if not entry.endswith(VIDEO_SUFFIXES):
            continue
        local_name = safe_local_name(entry)
        if local_name is None:
            print(f"Skipping remote entry with unusable name: {entry!r}")
            continue
        if local_name not in downloaded_files:
            pending.append((entry, local_name))
    return pending


def delete_remote(ftp_client, remote):
    """Delete a file on the printer, reporting failure rather than raising."""
    try:
        ftp_client.delete(remote)
        return True
    except Exception as e:
        print(f"Failed to delete file {remote}: {e}, continuing to next file.")
        return False


def download_one(ftp_client, remote, local_name, label):
    """Download a single timelapse, converting .avi to .mp4, then delete the remote copy."""
    download_file_path = os.path.join(DOWNLOAD_FOLDER, local_name)
    # Transfer into a scratch name and rename on completion. A half-written file
    # under the real name would be indistinguishable from a finished download on
    # the next run, so the video would be skipped forever.
    partial_path = download_file_path + ".part"
    try:
        filesize = ftp_client.size(remote)
        if not filesize:
            print(
                f"Filesize of file {remote} is {filesize}, skipping file and continue"
            )
            return
        filesize_mb = round(filesize / 1024 / 1024, 2)

        print(f'Downloading file "{remote}" ({label}), size: {filesize_mb} MB')
        with open(partial_path, "wb") as fhandle:
            ftp_client.retrbinary(f"RETR {remote}", fhandle.write)
        os.replace(partial_path, download_file_path)

        # Convert .avi to .mp4, download .mp4 as-is
        if local_name.endswith(".avi"):
            mp4_file_path = os.path.join(DOWNLOAD_FOLDER, mp4_name(local_name))
            if not convert_avi_to_mp4(download_file_path, mp4_file_path):
                # Keep the printer's copy so a later run can retry the conversion.
                return
    except Exception as e:
        remove_quietly(partial_path)
        remove_quietly(download_file_path)
        print(f"Failed to download file {remote}: {e}, continuing with next file.")
        return

    if DELETE_FILES:
        delete_remote(ftp_client, remote)


def ftp_download():
    try:
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
        downloaded_files = {
            f for f in os.listdir(DOWNLOAD_FOLDER) if f.endswith(VIDEO_SUFFIXES)
        }

        print(f"Connecting to printer {FTP_USER}@{FTP_HOST}:{FTP_PORT}")
        ftp_client = ImplicitFTP_TLS()
        ftp_client.connect(host=FTP_HOST, port=FTP_PORT)
        ftp_client.login(user=FTP_USER, passwd=FTP_PASS)
        ftp_client.prot_p()
        print("Connected.")
    except Exception as e:
        print(f'FTP connection failed, error: "{e}"')
        return

    try:
        # FTP.__exit__ quits the session and closes the socket; without it the
        # daemon leaks one FTPS connection per scheduled run.
        with ftp_client:
            if REMOTE_FOLDER not in ftp_client.nlst():
                print(f"{REMOTE_FOLDER} not found on FTP server.")
                return
            ftp_client.cwd(REMOTE_FOLDER)

            print("Looking for timelapse files to download.")
            try:
                pending = list_remote_files(ftp_client, downloaded_files)
            except ftplib.error_perm as resp:
                if str(resp).startswith("550"):
                    print(f"No files in this directory ({resp}).")
                    return
                raise

            if not pending:
                return
            print(f"Found {len(pending)} files for download.")
            for idx, (remote, local_name) in enumerate(pending, start=1):
                converted = local_name.endswith(".avi") and (
                    mp4_name(local_name) in downloaded_files
                )
                if converted:
                    if DELETE_FILES and delete_remote(ftp_client, remote):
                        print(f"Deleted remote {remote}, already converted locally.")
                    elif not DELETE_FILES:
                        print(f"Skipping {remote}, already converted locally.")
                    continue

                download_one(
                    ftp_client, remote, local_name, f"{idx} out of {len(pending)}"
                )
    except Exception as e:
        print(f"Program failed: {e}")


def now_local():
    """Current time, aware, in the container's own timezone (TZ env var)."""
    return datetime.now().astimezone()


def get_next_run():
    """Calculate the next run time based on cron schedule."""
    cron_iter = croniter(CRON_SCHEDULE, now_local())
    return cron_iter.get_next(datetime)


def main():
    """Run the download on the configured cron schedule, forever."""
    while True:
        ftp_download()
        next_run = get_next_run()
        now = now_local()
        wait_seconds = (next_run - now).total_seconds()
        print(f"Next run scheduled at {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Waiting for {int(wait_seconds)} seconds...")
        time.sleep(max(0, wait_seconds))


if __name__ == "__main__":
    main()
