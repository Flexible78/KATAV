"""
Non-GUI unit tests for the URL/YouTube pipeline.
Run: python test_url_pipeline.py

Note: this file uses the standard unittest framework (instead of the custom
harness in test_queue.py) so we can leverage unittest.mock for subprocess and
yt-dlp mocking.
"""
import sys
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import canonical_media_url
from whisper_core import (
    _get_playlist_entries, _download_url_to_queue,
    _is_radio_playlist,
)
from google_drive import _is_google_drive_url, _extract_drive_file_id
import whisper_core
import utils


def _yt_dlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


class CanonicalMediaUrlTests(unittest.TestCase):
    """Tests for utils.canonical_media_url."""

    def test_youtube_watch_url(self):
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=share"
        self.assertEqual(canonical_media_url(url), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_youtube_short_url(self):
        url = "https://youtu.be/dQw4w9WgXcQ"
        self.assertEqual(canonical_media_url(url), "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_youtube_playlist_url_unchanged(self):
        url = "https://www.youtube.com/playlist?list=PL1234567890"
        self.assertEqual(canonical_media_url(url), url)

    def test_non_youtube_url_unchanged(self):
        url = "https://example.com/video?id=123"
        self.assertEqual(canonical_media_url(url), url)

    def test_non_string_input_returned_unchanged(self):
        self.assertEqual(canonical_media_url(None), None)
        self.assertEqual(canonical_media_url(123), 123)

    def test_malformed_url_returned_unchanged(self):
        url = "not a url"
        self.assertEqual(canonical_media_url(url), url)


@unittest.skipUnless(_yt_dlp_available(), "yt-dlp is not installed")
class PlaylistExpansionTests(unittest.TestCase):
    """Tests for whisper_core._get_playlist_entries with mocked yt-dlp."""

    @patch("yt_dlp.YoutubeDL")
    def test_playlist_expansion(self, mock_youtube_dl_class):
        mock_ydl = MagicMock()
        mock_youtube_dl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_youtube_dl_class.return_value.__exit__ = MagicMock(return_value=False)

        mock_ydl.extract_info.return_value = {
            "entries": [
                {"url": "https://youtube.com/watch?v=abc123", "title": "Video One"},
                {"webpage_url": "https://youtube.com/watch?v=def456", "title": "Video Two"},
                {"id": "ghi789", "title": "Video Three"},
            ]
        }

        entries = _get_playlist_entries("https://www.youtube.com/playlist?list=PLtest")

        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["url"], "https://youtube.com/watch?v=abc123")
        self.assertEqual(entries[0]["title"], "Video One")
        self.assertEqual(entries[1]["url"], "https://youtube.com/watch?v=def456")
        self.assertEqual(entries[2]["url"], "https://www.youtube.com/watch?v=ghi789")
        self.assertEqual(entries[2]["title"], "Video Three")

    @patch("yt_dlp.YoutubeDL")
    def test_empty_playlist(self, mock_youtube_dl_class):
        mock_ydl = MagicMock()
        mock_youtube_dl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_youtube_dl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": []}

        entries = _get_playlist_entries("https://www.youtube.com/playlist?list=PLempty")
        self.assertEqual(entries, [])

    @patch("yt_dlp.YoutubeDL")
    def test_playlist_extraction_failure(self, mock_youtube_dl_class):
        mock_youtube_dl_class.side_effect = Exception("network error")
        entries = _get_playlist_entries("https://www.youtube.com/playlist?list=PLfail")
        self.assertEqual(entries, [])


class FakeProcess:
    """Fake subprocess.Popen result for _download_url_to_queue tests."""

    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self._returncode = returncode
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        return self._returncode

    @property
    def returncode(self):
        return self._returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def _make_cache_file(cache_dir: str, video_id: str = "dQw4w9WgXcQ") -> str:
    path = os.path.join(cache_dir, f"{video_id}.mp3")
    with open(path, "w", encoding="utf-8") as f:
        f.write("fake audio")
    return path


class DownloadUrlToQueueTests(unittest.TestCase):
    """Tests for whisper_core._download_url_to_queue with mocked subprocess/yt-dlp."""

    def setUp(self):
        self.original_stop_requested = utils.stop_requested
        utils.stop_requested = False
        utils.current_process = None

    def tearDown(self):
        utils.stop_requested = self.original_stop_requested
        utils.current_process = None

    @patch("whisper_core._url_cache_dir")
    @patch("whisper_core.os.path.isfile")
    @patch("whisper_core._get_url_title")
    @patch("whisper_core._copy_to_output")
    @patch("whisper_core._get_file_duration")
    @patch("whisper_core.batch_queue")
    def test_cache_hit_returns_cached_path(
        self,
        mock_batch_queue,
        mock_get_file_duration,
        mock_copy_to_output,
        mock_get_url_title,
        mock_isfile,
        mock_url_cache_dir,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = _make_cache_file(tmpdir)
            output_path = os.path.join(tmpdir, "output", "Video Title.mp3")

            mock_url_cache_dir.return_value = tmpdir
            mock_isfile.side_effect = lambda p: p == cache_path
            mock_get_url_title.return_value = "Video Title"
            mock_copy_to_output.return_value = output_path
            mock_get_file_duration.return_value = 123.45

            files_to_process = []
            result = _download_url_to_queue(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                os.path.join(tmpdir, "output"),
                files_to_process,
                item_idx=1,
            )

            self.assertEqual(result, output_path)
            self.assertIn(output_path, files_to_process)
            mock_batch_queue.update_url_to_local.assert_called_once_with(
                1, output_path, name="Video Title", duration=123.45
            )

    @patch("whisper_core.subprocess.Popen")
    @patch("whisper_core._url_cache_dir")
    @patch("whisper_core.os.path.isfile")
    @patch("whisper_core._get_url_title")
    @patch("whisper_core._copy_to_output")
    @patch("whisper_core._get_file_duration")
    @patch("whisper_core.batch_queue")
    def test_successful_download(
        self,
        mock_batch_queue,
        mock_get_file_duration,
        mock_copy_to_output,
        mock_get_url_title,
        mock_isfile,
        mock_url_cache_dir,
        mock_popen,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "_url_cache")
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(cache_dir)
            # Use a path that is NOT the expected cache path so we exercise the
            # subprocess download branch rather than the cache-hit branch.
            printed_file = os.path.join(cache_dir, "yt-dlp-downloaded.mp3")
            with open(printed_file, "w", encoding="utf-8") as f:
                f.write("fake audio")
            output_file = os.path.join(output_dir, "Video Title.mp3")

            mock_url_cache_dir.return_value = cache_dir
            mock_isfile.side_effect = lambda p: p == printed_file
            mock_popen.return_value = FakeProcess([f"{printed_file}\n"], returncode=0)
            mock_get_url_title.return_value = "Video Title"
            mock_copy_to_output.return_value = output_file
            mock_get_file_duration.return_value = 123.45

            files_to_process = []
            result = _download_url_to_queue(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir,
                files_to_process,
                item_idx=1,
            )

            self.assertEqual(result, output_file)
            self.assertIn(output_file, files_to_process)
            mock_popen.assert_called_once()
            mock_batch_queue.update_url_to_local.assert_called_once_with(
                1, output_file, name="Video Title", duration=123.45
            )

    @patch("whisper_core.subprocess.Popen")
    @patch("whisper_core._url_cache_dir")
    @patch("whisper_core.os.path.isfile")
    @patch("whisper_core._get_url_title")
    @patch("whisper_core._copy_to_output")
    @patch("whisper_core.batch_queue")
    def test_failed_download_returns_empty_string(
        self,
        mock_batch_queue,
        mock_copy_to_output,
        mock_get_url_title,
        mock_isfile,
        mock_url_cache_dir,
        mock_popen,
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = os.path.join(tmpdir, "_url_cache")
            output_dir = os.path.join(tmpdir, "output")
            os.makedirs(cache_dir)
            downloaded_file = os.path.join(cache_dir, "dQw4w9WgXcQ.mp3")

            mock_url_cache_dir.return_value = cache_dir
            mock_isfile.return_value = False
            mock_popen.return_value = FakeProcess([f"{downloaded_file}\n"], returncode=1)

            files_to_process = []
            result = _download_url_to_queue(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                output_dir,
                files_to_process,
                item_idx=1,
            )

            self.assertEqual(result, "")
            self.assertEqual(files_to_process, [])
            mock_batch_queue.update_url_to_local.assert_not_called()

    @patch("whisper_core.subprocess.Popen")
    @patch("whisper_core._url_cache_dir")
    @patch("whisper_core.os.path.isfile")
    def test_user_cancel(self, mock_isfile, mock_url_cache_dir, mock_popen):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_process = FakeProcess(["downloading...\n"])
            mock_popen.return_value = fake_process
            mock_url_cache_dir.return_value = tmpdir
            mock_isfile.return_value = False
            utils.stop_requested = True

            files_to_process = []
            result = _download_url_to_queue(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "/tmp/output",
                files_to_process,
            )

            self.assertEqual(result, "")
            self.assertTrue(fake_process.terminated or fake_process.killed)


class PlaylistExpansionPolicyTests(unittest.TestCase):
    """Tests for BC5 playlist expansion policies (RD/UL rejection, cap, dedup)."""

    @patch("whisper_core._get_playlist_entries")
    def test_radio_playlist_rejected(self, mock_get_entries):
        self.assertTrue(_is_radio_playlist("https://www.youtube.com/playlist?list=RDabc123"))
        self.assertTrue(_is_radio_playlist("https://www.youtube.com/playlist?list=ULxyz789"))
        self.assertFalse(_is_radio_playlist("https://www.youtube.com/playlist?list=PLabc123"))

    @patch("whisper_core._get_playlist_entries")
    def test_playlist_deduplicates_and_caps(self, mock_get_entries):
        mock_get_entries.return_value = [
            {"id": "abc", "url": "https://www.youtube.com/watch?v=abc", "title": "One"},
            {"id": "abc", "url": "https://www.youtube.com/watch?v=abc", "title": "One again"},
            {"id": "def", "url": "https://www.youtube.com/watch?v=def", "title": "Two"},
        ]
        entries = whisper_core.expand_playlist("https://www.youtube.com/playlist?list=PLtest")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["id"], "abc")
        self.assertEqual(entries[1]["id"], "def")
        self.assertEqual(entries[0]["playlist_index"], 1)
        self.assertEqual(entries[1]["playlist_index"], 2)
        self.assertEqual(entries[0]["url"], "https://www.youtube.com/watch?v=abc")

    @patch("whisper_core._get_playlist_entries")
    def test_playlist_fifty_item_cap(self, mock_get_entries):
        many = [{"id": f"vid{i:03d}", "url": f"https://www.youtube.com/watch?v=vid{i:03d}", "title": f"Video {i}"} for i in range(1, 55)]
        mock_get_entries.return_value = many
        entries = whisper_core.expand_playlist("https://www.youtube.com/playlist?list=PLbig")
        self.assertEqual(len(entries), 50)


class GoogleDriveTests(unittest.TestCase):
    """Tests for BC8 Google Drive link handling."""

    def test_recognises_drive_links(self):
        self.assertTrue(_is_google_drive_url("https://drive.google.com/file/d/ABC123/view"))
        self.assertTrue(_is_google_drive_url("https://drive.google.com/file/d/ABC123"))
        self.assertTrue(_is_google_drive_url("https://drive.google.com/open?id=XYZ789"))
        self.assertFalse(_is_google_drive_url("https://www.youtube.com/watch?v=abc"))

    def test_extracts_file_id(self):
        self.assertEqual(_extract_drive_file_id("https://drive.google.com/file/d/ABC123/view"), "ABC123")
        self.assertEqual(_extract_drive_file_id("https://drive.google.com/open?id=XYZ789"), "XYZ789")
        self.assertEqual(_extract_drive_file_id("https://example.com/file"), "")


class BatchResultsTests(unittest.TestCase):
    """Tests for BC6 JOIN and ZIP helpers."""

    @patch("batch_results.batch_queue")
    def test_join_creates_files(self, mock_queue):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            src1 = os.path.join(tmpdir, "video1_TRANSLATED_EN.txt")
            src2 = os.path.join(tmpdir, "video2_TRANSLATED_EN.txt")
            with open(src1, "w", encoding="utf-8") as f:
                f.write("Hello world")
            with open(src2, "w", encoding="utf-8") as f:
                f.write("Goodbye world")
            mock_queue.get_batch_results.return_value = [
                {"idx": 1, "name": "video1", "playlist_index": 1, "produced_files": [src1]},
                {"idx": 2, "name": "video2", "playlist_index": 2, "produced_files": [src2]},
            ]
            from batch_results import join_batch_results
            paths = join_batch_results(tmpdir, plain_text=False)
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].endswith("batch_JOINED_EN.txt"))
            with open(paths[0], "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("## 001 — video1", content)
            self.assertIn("Hello world", content)
            self.assertIn("## 002 — video2", content)
            self.assertIn("Goodbye world", content)

    @patch("batch_results.batch_queue")
    def test_zip_creates_archive(self, mock_queue):
        import tempfile
        from batch_results import zip_batch_results
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "result.txt")
            with open(src, "w", encoding="utf-8") as f:
                f.write("batch result")
            mock_queue.get_batch_results.return_value = [
                {"idx": 1, "name": "item", "playlist_index": None, "produced_files": [src]},
            ]
            zip_path = zip_batch_results(tmpdir)
            self.assertTrue(os.path.isfile(zip_path))
            import zipfile
            with zipfile.ZipFile(zip_path, "r") as zf:
                self.assertIn("result.txt", zf.namelist())


if __name__ == "__main__":
    unittest.main(verbosity=2)
