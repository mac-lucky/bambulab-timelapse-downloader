"""Conversion behaviour.

The ffmpeg-backed tests are skipped when no binary can be resolved. The binary
comes from imageio-ffmpeg, which moviepy itself uses and which ships bundled in
the wheel, so this needs no system package.
"""

import subprocess

import pytest

import timelapse_downloader as tld
from tests.conftest import FakeFTP

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None


def _ffmpeg():
    """Path to the ffmpeg moviepy itself uses, or None if it cannot be resolved."""
    if imageio_ffmpeg is None:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


FFMPEG = _ffmpeg()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="no ffmpeg binary available")


@pytest.fixture
def tiny_avi(tmp_path):
    """A one second 64x48 test pattern, small enough to convert instantly."""
    path = tmp_path / "clip.avi"
    subprocess.run(
        [
            FFMPEG,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x48:rate=5",
            "-t",
            "1",
            str(path),
        ],
        check=True,
    )
    return path


@pytest.fixture
def failing_clips(monkeypatch):
    """Replace VideoFileClip with a stub whose write fails; yields the instances.

    A real video cannot exercise this: the leak guarded against is our own
    failure to release the clip when write_videofile raises, and a corrupt input
    fails during construction, before any reader exists.
    """
    created = []

    class FailingClip:
        def __init__(self, path):
            self.path = path
            self.closed = False
            created.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()
            return False

        def close(self):
            self.closed = True

        def write_videofile(self, filename, *args, **kwargs):
            self.target = filename
            raise RuntimeError("encoder exploded")

    monkeypatch.setattr(tld, "VideoFileClip", FailingClip)
    return created


def test_clip_is_released_even_when_the_write_fails(tmp_path, failing_clips):
    # Was: close() sat after write_videofile, so a failing write leaked the
    # ffmpeg reader subprocess and its pipes for the life of the container.
    src = tmp_path / "clip.avi"
    src.write_bytes(b"pretend video")

    assert tld.convert_avi_to_mp4(str(src), str(tmp_path / "clip.mp4")) is False

    assert len(failing_clips) == 1
    assert failing_clips[0].closed, "clip was not closed after a failed write"


def test_failed_conversion_removes_a_leftover_output(tmp_path, failing_clips):
    # A half-written .mp4 would look like a finished conversion next run, and
    # get the printer's copy deleted.
    src = tmp_path / "clip.avi"
    src.write_bytes(b"pretend video")
    out = tmp_path / "clip.mp4"
    out.write_bytes(b"partial output from a crashed run")

    assert tld.convert_avi_to_mp4(str(src), str(out)) is False

    assert not out.exists()
    assert src.exists(), "the source must survive so a later run can retry"


def test_the_encode_goes_to_a_scratch_name_and_leaves_none_behind(
    tmp_path, failing_clips
):
    # Was: moviepy wrote straight to clip.mp4, so a run killed mid-encode left
    # an .mp4 that the next run took for a finished conversion.
    src = tmp_path / "clip.avi"
    src.write_bytes(b"pretend video")
    (tmp_path / "clip.tmp.mp4").write_bytes(b"left by a killed run")

    assert tld.convert_avi_to_mp4(str(src), str(tmp_path / "clip.mp4")) is False

    assert failing_clips[0].target == str(tmp_path / "clip.tmp.mp4")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.avi"]


def test_a_local_avi_the_printer_does_not_list_is_left_alone(
    run_download, local_names, tmp_path, failing_clips
):
    # The folder may hold the owner's own videos: only names the printer still
    # lists are retried.
    (tmp_path / "mine.avi").write_bytes(b"not from the printer")

    run_download(FakeFTP({"other.mp4": b"video"}), delete_files=True)

    assert failing_clips == []
    assert local_names() == ["mine.avi", "other.mp4"]


def test_a_stranded_avi_that_differs_from_the_printer_copy_is_fetched_again(
    run_download, tmp_path, failing_clips
):
    (tmp_path / "clip.avi").write_bytes(b"cut short")

    fake = run_download(FakeFTP({"clip.avi": b"the whole recording"}))

    assert fake.retrieved == ["clip.avi"]
    assert (tmp_path / "clip.avi").read_bytes() == b"the whole recording"


@needs_ffmpeg
def test_conversion_writes_the_mp4_and_removes_the_source(tiny_avi, tmp_path):
    out = tmp_path / "clip.mp4"
    assert tld.convert_avi_to_mp4(str(tiny_avi), str(out)) is True
    assert out.exists() and out.stat().st_size > 0
    assert not tiny_avi.exists()
    assert not (tmp_path / "clip.tmp.mp4").exists()


@needs_ffmpeg
def test_real_corrupt_input_fails_without_leaving_an_output(tmp_path):
    bad = tmp_path / "corrupt.avi"
    bad.write_bytes(b"RIFF\x00\x00\x00\x00AVI LIST" + b"\x00" * 512)
    out = tmp_path / "corrupt.mp4"

    assert tld.convert_avi_to_mp4(str(bad), str(out)) is False
    assert not out.exists()
    assert bad.exists()


@needs_ffmpeg
def test_a_downloaded_avi_is_converted_end_to_end(run_download, local_names, tiny_avi):
    raw = tiny_avi.read_bytes()
    tiny_avi.unlink()

    fake = run_download(FakeFTP({"clip.avi": raw}), delete_files=True)

    # The .avi is replaced by the .mp4, and only then is the remote copy dropped.
    assert local_names() == ["clip.mp4"]
    assert fake.deleted == ["clip.avi"]


@needs_ffmpeg
def test_a_failed_conversion_keeps_the_printer_copy(run_download, local_names):
    # Was: the remote original was deleted even when conversion failed, leaving
    # the video stranded locally as an .avi that would never be retried.
    fake = run_download(FakeFTP({"clip.avi": b"not a real video"}), delete_files=True)

    assert fake.deleted == []
    assert local_names() == ["clip.avi"]


@needs_ffmpeg
def test_a_failed_conversion_is_retried_on_the_next_run(
    run_download, local_names, tiny_avi, tmp_path, monkeypatch
):
    # Was: the stranded clip.avi counted as downloaded, so it was never
    # converted and the printer copy was never deleted.
    raw = tiny_avi.read_bytes()
    tiny_avi.unlink()
    real_clip = tld.VideoFileClip

    class BrokenEncoder:
        def __init__(self, path):
            raise RuntimeError("encoder unavailable")

    monkeypatch.setattr(tld, "VideoFileClip", BrokenEncoder)
    first = run_download(FakeFTP({"clip.avi": raw}), delete_files=True)
    assert first.deleted == []
    assert local_names() == ["clip.avi"]

    monkeypatch.setattr(tld, "VideoFileClip", real_clip)
    (tmp_path / "clip.tmp.mp4").write_bytes(b"left by a killed run")
    second = run_download(FakeFTP({"clip.avi": raw}), delete_files=True)

    assert second.retrieved == [], "the local copy is converted, not fetched again"
    assert second.deleted == ["clip.avi"]
    assert local_names() == ["clip.mp4"]
