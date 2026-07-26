import os
import subprocess
import threading
import re
import time
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Any, Dict
import gradio as gr

import utils

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False

from config import WHISPER_EXE, WHISPER_EXE_HINT, DEFAULT_OUTPUT_DIR, WHISPER_PROCESS_PRIORITY, WHISPER_MAX_THREADS, WHISPER_COOLDOWN_SEC, WHISPER_GPU_POWER_LIMIT_W
from utils import (
    log_queue, log_to_terminal, interruptible_sleep, rescue_text_from_log,
    get_actual_output_dir, process_active, current_process, current_percent,
    time_elapsed, time_remaining, audio_speed, full_whisper_log, stop_requested,
    current_action, enqueue_output, clean_srt_text, _url_cache_dir
)
from ui_manager import ui_state
from queue_manager import batch_queue
from google_drive import is_google_drive_url, download_google_drive_file

def _gpu_power_limit_set(watts):
    """Best-effort: read current GPU power limit and set a new cap. Returns previous limit or None."""
    if not watts: return None
    try:
        prev = subprocess.run(
            ["nvidia-smi", "--query-gpu=power.default_limit", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10
        ).stdout.strip()
        subprocess.run(["nvidia-smi", "-pl", str(watts)], capture_output=True, text=True, timeout=10)
        log_queue.put(f"🔌 GPU power limit set to {watts}W (was {prev}W)\n")
        return prev
    except Exception as e:
        log_queue.put(f"⚠️ GPU power limit unavailable: {e}\n")
        return None

def _gpu_power_limit_restore(prev):
    """Best-effort: restore previous GPU power limit."""
    if not prev: return
    try:
        subprocess.run(["nvidia-smi", "-pl", str(prev)], capture_output=True, text=True, timeout=10)
    except Exception:
        pass


def _sanitize_filename(text: str) -> str:
    """Sanitise a string so it can be used as a file name."""
    if not text:
        return "media"
    text = re.sub(r"[<>:\"/\\\\|?*]", "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._")
    return text or "media"


def _get_url_title(url: str) -> str:
    """Best-effort metadata fetch for the video title."""
    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 10,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return (info or {}).get("title", "") or ""
    except Exception:
        return ""


def _get_playlist_id(url: str) -> str:
    """Extract the list= parameter from a YouTube playlist URL."""
    try:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        if parsed.path in ("/playlist", "/playlist/"):
            return parse_qs(parsed.query).get("list", [""])[0]
    except Exception:
        pass
    return ""


def _get_playlist_entries(url: str) -> List[Dict[str, Any]]:
    """Return a list of {'id', 'url', 'title'} for each entry in a playlist."""
    try:
        import yt_dlp
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "socket_timeout": 10,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            entries = (info or {}).get("entries", []) or []
            result = []
            for entry in entries:
                if not entry:
                    continue
                entry_id = entry.get("id") or ""
                entry_url = entry.get("url") or entry.get("webpage_url")
                if not entry_url:
                    if entry_id:
                        entry_url = f"https://www.youtube.com/watch?v={entry_id}"
                    else:
                        continue
                result.append({
                    "id": entry_id,
                    "url": entry_url,
                    "title": entry.get("title", "") or entry_url,
                })
            return result
    except Exception as e:
        log_queue.put(f"❌ Failed to expand playlist {url}: {e}\n")
        return []


def _is_radio_playlist(url: str) -> bool:
    """Reject auto-generated YouTube playlists (Mix/Radio/UL, etc.)."""
    list_id = _get_playlist_id(url)
    return list_id.upper().startswith(("RD", "UL"))


def expand_playlist(url: str) -> List[Dict[str, Any]]:
    """
    Expand a YouTube playlist into a list of video entries.

    - Rejects auto-generated Mix/Radio lists (RD/UL prefixes).
    - Caps at 50 entries (adds first 50 and logs a warning).
    - Deduplicates by video id.
    - Attaches playlist_index and playlist_title to each entry.
    """
    entries = _get_playlist_entries(url)
    if not entries:
        return []

    seen_ids = set()
    deduped = []
    for entry in entries:
        if len(deduped) >= 50:
            log_queue.put(f"[PLAYLIST] {len(entries)} items found, first 50 added. Add the rest manually.\n")
            break
        vid = entry.get("id") or entry.get("url", "")
        if vid in seen_ids:
            continue
        seen_ids.add(vid)
        # Index after deduplication, so prefix numbers are contiguous
        entry["playlist_index"] = len(deduped) + 1
        entry["playlist_title"] = entry.get("title", "")
        # Ensure canonical URL without list= parameter
        if entry.get("id"):
            entry["url"] = f"https://www.youtube.com/watch?v={entry['id']}"
        deduped.append(entry)

    return deduped


def _is_playlist_url(url: str) -> bool:
    return "/playlist?" in url and "list=" in url


# ---------------------------------------------------------------------------
# Google Drive / Spotify helpers
# ---------------------------------------------------------------------------
def _is_spotify_url(url: str) -> bool:
    return "open.spotify.com" in url


# ---------------------------------------------------------------------------
# URL title / naming helpers
# ---------------------------------------------------------------------------
def _output_title_for_item(url: str, item_idx: int) -> str:
    """Return a display/file title, prefixing playlist items with 001_, 002_, etc."""
    # Prefer cached metadata/name to avoid redundant network calls, but only
    # accept real strings (defensive against mocks or malformed metadata).
    title = None
    if item_idx is not None:
        try:
            item = batch_queue.get_item(item_idx)
            if item:
                if isinstance(item.metadata, dict):
                    cached = item.metadata.get("playlist_title")
                    if isinstance(cached, str) and cached.strip():
                        title = cached
                if not title and isinstance(item.name, str) and item.name.strip():
                    title = item.name
        except Exception:
            pass
    if not title:                title = _get_url_title(url) or _extract_youtube_id(url) or "media"
    if item_idx is not None:
        try:
            item = batch_queue.get_item(item_idx)
            if item and isinstance(item.metadata, dict):
                playlist_idx = item.metadata.get("playlist_index")
                if isinstance(playlist_idx, int):
                    title = f"{playlist_idx:03d}_{title}"
        except Exception:
            pass
    return title


def _copy_to_output(source_path: str, output_dir: str, title: str) -> str:
    """Copy a cached/downloaded audio file to the normal output directory, named after the title."""
    os.makedirs(output_dir, exist_ok=True)
    safe = _sanitize_filename(title)
    dest = os.path.join(output_dir, f"{safe}.mp3")
    if os.path.abspath(source_path) == os.path.abspath(dest):
        return dest
    try:
        import shutil as _shutil
        _shutil.copy2(source_path, dest)
    except Exception as e:
        log_queue.put(f"⚠️ Could not copy audio to output dir: {e}\n")
        return source_path
    return dest


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
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return -1.0


def _extract_youtube_id(url: str) -> str:
    """Extract the v= / youtu.be id from a canonical YouTube URL."""
    try:
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(url)
        if parsed.path in ("/watch", "/watch/"):
            return parse_qs(parsed.query).get("v", [None])[0]
        if "youtu.be" in parsed.netloc:
            return parsed.path.strip("/").split("/")[0]
    except Exception:
        pass
    return ""


def _download_url_to_queue(
    url: str, output_dir: str,
    files_to_process: List[Any],
    item_idx: int = None,
) -> str:
    """Download a single URL via yt-dlp CLI (subprocess), stream output, and queue the result.

    Downloaded audio is cached in Outputs/_url_cache for reuse across runs and is
    intentionally not treated as temporary. Returns the path to the downloaded/cached
    audio file, or an empty string on failure.
    """
    original_url = url
    url = utils.canonical_media_url(url)
    if url != original_url:
        log_queue.put(f"[URL] Normalised: {original_url} -> {url}\n")
    log_queue.put(f"️ Downloading: {url}\n")

    cache_dir = _url_cache_dir()
    video_id = _extract_youtube_id(url)
    cached_path = os.path.join(cache_dir, f"{video_id}.mp3") if video_id else ""

    # Reuse cached audio if it already exists
    if cached_path and os.path.isfile(cached_path):
        size_mb = os.path.getsize(cached_path) / (1024 * 1024)
        log_queue.put(f"[URL] Cached audio reused: {video_id}.mp3\n")
        title = _output_title_for_item(url, item_idx)
        local_path = _copy_to_output(cached_path, output_dir, title)
        files_to_process.append(local_path)
        if item_idx is not None:
            duration = _get_file_duration(local_path)
            batch_queue.update_url_to_local(item_idx, local_path, name=title[:80], duration=duration)
        return local_path

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", "bestaudio/best",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", os.path.join(cache_dir, "%(id)s.%(ext)s"),
        "--print", "after_move:filepath",
        "--progress",
    ]
    cmd.append(url)

    printed_path = ""
    first_error_line = ""
    process = None
    try:
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        utils.current_process = process

        for raw_line in process.stdout:
            if utils.stop_requested:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                log_queue.put("🛑 Download cancelled by user.\n")
                break
            line = utils.strip_ansi(raw_line).strip()
            if line:
                log_queue.put(line + "\n")
                if line.endswith(".mp3") and os.path.isfile(line):
                    printed_path = line
                # Capture the first real error line for classification
                if not first_error_line and (
                    "ERROR:" in line or "error" in line.lower() or "sign in" in line.lower()
                ):
                    first_error_line = line

        if not utils.stop_requested:
            try:
                process.wait(timeout=10)
            except Exception:
                pass

            if process.returncode == 0 and printed_path and os.path.isfile(printed_path):
                size_mb = os.path.getsize(printed_path) / (1024 * 1024)
                log_queue.put(f"[URL] Audio ready: {printed_path} ({size_mb:.2f} MB)\n")
                title = _output_title_for_item(url, item_idx)
                local_path = _copy_to_output(printed_path, output_dir, title)
                files_to_process.append(local_path)
                if item_idx is not None:
                    duration = _get_file_duration(local_path)
                    batch_queue.update_url_to_local(item_idx, local_path, name=title[:80], duration=duration)
                    log_queue.put(f"[STAGE] URL item resolved to local audio, starting transcription: {title}\n")
                return local_path
            else:
                _log_url_error(url, video_id, first_error_line)
    except Exception as e:
        log_queue.put(f"❌ URL download error for {url}: {e}\n")
    finally:
        utils.current_process = None

    return ""


def _log_url_error(url: str, video_id: str, error_line: str):
    """Classify yt-dlp output and emit a single actionable log line."""
    err_lower = (error_line or "").lower()
    vid = video_id or os.path.basename(url) or url
    if "sign in" in err_lower or "signin" in err_lower:
        log_queue.put("[ERROR] YouTube requires sign-in for this video. Skipped.\n")
    elif "video unavailable" in err_lower or "private" in err_lower or "removed" in err_lower or "unavailable" in err_lower:
        log_queue.put(f"[ERROR] Video is unavailable or private: {vid}. Skipped.\n")
    else:
        msg = error_line.strip() if error_line else f"yt-dlp exited with code for URL: {url}"
        log_queue.put(f"[ERROR] Download failed for {vid}: {msg}\n")

def run_transcription(
    input_files: List[Any], manual_path: str, urls_input: str, initial_prompt: str, hotwords: str,
    vad_method: str, language: str, model_size: str, compute_type: str,
    temperature: float, rep_penalty: float, beam_size: float, patience: float,
    condition_on_prev: bool, no_speech_thresh: float, use_sentence: bool,
    use_print_progress: bool, use_vad_filter: bool, use_beep_off: bool,
    use_custom_output: bool, output_dir: str, output_formats: List[str], save_audio_track: bool,
    plain_text_output: bool = False
) -> Tuple[gr.update, gr.update, gr.update, str, str, str]:
    global process_active, current_process, current_percent, time_elapsed, time_remaining, audio_speed, full_whisper_log, stop_requested, current_action
    
    ui_state.save_settings({
        "whisper_manual_path": manual_path, "whisper_urls": urls_input, "whisper_use_custom_output": use_custom_output, "whisper_output_dir": output_dir,
        "whisper_language": language, "whisper_vad": vad_method, "whisper_model": model_size, "whisper_compute": compute_type,
        "whisper_prompt": initial_prompt, "whisper_hotwords": hotwords, "whisper_temp": temperature, "whisper_rep": rep_penalty,
        "whisper_beam": beam_size, "whisper_patience": patience, "whisper_cond": condition_on_prev, "whisper_nospeech": no_speech_thresh,
        "whisper_formats": output_formats, "whisper_sentence": use_sentence, "whisper_progress": use_print_progress,
        "whisper_vadfilter": use_vad_filter, "whisper_beep": use_beep_off,
        "whisper_save_audio_track": save_audio_track,
        "whisper_plain_text": plain_text_output
    })

    if process_active: return gr.update(value="⚠️ A process is already running!"), gr.update(), gr.update(), "", "", ""
        
    current_action = "Transcription"
    current_percent = 0; time_elapsed = "00:00"; time_remaining = "00:00"; audio_speed = "0.00x"
    stop_requested = False
    log_queue.put("⏳ Collecting media files...\n")
    
    files_to_process = []
    manual_path = (manual_path or "").strip()
    
    if manual_path:
        paths = [p.strip().strip('"').strip("'") for p in manual_path.split('|') if p.strip()]
        for p in paths:
            if os.path.isdir(p):
                # Бронебойный скан файлов вместо glob
                for f in os.listdir(p):
                    if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mp3', '.wav', '.m4a', '.flac', '.ogg')):
                        files_to_process.append(os.path.join(p, f))
            elif os.path.isfile(p): files_to_process.append(p)
            
    if input_files:
        for f in input_files: files_to_process.append(f.name if hasattr(f, 'name') else str(f))

    global_out_dir = get_actual_output_dir(manual_path, use_custom_output, output_dir)
    if use_custom_output:
        os.makedirs(global_out_dir, exist_ok=True)
    urls_input = (urls_input or "").strip()
    if urls_input:
        urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
        # Map canonical URL to the corresponding queue item for metadata updates.
        url_item_map = {
            utils.canonical_media_url(it.path_or_url): it
            for it in batch_queue.get_items() if it.source == "url"
        }
        if urls:
            # Expand genuine /playlist URLs into individual video queue items first.
            expanded_urls = []
            for url in urls:
                if _is_playlist_url(url):
                    if _is_radio_playlist(url):
                        log_queue.put(f"[PLAYLIST] Auto-generated playlists (RD/UL) are not supported: {url}\n")
                        continue
                    entries = expand_playlist(url)
                    if entries:
                        log_queue.put(f"[INFO] Playlist detected: {len(entries)} items queued.\n")
                        item = url_item_map.get(utils.canonical_media_url(url))
                        if item is not None:
                            batch_queue.replace_item_with_playlist_entries(item.idx, entries)
                        expanded_urls.extend([e["url"] for e in entries])
                    continue
                expanded_urls.append(url)
            urls = expanded_urls

            # Rebuild the URL -> QueueItem map after expansion.
            url_item_map = {
                utils.canonical_media_url(it.path_or_url): it
                for it in batch_queue.get_items() if it.source == "url"
            }

            # Separate Google Drive links from streaming/media URLs.
            drive_urls = [u for u in urls if is_google_drive_url(u)]
            stream_urls = [u for u in urls if not is_google_drive_url(u) and not _is_spotify_url(u)]
            spotify_urls = [u for u in urls if _is_spotify_url(u)]
            for s_url in spotify_urls:
                log_queue.put("[SPOTIFY] DRM-protected, cannot be downloaded. For podcasts use the RSS link or the same episode on YouTube.\n")
                s_item = url_item_map.get(utils.canonical_media_url(s_url))
                if s_item is not None:
                    batch_queue.mark_item_failed(s_item.idx, "Spotify is DRM-protected and not supported")

            for url in drive_urls:
                if stop_requested:
                    break
                item = url_item_map.get(url)
                try:
                    local_path = download_google_drive_file(url, _url_cache_dir())
                    if local_path:
                        files_to_process.append(local_path)
                        if item is not None:
                            batch_queue.update_url_to_local(item.idx, local_path, name=os.path.basename(local_path)[:80])
                except Exception as dl_exc:
                    log_queue.put(f"[ERROR] Google Drive download failed and was skipped: {url} ({dl_exc})\n")
                    if item is not None:
                        batch_queue.mark_item_failed(item.idx, str(dl_exc))

            if not YT_DLP_AVAILABLE:
                log_queue.put("⚠️ ERROR: yt-dlp library is not installed! Run: pip install yt-dlp\n")
            else:
                log_queue.put(f"[STAGE] Downloading audio from {len(stream_urls)} URL(s) (yt-dlp)...\n")
                for url in stream_urls:
                    if stop_requested:
                        break
                    canonical_url = utils.canonical_media_url(url)
                    item = url_item_map.get(canonical_url)
                    try:
                        _download_url_to_queue(
                            url, global_out_dir,
                            files_to_process,
                            item_idx=item.idx if item else None
                        )
                    except Exception as dl_exc:
                        log_queue.put(f"[ERROR] URL download failed and was skipped: {url} ({dl_exc})\n")
                        if item is not None:
                            batch_queue.mark_item_failed(item.idx, str(dl_exc))
                    
    files_to_process = list(set(files_to_process))
    
    if not files_to_process:
        current_action = "Error"
        return gr.update(value="Error: No files found!"), gr.update(value=[]), gr.update(elem_classes=["status-error"]), "", "", ""
    
    process_active = True
    batch_queue.mark_started()
    current_queue_item = None

    def _find_queue_item(path: str):
        """Find the QueueItem whose current path matches the given local path."""
        norm = os.path.normcase(os.path.abspath(path))
        for qi in batch_queue.get_items():
            if os.path.normcase(os.path.abspath(qi.path_or_url)) == norm:
                return qi
        return None

    def _read_whisper_output_and_track(process, item_idx: int):
        """Stream Whisper stdout, forward to log queue, and update item progress."""
        try:
            for raw_line in process.stdout:
                line = utils.strip_ansi(raw_line)
                log_queue.put(line + ("\n" if not line.endswith("\n") else ""))
                progress = utils.parse_whisper_progress(line)
                if progress:
                    try:
                        batch_queue.update_item_progress(item_idx, progress["percent"])
                        batch_queue.update_current_file_eta(progress["remaining_seconds"])
                    except Exception:
                        pass
                # Capture detected source language from lines like:
                # Detected language 'ru': 99%
                detected_match = re.search(r"Detected\s+language\s+['\"]([a-z]{2,3})['\"]", line, re.IGNORECASE)
                if detected_match:
                    try:
                        batch_queue.set_detected_language(item_idx, detected_match.group(1).lower())
                    except Exception:
                        pass
        except Exception:
            pass
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass

    all_downloadable_files = []
    all_clean_text = ""
    processed_srt_paths = [] 

    utils.log_queue.put(f"[STAGE] Loading Whisper model {model_size} ({compute_type})...\n")
    utils.model_load_start_time = time.time()

    # Build process creationflags once (Windows priority)
    creationflags = 0
    if os.name == "nt":
        prio = {
            "below_normal": getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000),
            "idle":         getattr(subprocess, "IDLE_PRIORITY_CLASS", 0x00000040),
            "normal":       0,
        }.get(WHISPER_PROCESS_PRIORITY, 0)
        creationflags = prio
    log_queue.put(f"⚙️ Process priority: {WHISPER_PROCESS_PRIORITY}\n")

    # Build subprocess env with CPU thread limit
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(WHISPER_MAX_THREADS)
    env["CT2_FORCE_CPU_ISA"] = env.get("CT2_FORCE_CPU_ISA", "")
    log_queue.put(f"⚙️ CPU thread limit: {WHISPER_MAX_THREADS}\n")

    # Optional GPU power limit (best-effort, fully reversible)
    _prev_gpu_power = _gpu_power_limit_set(WHISPER_GPU_POWER_LIMIT_W)

    # Emit queue state for batch panel
    total_files = len(files_to_process)
    for i, fp in enumerate(files_to_process):
        log_queue.put(f"[PROGRESS_FILE] | {i+1} | {total_files} | {os.path.basename(fp)} | queued\n")

    try:
        if not WHISPER_EXE or not Path(WHISPER_EXE).is_file():
            raise RuntimeError(WHISPER_EXE_HINT)
        for idx, video_path in enumerate(files_to_process):
            if stop_requested: break
            full_whisper_log = "" 
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            log_queue.put(f"\n🚜 [BATCH {idx+1}/{len(files_to_process)}] Processing: {base_name}\n")

            current_queue_item = _find_queue_item(video_path)
            if current_queue_item is not None:
                batch_queue.mark_item_running(current_queue_item.idx)
            log_queue.put(f"[PROGRESS_FILE] | {current_queue_item.idx if current_queue_item else idx+1} | {total_files} | {base_name} | running\n")
            
            if use_custom_output and output_dir.strip(): current_out_dir = output_dir.strip()
            elif "Temp" in video_path or "temp" in video_path: current_out_dir = DEFAULT_OUTPUT_DIR
            else: current_out_dir = os.path.dirname(os.path.abspath(video_path))
                
            os.makedirs(current_out_dir, exist_ok=True)
            
            command = [WHISPER_EXE]
            if output_formats: command.append("--output_format"); command.extend(output_formats)
            if language and language != "auto": command.extend(["--language", language])
            command.extend(["--model", model_size, f"--compute_type={compute_type}"])
            if initial_prompt and initial_prompt != "auto": command.extend(["-prompt", initial_prompt])
            if hotwords: command.extend(["--hotwords", hotwords])
            if temperature != 0.0: command.extend(["--temperature", str(temperature)])
            if rep_penalty != 1.0: command.extend(["--repetition_penalty", str(rep_penalty)])
            if beam_size != 5: command.extend(["--beam_size", str(int(beam_size))])
            if patience != 1.0: command.extend(["--patience", str(patience)])
            if not condition_on_prev: command.extend(["--condition_on_previous_text", "False"])
            if no_speech_thresh != 0.6: command.extend(["--no_speech_threshold", str(no_speech_thresh)])
            if vad_method != "No VAD": command.extend(["--vad_method", vad_method])
            if use_sentence: command.append("--sentence")
            if use_print_progress: command.append("--print_progress")
            if use_vad_filter: command.extend(["--vad_filter", "True"])
            if use_beep_off: command.append("--beep_off")
            # --threads flag confirmed via --help (MUST be before -- separator!)
            command.extend(["--threads", str(WHISPER_MAX_THREADS)])
            command.extend(["--output_dir", current_out_dir, "--", video_path])

            # Log the exact command for diagnostics ([CMD] one element per line)
            for i, cmd_part in enumerate(command):
                log_queue.put(f"[CMD] {i}: {cmd_part}\n")

            current_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, shell=False, creationflags=creationflags, env=env)
            threading.Thread(target=_read_whisper_output_and_track, args=(current_process, current_queue_item.idx if current_queue_item else idx+1), daemon=True).start()
            current_process.wait()
            if current_queue_item is not None:
                batch_queue.update_item_progress(current_queue_item.idx, 100.0) 
            if idx < len(files_to_process) - 1 and WHISPER_COOLDOWN_SEC > 0:
                log_queue.put(f"❄️ Cooling down {WHISPER_COOLDOWN_SEC}s...\n")
                if interruptible_sleep(float(WHISPER_COOLDOWN_SEC)): break
            else:
                if interruptible_sleep(1.0): break 
            
            # 🚀 ИСПРАВЛЕНИЕ ДЛЯ WINDOWS: Заменили 'glob' на надежный 'os.listdir'
            current_file_downloads = []
            if os.path.exists(current_out_dir):
                for fname in os.listdir(current_out_dir):
                    if fname.startswith(base_name):
                        for ext in output_formats:
                            if fname.endswith(f".{ext}") and "_TRANSLATED_" not in fname:
                                current_file_downloads.append(os.path.abspath(os.path.join(current_out_dir, fname)))
                                
            current_file_downloads = list(set(current_file_downloads))

            # Generate *_CLEAN.txt plain-text sidecars when requested.
            if plain_text_output and not stop_requested:
                clean_paths = []
                for produced_path in current_file_downloads:
                    if produced_path.lower().endswith(('.srt', '.vtt')):
                        try:
                            with open(produced_path, 'r', encoding='utf-8') as f:
                                raw_text = f.read()
                            clean_text = clean_srt_text(raw_text)
                            clean_path = os.path.join(
                                os.path.dirname(produced_path),
                                f"{os.path.splitext(os.path.basename(produced_path))[0]}_CLEAN.txt"
                            )
                            with open(clean_path, 'w', encoding='utf-8') as f:
                                f.write(clean_text)
                            clean_paths.append(clean_path)
                            log_queue.put(f"[CLEAN] {os.path.basename(clean_path)}\n")
                        except Exception as e:
                            log_queue.put(f"️ Could not create clean text for {produced_path}: {e}\n")
                current_file_downloads.extend(clean_paths)
                
            if stop_requested and not current_file_downloads:
                rescued_text = rescue_text_from_log(full_whisper_log)
                if rescued_text:
                    partial_path = os.path.join(current_out_dir, f"{base_name}_PARTIAL.txt")
                    rescued_path = utils.unique_path(partial_path)
                    if rescued_path != partial_path:
                        log_queue.put(f"[SAVE] Existing file kept. Writing {os.path.basename(rescued_path)} instead.\n")
                    try:
                        with open(rescued_path, "w", encoding="utf-8") as f: f.write(rescued_text)
                        current_file_downloads.append(rescued_path)
                        log_queue.put(f"\n✅ TEXT RESCUED: {rescued_path}\n")
                    except: pass

            # 🔊 EXTRACT AND SAVE AUDIO TRACK AS MP3 IF REQUESTED
            if save_audio_track and not stop_requested:
                try:
                    import ffmpeg
                    audio_path = os.path.join(current_out_dir, f"{base_name}.mp3")
                    (
                        ffmpeg
                        .input(video_path)
                        .output(audio_path, acodec='libmp3lame', audio_bitrate='192k')
                        .overwrite_output()
                        .run(quiet=True, capture_stdout=True, capture_stderr=True)
                    )
                    if os.path.exists(audio_path):
                        all_downloadable_files.append(audio_path)
                        log_queue.put(f"\n🔊 AUDIO TRACK SAVED: {os.path.basename(audio_path)}\n")
                except ImportError:
                    log_queue.put("⚠️ To save audio tracks install: pip install ffmpeg-python\n")
                except Exception as e:
                    log_queue.put(f"❌ Audio extraction error: {e}\n")

            all_downloadable_files.extend(current_file_downloads)

            # Record produced files against the queue item for batch post-processing (BC6)
            if current_queue_item is not None:
                for produced_path in current_file_downloads:
                    batch_queue.add_produced_file(current_queue_item.idx, produced_path)

            # Collect translation-ready text/subtitle files produced for this item
            trans_exts = ('.srt', '.txt')
            item_trans_paths = [f for f in current_file_downloads if f.lower().endswith(trans_exts) and "_TRANSLATED_" not in f and "_PARTIAL" not in f and not f.endswith("_CLEAN.txt")]
            if item_trans_paths:
                processed_srt_paths.extend(item_trans_paths)
            else:
                log_queue.put(f"[ERROR] {base_name} produced no subtitle/text files\n")
            
            txt_files = [f for f in current_file_downloads if f.endswith('.txt')]
            if txt_files:
                try:
                    with open(txt_files[0], 'r', encoding='utf-8') as f: clean_text_result = f.read()
                    clean_text_result = re.sub(r'\[\d{2}:\d{2}(:\d{2})?\.\d{3}.*?\d{2}:\d{2}(:\d{2})?\.\d{3}\]\s*', '', clean_text_result)
                    all_clean_text += f"\n--- {base_name} ---\n" + "\n".join([line for line in clean_text_result.split('\n') if line.strip()]) + "\n"
                except: pass
            
            if current_queue_item is not None:
                batch_queue.mark_item_done(current_queue_item.idx)
            log_queue.put(f"[PROGRESS_FILE] | {current_queue_item.idx if current_queue_item else idx+1} | {total_files} | {base_name} | done\n")
            
        final_status = gr.update(elem_classes=["status-error"]) if stop_requested else gr.update(elem_classes=["status-done"])
        if not stop_requested: log_queue.put(f"\n✅ BATCH DONE! Files processed: {len(processed_srt_paths)}\n")

    except Exception as e:
        log_queue.put(f"\n⚠️ ERROR: {e}\n")
        if current_queue_item is not None:
            batch_queue.mark_item_failed(current_queue_item.idx, str(e))
        final_status = gr.update(elem_classes=["status-error"])
    finally:
        _gpu_power_limit_restore(_prev_gpu_power)
        process_active = False; current_process = None
        current_action = "Stopped" if stop_requested else "Done"


    # Ensure unique, stable handoff list (preserve order, no duplicates)
    seen_paths = []
    for p in processed_srt_paths:
        if p not in seen_paths:
            seen_paths.append(p)
    produced_text_paths = seen_paths

    if produced_text_paths:
        log_queue.put(f"[STAGE] Transcription produced {len(produced_text_paths)} file(s), handing off to translation\n")
    else:
        log_queue.put("[STAGE] Transcription produced 0 files, nothing to hand off to translation\n")

    all_paths_str = "|".join(produced_text_paths)
    last_path = produced_text_paths[-1] if produced_text_paths else ""
    return gr.update(value=all_clean_text), gr.update(value=all_downloadable_files if all_downloadable_files else []), final_status, all_paths_str, last_path, global_out_dir