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
from whisper_core import _get_playlist_entries, _download_url_to_queue
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

    @patch("yt_dlp.YoutubeDL")
    def test_cookie_browser_forwarded(self, mock_youtube_dl_class):
        mock_ydl = MagicMock()
        mock_youtube_dl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl)
        mock_youtube_dl_class.return_value.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = {"entries": []}

        _get_playlist_entries("https://www.youtube.com/playlist?list=PLcookies", cookie_browser="chrome")

        mock_youtube_dl_class.assert_called_once()
        call_args = mock_youtube_dl_class.call_args
        opts = call_args.kwargs if call_args.kwargs else call_args[0][0]
        self.assertIn("cookiesfrombrowser", opts)
        self.assertEqual(opts["cookiesfrombrowser"], ("chrome",))


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
                "None",
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
                "None",
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
                "None",
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
                "None",
                files_to_process,
            )

            self.assertEqual(result, "")
            self.assertTrue(fake_process.terminated or fake_process.killed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
