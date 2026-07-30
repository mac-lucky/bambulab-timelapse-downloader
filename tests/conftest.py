"""Shared fixtures.

The daemon reads its configuration into module globals and constructs its FTP
client inline, both at call time, so tests point the module at a tmp_path and
swap in a fake client with monkeypatch instead of touching production code.
"""

import ftplib

import pytest

import timelapse_downloader as tld


class FakeFTP:
    """Stand-in for ImplicitFTP_TLS covering only what the daemon calls.

    `nlst()` answers the root listing until `cwd()` has been called, then the
    file listing, which is how the real flow probes for REMOTE_FOLDER first.
    """

    def __init__(
        self, files=None, fail_on=None, size_fails=(), remote_folder="timelapse"
    ):
        self.files = dict(files or {})
        self.fail_on = fail_on
        self.size_fails = set(size_fails)
        self.remote_folder = remote_folder
        # What the server advertises at the root, independent of the folder the
        # daemon is configured to look for, so a mismatch can be tested.
        self.root_listing = [remote_folder]
        self.deleted = []
        self.retrieved = []
        self.commands = []
        self.cwd_called = False
        self.closed = False

    def connect(self, host=None, port=None):
        self.commands.append(f"connect:{host}:{port}")
        if self.fail_on == "connect":
            raise OSError("connection refused")

    def login(self, user=None, passwd=None):
        if self.fail_on == "login":
            raise ftplib.error_perm("530 Login incorrect")

    def prot_p(self):
        if self.fail_on == "prot_p":
            raise ftplib.error_perm("534 Policy denies")

    def nlst(self):
        self.commands.append("nlst")
        if self.fail_on == "nlst":
            raise ftplib.error_perm("550 No files found")
        return list(self.files) if self.cwd_called else list(self.root_listing)

    def cwd(self, folder):
        self.commands.append(f"cwd:{folder}")
        self.cwd_called = True

    def size(self, name):
        self.commands.append(f"size:{name}")
        if name in self.size_fails:
            raise ftplib.error_perm(f"550 {name}: Permission denied")
        if name not in self.files:
            raise ftplib.error_perm(f"550 {name}: No such file or directory")
        return len(self.files[name])

    def retrbinary(self, cmd, callback):
        name = cmd[len("RETR ") :]
        self.commands.append(f"retr:{name}")
        if name not in self.files:
            raise ftplib.error_perm(f"550 {name}: No such file")
        self.retrieved.append(name)
        callback(self.files[name])

    def delete(self, name):
        self.commands.append(f"delete:{name}")
        if name not in self.files:
            raise ftplib.error_perm(f"550 {name}: No such file")
        del self.files[name]
        self.deleted.append(name)

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True

    # ftplib.FTP is a context manager and ftp_download relies on `with`; without
    # these every test would silently fall into the "Program failed" handler.
    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.quit()
        except (OSError, EOFError):
            self.close()


@pytest.fixture
def run_download(tmp_path, monkeypatch):
    """Point the module at tmp_path and run ftp_download against a fake client."""

    def _run(fake, delete_files=False):
        monkeypatch.setattr(tld, "DOWNLOAD_FOLDER", str(tmp_path))
        monkeypatch.setattr(tld, "DELETE_FILES", delete_files)
        monkeypatch.setattr(tld, "REMOTE_FOLDER", fake.remote_folder)
        monkeypatch.setattr(tld, "ImplicitFTP_TLS", lambda: fake)
        tld.ftp_download()
        return fake

    return _run


@pytest.fixture
def local_names(tmp_path):
    """Names of files currently in the download folder."""
    return lambda: sorted(p.name for p in tmp_path.iterdir())
