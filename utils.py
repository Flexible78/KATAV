import sys
import logging
import traceback
import subprocess
import os
import threading
import queue
import time
import json
import re
from typing import Dict, Any, Tuple
from urllib.parse import urlparse, parse_qs
import gradio as gr

from config import CONFIG_FILE, DEFAULT_OUTPUT_DIR

# ==============================================================================
# 1. ЛОГГИРОВАНИЕ И ИНИЦИАЛИЗАЦИЯ
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("whisper_app.log", encoding="utf-8", mode="w"),
        logging.StreamHandler(sys.stdout)
    ]
)

def log_to_terminal(msg: str) -> None:
    logging.info(msg)

# Глобальные переменные
log_queue = queue.Queue()       
process_active = False          
current_process = None          
stop_requested = False          
full_whisper_log = ""           

current_action = "Waiting..."
current_percent = 0
time_elapsed = "00:00"
time_remaining = "00:00"
audio_speed = "0.00x"
GEMINI_READY = False
OPENAI_READY = False
model_load_start_time = 0.0

# ==============================================================================
# УТИЛИТЫ И КЛЮЧИ
# ==============================================================================
def load_keys() -> Dict[str, str]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: return {}
    return {}

def save_keys(google_key: str, or_key: str, studio_key: str = "", groq_key: str = "") -> None:
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: 
            json.dump({
                "google": google_key, 
                "openrouter": or_key,
                "google_studio": studio_key,
                "groq": groq_key
            }, f, indent=4)
    except Exception: pass

def interruptible_sleep(seconds: float) -> bool:
    global stop_requested
    steps = int(seconds * 10)
    for _ in range(steps if steps > 0 else 1):
        if stop_requested: return True
        time.sleep(0.1)
    return False

def sanitize_srt_text(text: str) -> str:
    text = text.replace('\ufeff', '') 
    text = re.sub(r'==== ОШИБКА ПЕРЕВОДА БЛОКА ====\n?', '', text)
    text = re.sub(r'<(thought|think)>.*?</\1>\n?', '', text, flags=re.DOTALL)
    return text.strip()

def enqueue_output(out, queue_obj: queue.Queue):
    buf = ""
    try:
        while True:
            char = out.read(1)
            if not char:
                if buf: queue_obj.put(buf)
                break
            if char in ['\r', '\n']:
                if buf: queue_obj.put(buf + '\n'); buf = ""
            else: buf += char
    except Exception: pass
    finally: out.close()

def rescue_text_from_log(log_text: str) -> str:
    lines = log_text.split('\n')
    extracted = []
    pattern = re.compile(r'\[\d+:\d+.*?\d+:\d+.*?\]\s*(.*)')
    for line in lines:
        match = pattern.search(line)
        if match:
            text = match.group(1).strip()
            if text: extracted.append(text)
    return "\n".join(extracted)

def get_actual_output_dir(manual_path: str, use_custom: bool, custom_dir: str) -> str:
    if use_custom and custom_dir.strip(): return custom_dir.strip()
    m_path = (manual_path or "").strip()
    if m_path:
        first_path = m_path.split('|')[0].strip().strip('"').strip("'")
        if os.path.isdir(first_path): return first_path
        if os.path.isfile(first_path): return os.path.dirname(os.path.abspath(first_path))
    return DEFAULT_OUTPUT_DIR

def stop_all_processes():
    global stop_requested, current_process, log_queue
    stop_requested = True
    if current_process:
        try: current_process.terminate() 
        except Exception: pass
    log_queue.put("\n🛑 STOP SIGNAL! Finishing current tasks...\n")
    return gr.update(elem_classes=["status-error"])

def restart_app():
    log_to_terminal("=== APP RESTART INITIATED BY USER ===")
    try: os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception: pass

def kill_program():
    global current_process
    import subprocess as _subprocess
    import time as _time

    # 1. Terminate the current transcription/translation process cleanly.
    if current_process:
        try:
            current_process.terminate()
        except Exception:
            pass
        try:
            current_process.wait(timeout=3)
        except Exception:
            try:
                current_process.kill()
            except Exception:
                pass

    own_pid = os.getpid()
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".katav_pids")
    pids_to_kill = []
    by_title = False

    # 2. Read recorded PIDs and filter out own PID.
    #    Read in binary to tolerate UTF-16LE, UTF-8 or ANSI; strip NUL bytes
    #    and extract decimal PID substrings.
    if os.path.exists(pid_file):
        try:
            raw = open(pid_file, "rb").read()
            cleaned = raw.replace(b"\x00", b"")
            text = cleaned.decode("utf-8", errors="ignore")
            for pid_str in re.findall(r"\d+", text):
                pid = int(pid_str)
                if pid != own_pid:
                    pids_to_kill.append(pid)
        except Exception as e:
            logging.warning(f"[EXIT] Failed to read PID file {pid_file}: {e}")

    # 3. Fallback: find processes listening on ports 8080 and 7861,
    #    walking up from the python child to its cmd.exe parent.
    if os.name == 'nt':
        if not pids_to_kill:
            for port in (8080, 7861):
                try:
                    result = _subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"],
                        capture_output=True, text=True, timeout=5,
                        creationflags=0x08000000,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        for pid_str in result.stdout.strip().splitlines():
                            pid_str = pid_str.strip()
                            if pid_str and pid_str.isdigit():
                                pid = int(pid_str)
                                if pid == own_pid:
                                    continue
                                # Prefer the parent cmd.exe so the console window dies.
                                try:
                                    proc_info = _subprocess.run(
                                        ["powershell", "-NoProfile", "-Command",
                                         f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").ParentProcessId"],
                                        capture_output=True, text=True, timeout=5,
                                        creationflags=0x08000000,
                                    )
                                    if proc_info.returncode == 0 and proc_info.stdout.strip():
                                        parent = int(proc_info.stdout.strip().splitlines()[0].strip())
                                        if parent and parent != own_pid and parent not in pids_to_kill:
                                            pids_to_kill.append(parent)
                                        elif pid != own_pid and pid not in pids_to_kill:
                                            pids_to_kill.append(pid)
                                    else:
                                        if pid != own_pid and pid not in pids_to_kill:
                                            pids_to_kill.append(pid)
                                except Exception:
                                    if pid != own_pid and pid not in pids_to_kill:
                                        pids_to_kill.append(pid)
                except Exception:
                    pass

        # 4. Fallback by window titles (works even without a PID file).
        if not pids_to_kill:
            try:
                for title in ("KATAV Main*", "KATAV AI Proxy*"):
                    _subprocess.run(
                        ["taskkill", "/F", "/T", "/FI", f"WINDOWTITLE eq {title}"],
                        capture_output=True, text=True, timeout=5,
                        creationflags=0x08000000,
                    )
                by_title = True
            except Exception:
                pass

    # 5. Kill recorded/fallback PIDs.
    if os.name == 'nt':
        for pid in pids_to_kill:
            try:
                _subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, text=True, timeout=5,
                    creationflags=0x08000000,
                )
            except Exception:
                pass

    # 6. Delete PID file.
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass

    # 7. Log and exit.
    logging.info(f"[EXIT] killed pids: {pids_to_kill} | by title: {'yes' if by_title else 'no'}")
    logging.shutdown()
    os._exit(0)

def unique_path(path: str) -> str:
    """Return path if free, else path with _1, _2, ... before the extension."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 1000):
        candidate = f"{base}_{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
    # Fall back to timestamp after 999 attempts
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{base}_{timestamp}{ext}"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    if not text:
        return text
    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def canonical_media_url(url: str) -> str:
    """
    Canonicalise a media URL.

    - youtube.com/watch and youtu.be -> https://www.youtube.com/watch?v=<id>
    - /playlist?list= links are returned unchanged
    - non-YouTube URLs are returned unchanged
    - never raises; on parse problems returns the input unchanged
    """
    if not isinstance(url, str):
        return url
    try:
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower()
        if netloc in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"):
            # Genuine playlist request
            if parsed.path in ("/playlist", "/playlist/") or parsed.path.startswith("/playlist"):
                return url
            # youtube.com/watch?v=...
            if parsed.path in ("/watch", "/watch/") or parsed.path.endswith("/watch"):
                qs = parse_qs(parsed.query)
                v_list = qs.get("v")
                if v_list:
                    return f"https://www.youtube.com/watch?v={v_list[0]}"
                return url
            # youtu.be/<id>
            if netloc in ("youtu.be", "www.youtu.be"):
                segments = [s for s in parsed.path.strip("/").split("/") if s]
                if segments:
                    return f"https://www.youtube.com/watch?v={segments[0]}"
                return url
        return url
    except Exception:
        return url


WHISPER_PROGRESS_RE = re.compile(
    r"(?P<percent>\d+(?:\.\d+)?)%\s*\|\s*"
    r"(?P<done>\d+)\/(?P<total>\d+)\s*\|\s*"
    r"(?P<elapsed>(?:\d{1,2}:)?\d{2}:\d{2})\s*<<?\s*(?P<remaining>(?:\d{1,2}:)?\d{2}:\d{2})\s*\|\s*"
    r"(?P<speed>[\d.]+)\s*audio\s*seconds?\/s",
    re.IGNORECASE,
)


def _parse_time_to_seconds(value: str) -> int:
    """Convert 'HH:MM:SS' or 'MM:SS' to total seconds."""
    parts = [int(p) for p in value.strip().split(":") if p.isdigit()]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


def parse_whisper_progress(line: str) -> Dict[str, Any] | None:
    """Parse a faster-whisper progress line into structured data.

    Example: '89% | 728/818 | 02:29<<00:24 |  4.87 audio seconds/s'
    Returns a dict with: percent, done, total, elapsed_seconds, remaining_seconds, speed.
    """
    if not line:
        return None
    match = WHISPER_PROGRESS_RE.search(line)
    if not match:
        return None
    try:
        return {
            "percent": float(match.group("percent")),
            "done": int(match.group("done")),
            "total": int(match.group("total")),
            "elapsed_seconds": _parse_time_to_seconds(match.group("elapsed")),
            "remaining_seconds": _parse_time_to_seconds(match.group("remaining")),
            "speed": float(match.group("speed")),
        }
    except Exception:
        return None


def process_logs(current_log: str) -> Tuple[str, str]:
    global current_percent, time_elapsed, time_remaining, audio_speed, full_whisper_log, current_action
    new_text = current_log
    try:
        while not log_queue.empty():
            line = log_queue.get()
            new_text += line
            full_whisper_log += line 
            match = re.search(r'(\d+)%\s*\|\s*\d+/\d+\s*\|\s*(\d{2}:\d{2})<<?(\d{2}:\d{2})\s*\|\s*([\d.]+)', line)
            if match:
                current_percent = int(match.group(1))
                time_elapsed = match.group(2)
                time_remaining = match.group(3)
                audio_speed = f"{match.group(4)}x"
    except Exception: pass 
            
    metrics_html = f"""
    <div style="background: rgba(30, 41, 59, 0.8); padding: 15px; border-radius: 12px; border: 1px solid #475569; margin-bottom: 10px; box-shadow: inset 0 2px 10px rgba(0,0,0,0.5);">
        <div style="display: flex; justify-content: space-between; margin-bottom: 8px; font-weight: bold; font-size: 16px; color: #f4f4f5; text-transform: uppercase; letter-spacing: 0.5px;">
            <span>{current_action}</span><span style="color: #ea580c;">{current_percent}%</span>
        </div>
        <div style="width: 100%; background-color: #18181b; border-radius: 8px; overflow: hidden; height: 24px; border: 1px solid #27272a;">
            <div style="width: {current_percent}%; height: 100%; background: linear-gradient(90deg, #9a3412, #ea580c); box-shadow: inset 0 1px 2px rgba(255,255,255,0.2); transition: width 0.3s ease;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 10px; color: #a1a1aa; font-family: 'Courier New', Courier, monospace; font-size: 14px; font-weight: bold;">
            <span>⏱ Elapsed: <span style="color:#d4d4d8;">{time_elapsed}</span></span>
            <span>⏳ Left: <span style="color:#f87171;">{time_remaining}</span></span>
            <span>⚡ Speed: <span style="color:#34d399;">{audio_speed}</span></span>
        </div>
    </div>
    """
    return new_text, metrics_html
    
# ==============================================================================
# 11. МЕХАНИЗМ ПАУЗЫ
# ==============================================================================
pause_requested = False

def toggle_pause():
    global pause_requested
    pause_requested = not pause_requested
    status = "⏸ PAUSE ENABLED (Process waiting...)" if pause_requested else "▶️ PROCESS RESUMED!"
    log_queue.put(f"\n{status}\n")
    return gr.update(value="▶️ RESUME" if pause_requested else "⏸ PAUSE", variant="primary" if pause_requested else "secondary")