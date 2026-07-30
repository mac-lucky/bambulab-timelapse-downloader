"""One test per bug that was live in this repo.

Each name says what breaks if the test goes red, so a future failure points at
the behaviour rather than at the assertion.
"""

from tests.conftest import FakeFTP


def test_deleting_an_already_converted_avi_does_not_abort_the_batch(
    run_download, local_names, tmp_path
):
    # Was: the remote .avi got deleted, then SIZE ran against the file that had
    # just been removed, raising 550 outside the per-file try and ending the run.
    (tmp_path / "a.mp4").write_bytes(b"already converted")
    fake = run_download(
        FakeFTP({"a.avi": b"raw", "b.mp4": b"bbbb", "c.mp4": b"cccc"}),
        delete_files=True,
    )

    assert "a.avi" in fake.deleted
    assert "size:a.avi" not in fake.commands
    assert local_names() == ["a.mp4", "b.mp4", "c.mp4"]


def test_one_failing_size_does_not_abort_the_batch(run_download, local_names):
    # SIZE used to sit outside the per-file try, so a single 550 killed the run.
    fake = run_download(
        FakeFTP(
            {"bad.mp4": b"x", "good1.mp4": b"aaa", "good2.mp4": b"bbb"},
            size_fails=["bad.mp4"],
        )
    )

    assert local_names() == ["good1.mp4", "good2.mp4"]
    assert fake.retrieved == ["good1.mp4", "good2.mp4"]


def test_zero_byte_file_is_skipped_and_the_batch_continues(run_download, local_names):
    run_download(FakeFTP({"empty.mp4": b"", "later.mp4": b"ok"}))
    assert local_names() == ["later.mp4"]


def test_failed_login_stops_the_run_instead_of_reusing_a_dead_connection(
    run_download, local_names
):
    # Was: the connect failure only printed, so the unauthenticated client was
    # then used for the listing and the transfers.
    fake = run_download(FakeFTP({"x.mp4": b"xxxx"}, fail_on="login"))

    assert "nlst" not in fake.commands
    assert local_names() == []


def test_hostile_remote_names_cannot_write_outside_the_download_folder(
    run_download, local_names, tmp_path
):
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    victim = outside / "victim.mp4"
    victim.write_bytes(b"do not touch")

    run_download(FakeFTP({"../outside/victim.mp4": b"pwned", "ok.mp4": b"good"}))

    assert victim.read_bytes() == b"do not touch"
    # The traversal entry is kept, but reduced to a basename inside the folder.
    assert local_names() == ["ok.mp4", "victim.mp4"]


def test_control_character_names_are_skipped_without_killing_the_batch(
    run_download, local_names
):
    fake = run_download(FakeFTP({"a\r\nDELE x.mp4": b"bad", "fine.mp4": b"good"}))

    assert local_names() == ["fine.mp4"]
    assert not any(c.startswith("size:a\r\n") for c in fake.commands)


def test_a_stale_part_file_is_ignored_and_the_video_is_refetched(
    run_download, local_names, tmp_path
):
    # Downloads land atomically, so a transfer interrupted by docker stop leaves
    # a .part that must not be mistaken for a finished download.
    (tmp_path / "clip.mp4.part").write_bytes(b"TRUNCATED")

    fake = run_download(FakeFTP({"clip.mp4": b"the complete video"}))

    assert fake.retrieved == ["clip.mp4"]
    assert (tmp_path / "clip.mp4").read_bytes() == b"the complete video"
    assert local_names() == ["clip.mp4"]


def test_download_leaves_no_part_file_behind(run_download, local_names):
    run_download(FakeFTP({"clip.mp4": b"video"}))
    assert not any(n.endswith(".part") for n in local_names())


def test_a_file_already_downloaded_is_not_fetched_again(run_download, tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"already here")
    fake = run_download(FakeFTP({"clip.mp4": b"remote copy"}))

    assert fake.retrieved == []
    assert (tmp_path / "clip.mp4").read_bytes() == b"already here"


def test_happy_path_downloads_then_deletes_the_remote_copy(run_download, local_names):
    fake = run_download(FakeFTP({"new.mp4": b"video-bytes"}), delete_files=True)

    assert local_names() == ["new.mp4"]
    assert fake.deleted == ["new.mp4"]


def test_delete_files_off_leaves_the_printer_copy_alone(run_download):
    fake = run_download(FakeFTP({"new.mp4": b"video-bytes"}), delete_files=False)
    assert fake.deleted == []


def test_the_connection_is_always_closed(run_download):
    fake = run_download(FakeFTP({"a.mp4": b"x"}))
    assert fake.closed


def test_the_connection_is_closed_even_when_the_listing_fails(run_download):
    fake = run_download(FakeFTP({"a.mp4": b"x"}, fail_on="nlst"))
    assert fake.closed


def test_missing_remote_folder_is_reported_without_downloading(
    run_download, local_names
):
    fake = FakeFTP({"a.mp4": b"x"}, remote_folder="timelapse")
    fake.root_listing = ["some-other-folder"]
    run_download(fake)

    assert fake.retrieved == []
    assert local_names() == []
