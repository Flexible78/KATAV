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

    # 2. Read recorded PIDs and filter out own PID.
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r', encoding='utf-8') as f:
                for line in f:
                    pid_str = line.strip()
                    if pid_str and pid_str.isdigit():
                        pid = int(pid_str)
                        if pid != own_pid:
                            pids_to_kill.append(pid)
        except Exception:
            pass

    # 3. Fallback: find the process listening on port 8080.
    if not pids_to_kill and os.name == 'nt':
        try:
            result = _subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue).OwningProcess"],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000,
            )
            if result.returncode == 0 and result.stdout.strip():
                for pid_str in result.stdout.strip().splitlines():
                    pid_str = pid_str.strip()
                    if pid_str and pid_str.isdigit():
                        pid = int(pid_str)
                        if pid != own_pid:
                            pids_to_kill.append(pid)
        except Exception:
            pass

    # 4. Kill recorded/fallback PIDs.
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

    # 5. Delete PID file.
    try:
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except Exception:
        pass

    # 6. Log and exit.
    log_queue.put(f"[EXIT] Terminating {len(pids_to_kill)} child process(es)...\n")
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