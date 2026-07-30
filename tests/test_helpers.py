"""Pure helpers: name mapping, safe deletion, filename sanitisation, clock."""

import os
from datetime import datetime

import pytest

import timelapse_downloader as tld

FIVE_MINUTES = 300


def test_mp4_name_only_replaces_the_suffix():
    assert tld.mp4_name("clip.avi") == "clip.mp4"
    # A bare .replace() would rewrite both occurrences here.
    assert tld.mp4_name("a.avi.old.avi") == "a.avi.old.mp4"


def test_remove_quietly_is_a_noop_when_absent(tmp_path):
    target = tmp_path / "gone.mp4"
    tld.remove_quietly(str(target))  # must not raise
    target.write_bytes(b"x")
    tld.remove_quietly(str(target))
    assert not target.exists()


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("video_2024-01-01.avi", "video_2024-01-01.avi"),
        # Traversal is reduced to a basename rather than rejected.
        ("../../evil.mp4", "evil.mp4"),
        ("/etc/evil.mp4", "evil.mp4"),
        ("../../../root/.ssh/authorized_keys.mp4", "authorized_keys.mp4"),
        # Servers may legitimately answer NLST with a path.
        ("timelapse/v.avi", "v.avi"),
        # Control characters would be FTP command injection, NUL breaks open().
        ("a\r\nDELE x.mp4", None),
        ("a\nNOOP.avi", None),
        ("a\x00b.mp4", None),
        ("", None),
        (".", None),
        ("..", None),
    ],
)
def test_safe_local_name(remote, expected):
    assert tld.safe_local_name(remote) == expected


@pytest.mark.parametrize(
    "remote",
    [
        "../../evil.mp4",
        "/etc/evil.mp4",
        "../../../root/.ssh/authorized_keys.mp4",
        "timelapse/v.avi",
        "video.avi",
    ],
)
def test_accepted_names_cannot_escape_the_download_folder(remote):
    folder = "/timelapse"
    name = tld.safe_local_name(remote)
    assert name is not None
    joined = os.path.abspath(os.path.join(folder, name))
    assert os.path.commonpath([joined, folder]) == folder


def test_backslashes_are_a_filename_not_a_separator():
    # posixpath is used deliberately: FTP paths are "/"-separated whatever the
    # host OS, so a Windows-style name stays one literal (contained) filename.
    assert tld.safe_local_name(r"..\..\etc\passwd.mp4") == r"..\..\etc\passwd.mp4"


def test_now_local_is_timezone_aware():
    now = tld.now_local()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None


def test_get_next_run_keeps_tzinfo_and_stays_in_the_cron_window(monkeypatch):
    # Guards the DTZ005 fix: making the clock aware must not silently move the
    # schedule to UTC, and croniter must hand back an aware datetime.
    monkeypatch.setattr(tld, "CRON_SCHEDULE", "*/5 * * * *")
    now = tld.now_local()
    nxt = tld.get_next_run()
    assert isinstance(nxt, datetime)
    assert nxt.tzinfo is not None
    assert nxt.utcoffset() == now.utcoffset()
    assert 0 < (nxt - now).total_seconds() <= FIVE_MINUTES
