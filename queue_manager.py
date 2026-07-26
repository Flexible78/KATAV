"""
queue_manager.py — Central batch queue management for KATAV.
Handles: queue items (files + URLs), duration extraction, ETA calculation,
settings snapshots, and safe shutdown scheduling.
"""

import os
import re
import time
import json
import logging
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from config import DEFAULT_OUTPUT_DIR
import utils

log = logging.getLogger("queue_manager")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class QueueItem:
    """A single item in the batch queue — file or URL."""
    idx: int                          # insertion order (1-based)
    source: str                       # 'file' or 'url'
    name: str                         # display name (filename or short URL)
    path_or_url: str                  # full filesystem path or URL
    status: str = "queued"            # queued | running | done | failed | skipped
    duration: float = -1.0            # media seconds; -1 = unknown
    error: str = ""                   # error message if failed
    metadata: Dict[str, Any] = field(default_factory=dict)  # extra metadata
    started_at: float = 0.0           # wall-clock when processing started
    finished_at: float = 0.0          # wall-clock when processing finished
    processed_seconds: float = 0.0    # how many media seconds *actually* processed
    produced_files: List[str] = field(default_factory=list)  # output files produced for this item


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------
FFPROBE_TIMEOUT = 5  # seconds


def _get_file_duration(filepath: str) -> float:
    """Return media duration in seconds via ffprobe, or -1 on failure."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath,
            ],
            capture_output=True, text=True, timeout=FFPROBE_TIMEOUT,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        elif result.returncode != 0:
            stderr_tail = result.stderr.strip().split('\n')[-3:] if result.stderr else []
            log.warning(
                "ffprobe exited %d for %r: cmd=%r | stderr=%s",
                result.returncode, filepath,
                "ffprobe -v error -show_entries format=duration ...",
                " | ".join(stderr_tail) if stderr_tail else "<none>",
            )
    except FileNotFoundError:
        log.warning("ffprobe not found — install ffmpeg to get media durations")
    except Exception as e:
        log.debug("ffprobe failed for %r: %s", filepath, e)
    return -1.0


def _get_url_duration(url: str) -> float:
    """Attempt to get duration for a URL via yt-dlp (download=False). Returns -1 on failure."""
    try:
        import yt_dlp
        url = utils.canonical_media_url(url)
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 10,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            dur = info.get("duration")
            if dur is not None:
                return float(dur)
    except Exception:
        pass
    return -1.0


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS."""
    if seconds < 0:
        return "??:??"
    seconds = int(seconds)
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    else:
        m = seconds // 60
        s = seconds % 60
        return f"{m:02d}:{s:02d}"


def format_seconds_safe(seconds: float) -> str:
    """Format seconds, returning 'Calculating…' for negative values."""
    if seconds < 0:
        return "Calculating…"
    return format_duration(seconds)


# ---------------------------------------------------------------------------
# QueueManager
# ---------------------------------------------------------------------------
class QueueManager:
    """Singleton-style manager for the batch processing queue."""

    def __init__(self):
        self._items: List[QueueItem] = []
        self._next_idx: int = 1
        self._total_media_seconds: float = 0.0  # sum of known durations
        self._started: bool = False
        self._cancelled: bool = False
        self._lock = threading.Lock()

        # ETA tracking
        self._cumulative_media_seconds: float = 0.0   # total media secs completed
        self._cumulative_wall_seconds: float = 0.0     # total wall secs spent
        self._batch_start_time: float = 0.0
        self._current_file_media_remaining: float = 0.0
        self._current_file_start_wall: float = 0.0
        self._current_file_processed_media: float = 0.0

        # Shutdown state
        self._shutdown_requested: bool = False
        self._shutdown_scheduled: bool = False
        self._shutdown_countdown: int = 0
        self._shutdown_message: str = ""
        self._shutdown_cancelled: bool = False

        # Settings snapshots — keyed by item idx
        self._settings_snapshots: Dict[int, Dict[str, Any]] = {}

        # Notification callback for UI
        self._pending_notice: str = ""

        # Background duration probing
        self._executor: Optional[ThreadPoolExecutor] = None
        self._executor_shutdown: bool = False
        self._pending_futures: List[Any] = []
        self._probe_start_time: float = 0.0

    # ------------------------------------------------------------------
    # Queue building
    # ------------------------------------------------------------------
    def _get_executor(self) -> ThreadPoolExecutor:
        if self._executor is None or self._executor_shutdown:
            self._executor = ThreadPoolExecutor(max_workers=4)
            self._executor_shutdown = False
        return self._executor

    def reset(self):
        """Clear the entire queue and reset state for a fresh batch."""
        with self._lock:
            # Cancel any pending futures
            for fut in self._pending_futures:
                try:
                    fut.cancel()
                except Exception:
                    pass
            self._pending_futures.clear()
            if self._executor and not self._executor_shutdown:
                try:
                    self._executor.shutdown(wait=False)
                    self._executor_shutdown = True
                except Exception:
                    pass
                self._executor = None
            self._items.clear()
            self._next_idx = 1
            self._total_media_seconds = 0.0
            self._started = False
            self._cancelled = False
            self._cumulative_media_seconds = 0.0
            self._cumulative_wall_seconds = 0.0
            self._batch_start_time = 0.0
            self._current_file_media_remaining = 0.0
            self._current_file_start_wall = 0.0
            self._current_file_processed_media = 0.0
            self._shutdown_requested = False
            self._shutdown_scheduled = False
            self._shutdown_countdown = 0
            self._shutdown_message = ""
            self._shutdown_cancelled = False
            self._settings_snapshots.clear()
            self._pending_notice = ""
            self._probe_start_time = 0.0

    def _log_stage(self, message: str):
        """Emit a timestamped [STAGE] line to the live log."""
        elapsed = time.time() - self._probe_start_time if self._probe_start_time > 0 else 0.0
        line = f"[STAGE] {message} (elapsed: {elapsed:.1f}s)"
        try:
            utils.log_queue.put(line + "\n")
        except Exception:
            pass

    def _notify_queue_ready(self):
        """Called when all pending duration probes are done."""
        if not self._pending_futures:
            return
        try:
            total = len(self._items)
            known = sum(1 for it in self._items if it.duration > 0)
            elapsed = time.time() - self._probe_start_time if self._probe_start_time > 0 else 0.0
            line = f"[STAGE] Queue ready: {total} item(s), {known} duration(s) known in {elapsed:.1f}s"
            utils.log_queue.put(line + "\n")
        except Exception:
            pass

    def add_file(self, filepath: str) -> Optional[QueueItem]:
        """Add a local file to the queue. Returns the item or None if duplicate."""
        filepath = os.path.abspath(filepath)
        with self._lock:
            # Dedup
            for it in self._items:
                if it.source == "file" and it.path_or_url == filepath:
                    return None
            item = QueueItem(
                idx=self._next_idx,
                source="file",
                name=os.path.basename(filepath),
                path_or_url=filepath,
                duration=-1.0,
            )
            self._items.append(item)
            self._next_idx += 1
        # Probe duration in background (never blocks addition)
        def _probe():
            dur = _get_file_duration(filepath)
            if dur > 0:
                with self._lock:
                    item.duration = dur
                    item.metadata["duration_known"] = True
                    self._total_media_seconds += dur
        future = self._get_executor().submit(_probe)
        self._pending_futures.append(future)
        return item

    def add_url(self, url: str) -> Optional[QueueItem]:
        """Add a URL to the queue. Returns the item or None if duplicate/invalid."""
        url = url.strip()
        if not url:
            return None
        canonical = utils.canonical_media_url(url)
        # Normalize: remove trailing slash (harmless)
        url_norm = canonical.rstrip("/")
        with self._lock:
            for it in self._items:
                if it.source == "url" and it.path_or_url.rstrip("/") == url_norm:
                    return None
            # Validate URL
            if not re.match(r"^https?://", canonical):
                return None  # caller should show error
            short_name = canonical
            if len(short_name) > 50:
                short_name = short_name[:47] + "..."
            item = QueueItem(
                idx=self._next_idx,
                source="url",
                name=short_name,
                path_or_url=canonical,
                duration=-1.0,
                metadata={"full_url": url, "duration_known": False},
            )
            self._items.append(item)
            self._next_idx += 1
        # Resolve duration in background; never block on this.
        def _probe():
            dur = _get_url_duration(canonical)
            if dur > 0:
                with self._lock:
                    item.duration = dur
                    item.metadata["duration_known"] = True
                    self._total_media_seconds += dur
        future = self._get_executor().submit(_probe)
        self._pending_futures.append(future)
        return item

    def start_duration_probing(self):
        """Record the start time of duration probing and emit a stage line."""
        self._probe_start_time = time.time()
        total = self.get_total_items()
        self._log_stage(f"Reading durations for {total} item(s)...")
        # Schedule a watcher that logs "Queue ready" when all pending futures are done.
        def _watcher():
            try:
                for fut in list(self._pending_futures):
                    try:
                        fut.result(timeout=30)
                    except Exception:
                        pass
                self._notify_queue_ready()
            except Exception:
                pass
        threading.Thread(target=_watcher, daemon=True).start()

    def remove_item(self, idx: int) -> bool:
        """Remove an item by its 1-based idx. Returns True if removed."""
        with self._lock:
            for i, it in enumerate(self._items):
                if it.idx == idx:
                    if it.status == "running":
                        return False  # cannot remove running
                    if it.duration > 0:
                        self._total_media_seconds = max(0, self._total_media_seconds - it.duration)
                    del self._items[i]
                    return True
        return False

    def clear_queue(self):
        """Remove all non-running items."""
        with self._lock:
            self._items = [it for it in self._items if it.status == "running"]
            self._recalc_total_duration()

    def _recalc_total_duration(self):
        self._total_media_seconds = sum(it.duration for it in self._items if it.duration > 0)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def get_items(self) -> List[QueueItem]:
        with self._lock:
            return list(self._items)

    def get_total_items(self) -> int:
        with self._lock:
            return len(self._items)

    def get_item(self, idx: int) -> Optional[QueueItem]:
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    return it
        return None

    def get_total_media_seconds(self) -> float:
        with self._lock:
            return self._total_media_seconds

    def get_completed_count(self) -> int:
        with self._lock:
            return sum(1 for it in self._items if it.status == "done")

    def get_failed_count(self) -> int:
        with self._lock:
            return sum(1 for it in self._items if it.status == "failed")

    def get_running_item(self) -> Optional[QueueItem]:
        with self._lock:
            for it in self._items:
                if it.status == "running":
                    return it
        return None

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    # ------------------------------------------------------------------
    # Processing hooks (called from whisper_core)
    # ------------------------------------------------------------------
    def mark_started(self):
        with self._lock:
            self._started = True
            self._batch_start_time = time.time()

    def mark_item_running(self, idx: int):
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    it.status = "running"
                    it.started_at = time.time()
                    self._current_file_start_wall = it.started_at
                    self._current_file_processed_media = 0.0
                    if it.duration > 0:
                        self._current_file_media_remaining = it.duration
                    else:
                        self._current_file_media_remaining = 0.0
                    break

    def mark_item_done(self, idx: int):
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    it.status = "done"
                    it.finished_at = time.time()
                    wall = it.finished_at - it.started_at if it.started_at > 0 else 0
                    self._cumulative_wall_seconds += wall
                    if it.duration > 0:
                        self._cumulative_media_seconds += it.duration
                        it.processed_seconds = it.duration
                    break

    def mark_item_failed(self, idx: int, error: str = ""):
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    it.status = "failed"
                    it.error = error
                    it.finished_at = time.time()
                    break

    def mark_item_skipped(self, idx: int, reason: str = ""):
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    it.status = "skipped"
                    it.error = reason
                    break

    def get_skipped_count(self) -> int:
        with self._lock:
            return sum(1 for it in self._items if it.status == "skipped")

    def retry_failed(self) -> int:
        """Reset failed items back to queued. Returns count."""
        with self._lock:
            count = 0
            for it in self._items:
                if it.status == "failed":
                    it.status = "queued"
                    it.error = ""
                    count += 1
            return count

    def update_item_progress(self, idx: int, percent: float):
        """Update running item's processed_seconds based on progress percent."""
        with self._lock:
            for it in self._items:
                if it.idx == idx and it.status == "running":
                    if it.duration > 0:
                        it.processed_seconds = it.duration * (percent / 100.0)

    def update_current_file_eta(self, remaining_seconds: float):
        """Update the current running file's remaining seconds from Whisper progress."""
        with self._lock:
            self._current_file_media_remaining = max(0.0, float(remaining_seconds or 0.0))

    def update_url_duration(self, idx: int, duration: float):
        """Update a URL item's duration after metadata is resolved."""
        with self._lock:
            for it in self._items:
                if it.idx == idx and it.duration <= 0:
                    it.duration = duration
                    it.metadata["duration_known"] = True
                    self._total_media_seconds += duration
                    break

    def update_url_to_local(self, idx: int, local_path: str, duration: float = -1.0, name: str = ""):
        """Replace a URL item's working path with a local audio file path."""
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    # Preserve the original URL before overwriting
                    if "full_url" not in it.metadata:
                        it.metadata["full_url"] = it.path_or_url
                    it.path_or_url = local_path
                    if duration > 0:
                        it.duration = duration
                    if name:
                        it.name = name
                    break

    def set_detected_language(self, idx: int, lang: str):
        """Store the detected source language for a queue item."""
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    it.metadata["detected_language"] = lang
                    break

    def add_produced_file(self, idx: int, path: str):
        """Record a produced output file path for a queue item."""
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    if path and path not in it.produced_files:
                        it.produced_files.append(path)
                    break

    def get_batch_results(self) -> List[Dict[str, Any]]:
        """Return a list of {idx, name, playlist_index, produced_files} for all items."""
        with self._lock:
            return [
                {
                    "idx": it.idx,
                    "name": it.name,
                    "playlist_index": it.metadata.get("playlist_index"),
                    "produced_files": list(it.produced_files),
                }
                for it in self._items
            ]

    def get_detected_language(self, idx: int) -> str:
        """Return the detected source language for a queue item, or empty string."""
        with self._lock:
            for it in self._items:
                if it.idx == idx:
                    return it.metadata.get("detected_language", "")
        return ""

    def find_item_by_path(self, path: str) -> Optional[QueueItem]:
        """Find a queue item by its current local path."""
        norm = os.path.normcase(os.path.abspath(path))
        with self._lock:
            for it in self._items:
                if os.path.normcase(os.path.abspath(it.path_or_url)) == norm:
                    return it
        return None

    def replace_item_with_playlist_entries(self, idx: int, entries: List[Dict[str, Any]]) -> List[int]:
        """Replace a playlist queue item with individual video items, preserving order."""
        with self._lock:
            for i, it in enumerate(list(self._items)):
                if it.idx == idx:
                    self._items.pop(i)
                    new_items = []
                    insert_pos = i
                    seen_ids = set()
                    for entry in entries:
                        entry_url = entry.get("url", "")
                        entry_id = entry.get("id") or entry_url
                        # Skip duplicates within the playlist itself
                        if entry_id in seen_ids:
                            continue
                        seen_ids.add(entry_id)
                        entry_title = entry.get("title", "") or entry_url
                        canonical = utils.canonical_media_url(entry_url)
                        # Prefix name with playlist order for course-like batches
                        playlist_index = entry.get("playlist_index")
                        if playlist_index is not None:
                            display_name = f"{playlist_index:03d}_{entry_title}"[:80]
                        else:
                            display_name = entry_title[:80]
                        metadata = {
                            "full_url": entry_url,
                            "duration_known": False,
                            "playlist_index": playlist_index,
                            "playlist_title": entry.get("playlist_title", ""),
                        }
                        item = QueueItem(
                            idx=self._next_idx,
                            source="url",
                            name=display_name,
                            path_or_url=canonical,
                            duration=-1.0,
                            metadata=metadata,
                        )
                        self._items.insert(insert_pos, item)
                        new_items.append(item)
                        self._next_idx += 1
                        insert_pos += 1
                    return [it.idx for it in new_items]
            return []

    def set_cancelled(self):
        with self._lock:
            self._cancelled = True

    # ------------------------------------------------------------------
    # Settings snapshot
    # ------------------------------------------------------------------
    def set_settings_snapshot(self, idx: int, settings: Dict[str, Any]):
        with self._lock:
            self._settings_snapshots[idx] = dict(settings)

    def get_settings_snapshot(self, idx: int) -> Dict[str, Any]:
        with self._lock:
            return self._settings_snapshots.get(idx, {})

    def set_pending_notice(self, notice: str):
        with self._lock:
            self._pending_notice = notice

    def get_pending_notice(self) -> str:
        with self._lock:
            n = self._pending_notice
            self._pending_notice = ""
            return n

    # ------------------------------------------------------------------
    # ETA calculation
    # ------------------------------------------------------------------
    def calculate_eta(self) -> float:
        """
        Calculate estimated seconds remaining for the batch.
        Uses measured processing speed from real completed work and the
        remaining time reported by Whisper for the current file.
        Returns -1 if not enough data.
        """
        with self._lock:
            running = None
            for it in self._items:
                if it.status == "running":
                    running = it
                    break

            # Build measured speed from completed items first.
            speed = 0.0
            if self._cumulative_wall_seconds > 0:
                speed = self._cumulative_media_seconds / self._cumulative_wall_seconds

            # Factor in current file progress for a live speed estimate.
            current_speed = 0.0
            if running and running.started_at > 0:
                wall_now = time.time() - running.started_at
                if wall_now >= 3 and running.processed_seconds > 0:
                    current_speed = running.processed_seconds / wall_now

            effective_speed = current_speed if current_speed > 0 else speed
            if effective_speed <= 0:
                return -1.0

            # Remaining media seconds: current file remainder from Whisper + queued durations.
            remaining_media = 0.0
            if running and running.duration > 0:
                remaining_media += max(0.0, running.duration - running.processed_seconds)
            elif running:
                # Fallback if duration unknown: use Whisper's own remaining estimate.
                remaining_media += self._current_file_media_remaining

            for it in self._items:
                if it.status == "queued" and it.duration > 0:
                    remaining_media += it.duration

            if remaining_media <= 0:
                return 0.0

            return remaining_media / effective_speed

    def get_elapsed_str(self) -> str:
        with self._lock:
            if self._batch_start_time <= 0:
                return "00:00"
            elapsed = time.time() - self._batch_start_time
            return format_duration(elapsed)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def enable_shutdown(self):
        with self._lock:
            self._shutdown_requested = True

    def disable_shutdown(self):
        with self._lock:
            self._shutdown_requested = False
            self._shutdown_scheduled = False
            self._shutdown_cancelled = True

    def is_shutdown_enabled(self) -> bool:
        with self._lock:
            return self._shutdown_requested

    def check_and_schedule_shutdown(self) -> str:
        """
        Check if shutdown should be triggered. Returns a message string.
        Called after batch processing completes.
        """
        with self._lock:
            if not self._shutdown_requested:
                return ""

            if self._shutdown_cancelled:
                return "Shutdown cancelled."

            # Must have at least one success
            done = sum(1 for it in self._items if it.status == "done")
            if done == 0:
                self._shutdown_requested = False
                return "⚠️ No items succeeded — shutdown skipped."

            # Must not be cancelled
            if self._cancelled:
                self._shutdown_requested = False
                return "⚠️ Batch was cancelled — shutdown skipped."

            # Schedule shutdown
            try:
                result = subprocess.run(
                    ["shutdown", "/s", "/t", "60"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=0x08000000 if os.name == "nt" else 0,
                )
                if result.returncode != 0:
                    self._shutdown_message = f"Shutdown scheduling failed: {result.stderr.strip()}"
                    log.error(self._shutdown_message)
                    return self._shutdown_message
                self._shutdown_scheduled = True
                self._shutdown_message = "Batch complete. Windows will shut down in 60 seconds."
                return self._shutdown_message
            except Exception as e:
                self._shutdown_message = f"Shutdown scheduling failed: {e}"
                log.error(self._shutdown_message)
                return self._shutdown_message

    def cancel_shutdown(self) -> str:
        """Cancel pending shutdown. Returns status message."""
        with self._lock:
            try:
                subprocess.run(
                    ["shutdown", "/a"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=0x08000000 if os.name == "nt" else 0,
                )
                self._shutdown_scheduled = False
                self._shutdown_cancelled = True
                return "Shutdown cancelled."
            except Exception as e:
                return f"Failed to cancel shutdown: {e}"

    def get_shutdown_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "requested": self._shutdown_requested,
                "scheduled": self._shutdown_scheduled,
                "message": self._shutdown_message,
                "cancelled": self._shutdown_cancelled,
            }

    def is_shutdown_scheduled(self) -> bool:
        with self._lock:
            return self._shutdown_scheduled


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
batch_queue = QueueManager()
