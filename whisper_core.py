import os
import subprocess
import threading
import re
import time
import shutil
import sys
from pathlib import Path
from typing import List, Tuple, Any
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
    current_action, enqueue_output
)
from ui_manager import ui_state

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


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from yt-dlp output."""
    return re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)


def _download_url_to_queue(
    url: str, output_dir: str, cookie_browser: str,
    files_to_process: List[Any], downloaded_audio_files: List[Any]
):
    """Download a single URL via yt-dlp CLI (subprocess), stream output, and queue the result."""
    original_url = url
    url = utils.canonical_media_url(url)
    if url != original_url:
        log_queue.put(f"[URL] Normalised: {original_url} -> {url}\n")
    log_queue.put(f"⬇️ Downloading: {url}\n")

    is_playlist = "/playlist?" in url or "list=" in url
    temp_dir = os.path.join(output_dir, f".ytdlp_{os.getpid()}_{int(time.time()*1000)}")
    os.makedirs(temp_dir, exist_ok=True)

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-warnings",
        "--no-playlist",
        "-f", "bestaudio/best",
        "-o", "%(title)s.%(ext)s",
        "--progress",
    ]
    if cookie_browser and cookie_browser != "None":
        cmd.extend(["--cookies-from-browser", cookie_browser])
    cmd.append(url)

    process = None
    try:
        process = subprocess.Popen(
            cmd, cwd=temp_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
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
            line = _strip_ansi(raw_line).strip()
            if line:
                log_queue.put(line + "\n")
                lower = line.lower()
                if "sign in" in lower or "signin" in lower:
                    log_queue.put("[ERROR] YouTube requires sign-in for this video. Set COOKIES FROM BROWSER and retry.\n")
                elif "age-restricted" in lower or "age restricted" in lower:
                    log_queue.put("[ERROR] YouTube requires sign-in for this video. Set COOKIES FROM BROWSER and retry.\n")

        if not utils.stop_requested:
            process.wait(timeout=10)
            if process.returncode == 0:
                downloaded = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if os.path.isfile(os.path.join(temp_dir, f))]
                for f in downloaded:
                    dest = os.path.join(output_dir, os.path.basename(f))
                    if os.path.abspath(f) != os.path.abspath(dest):
                        try:
                            os.replace(f, dest)
                        except Exception:
                            shutil.move(f, dest)
                    if os.path.exists(dest):
                        files_to_process.append(dest)
                        downloaded_audio_files.append(dest)
                        log_queue.put(f"✅ Successfully extracted: {os.path.basename(dest)}\n")
            else:
                err_msg = f"yt-dlp exited with code {process.returncode} for URL: {url}"
                log_queue.put(f"❌ {err_msg}\n")
    except Exception as e:
        log_queue.put(f"❌ URL download error for {url}: {e}\n")
    finally:
        try:
            for f in os.listdir(temp_dir):
                fp = os.path.join(temp_dir, f)
                if os.path.exists(fp):
                    os.remove(fp)
            os.rmdir(temp_dir)
        except Exception:
            pass
        utils.current_process = None

def run_transcription(
    input_files: List[Any], manual_path: str, urls_input: str, initial_prompt: str, hotwords: str,
    vad_method: str, language: str, model_size: str, compute_type: str,
    temperature: float, rep_penalty: float, beam_size: float, patience: float,
    condition_on_prev: bool, no_speech_thresh: float, use_sentence: bool,
    use_print_progress: bool, use_vad_filter: bool, use_beep_off: bool,
    use_custom_output: bool, output_dir: str, output_formats: List[str], save_audio_track: bool,
    cookie_browser: str = "None"
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
        "whisper_cookie_browser": cookie_browser
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
    if use_custom_output: os.makedirs(global_out_dir, exist_ok=True)

    downloaded_audio_files = []
    urls_input = (urls_input or "").strip()
    if urls_input:
        if not YT_DLP_AVAILABLE:
            log_queue.put("⚠️ ERROR: yt-dlp library is not installed! Run: pip install yt-dlp\n")
        else:
            urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
            if urls:
                log_queue.put(f"[STAGE] Downloading audio from {len(urls)} URL(s) (yt-dlp)...\n")
                for url in urls:
                    if stop_requested: break
                    _download_url_to_queue(
                        url, global_out_dir, cookie_browser,
                        files_to_process, downloaded_audio_files
                    )
                    
    files_to_process = list(set(files_to_process))
    
    if not files_to_process:
        current_action = "Error"
        return gr.update(value="Error: No files found!"), gr.update(value=[]), gr.update(elem_classes=["status-error"]), "", "", ""
    
    process_active = True
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
            log_queue.put(f"[PROGRESS_FILE] | {idx+1} | {total_files} | {base_name} | running\n")
            
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
            if vad_method != "Без VAD": command.extend(["--vad_method", vad_method])
            if use_sentence: command.append("--sentence")
            if use_print_progress: command.append("--print_progress")
            if use_vad_filter: command.extend(["--vad_filter", "True"])
            if use_beep_off: command.append("--beep_off")
            # --threads flag confirmed via --help (MUST be before -- separator!)
            command.extend(["--threads", str(WHISPER_MAX_THREADS)])
            command.extend(["--output_dir", current_out_dir, "--", video_path])

            current_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1, universal_newlines=True, creationflags=creationflags, env=env)
            threading.Thread(target=enqueue_output, args=(current_process.stdout, log_queue), daemon=True).start()
            current_process.wait() 
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

            # Collect translation-ready text/subtitle files produced for this item
            trans_exts = ('.srt', '.txt')
            item_trans_paths = [f for f in current_file_downloads if f.lower().endswith(trans_exts) and "_TRANSLATED_" not in f and "_PARTIAL" not in f]
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
            
            log_queue.put(f"[PROGRESS_FILE] | {idx+1} | {total_files} | {base_name} | done\n")
            
        final_status = gr.update(elem_classes=["status-error"]) if stop_requested else gr.update(elem_classes=["status-done"])
        if not stop_requested: log_queue.put(f"\n✅ BATCH DONE! Files processed: {len(processed_srt_paths)}\n")

    except Exception as e:
        log_queue.put(f"\n⚠️ ERROR: {e}\n")
        final_status = gr.update(elem_classes=["status-error"])
    finally:
        _gpu_power_limit_restore(_prev_gpu_power)
        process_active = False; current_process = None
        current_action = "Stopped" if stop_requested else "Done"
        if downloaded_audio_files:
            log_queue.put("\n🧹 Cleaning up temporary files...\n")
            for f in downloaded_audio_files:
                try:
                    if os.path.exists(f): os.remove(f)
                except: pass

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