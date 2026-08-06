import gradio as gr
import os
import sys
import logging
import warnings
import subprocess
import inspect
import time

# Silence the google.generativeai deprecation notice without hiding other warnings.
warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")

# Disable Gradio telemetry (local tool, no network needed at startup).
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

# Проверяем наличие необходимых библиотек AI
try:
    import google.generativeai as genai
    from utils import GEMINI_READY
    GEMINI_READY = True
except ImportError:
    logging.warning("Module 'google-generativeai' is not installed. Gemini AI functions will be unavailable.")
    
try:
    from openai import OpenAI
    from utils import OPENAI_READY
    OPENAI_READY = True
except ImportError:
    logging.warning("Module 'openai' is not installed. OpenAI-compatible AI functions will be unavailable.")

from gradio_app import build_app
from config import PORT, DEFAULT_OUTPUT_DIR

# Allow overriding the Gradio port via environment variable (defaults to config.PORT)
PORT = int(os.getenv("GRADIO_SERVER_PORT", str(PORT)))

# Настройка логирования для main.py
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8", mode="a"), # append mode
        logging.StreamHandler(sys.stdout)
    ]
)


def _check_port(port: int) -> bool:
    """Return True if *port* is free; otherwise log the owner and decide."""
    if os.name != "nt":
        return True  # non-Windows: let Gradio handle it
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue).OwningProcess"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return True
        for line in result.stdout.strip().splitlines():
            pid_str = line.strip()
            if pid_str and pid_str.isdigit():
                pid = int(pid_str)
                # Get image name and command line
                try:
                    info = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object ProcessName -ExpandProperty ProcessName)"],
                        capture_output=True, text=True, timeout=5,
                        creationflags=0x08000000,
                    )
                    image = info.stdout.strip() or "unknown"
                except Exception:
                    image = "unknown"
                logging.info("[PORT] %d busy, owner PID %d (%s)", port, pid, image)
                # If it's an old KATAV instance (python running main.py), kill it
                if image == "unknown":
                    logging.info("[PORT] Owner PID %d no longer exists; treating port as free.", pid)
                    continue
                if image.lower().removesuffix(".exe") in ("python", "pythonw"):
                    try:
                        cmdline_result = subprocess.run(
                            ["powershell", "-NoProfile", "-Command",
                             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
                            capture_output=True, text=True, timeout=5,
                            creationflags=0x08000000,
                        )
                        cmdline = cmdline_result.stdout.strip()
                        base_dir = os.path.dirname(os.path.abspath(__file__))
                        if "main.py" in cmdline.lower() and base_dir.lower() in cmdline.lower():
                            logging.info("[PORT] Killing old KATAV instance (PID %d)", pid)
                            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                           capture_output=True, timeout=10,
                                           creationflags=0x08000000)
                            time.sleep(2)
                        else:
                            logging.error("[PORT] %d held by another python app (PID %d). Stop it or use GRADIO_SERVER_PORT.", port, pid)
                            return False
                    except Exception:
                        pass
                else:
                    logging.error("[PORT] %d held by foreign process %s (PID %d). Stop it or use GRADIO_SERVER_PORT.",
                                  port, image, pid)
                    return False
    except Exception as e:
        logging.debug("[PORT] check skipped: %s", e)
    return True


def _register_pids():
    """Record this process and its parent in .katav_pids so the EXIT button
    always finds the real KATAV processes even if start.bat missed them."""
    pid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".katav_pids")
    pids = {os.getpid()}
    if os.name == "nt":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ProcessId={os.getpid()}\").ParentProcessId"],
                capture_output=True, text=True, timeout=5,
                creationflags=0x08000000,
            )
            head = res.stdout.strip().splitlines()
            if head and head[0].strip().isdigit():
                pids.add(int(head[0].strip()))
        except Exception:
            pass
    existing = set()
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "rb") as fh:
                text = fh.read().replace(b"\x00", b"").decode("utf-8", errors="ignore")
            for tok in text.split():
                if tok.isdigit():
                    existing.add(int(tok))
        except Exception:
            pass
    try:
        with open(pid_file, "w", encoding="ascii") as fh:
            for pid in sorted(existing | pids):
                fh.write(str(pid) + chr(10))
        logging.info("[PIDS] registered %s (file now: %s)", sorted(pids), sorted(existing | pids))
    except Exception as e:
        logging.warning("[PIDS] registration failed: %s", e)


def main():
    # Убедимся, что папка Outputs существует
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    logging.info(f"Output folder '{DEFAULT_OUTPUT_DIR}' is ready.")
    _register_pids()

    app = build_app()
    from config import custom_css
    favicon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")

    if not _check_port(PORT):
        print(f"[PORT] {PORT} is held by another application. Set GRADIO_SERVER_PORT env var to use a different port.")
        sys.exit(1)

    launch_kwargs = {
        "server_port": PORT,
        "inbrowser": True,
        "debug": False,
        "css": custom_css,
    }
    if os.path.isfile(favicon_path):
        launch_kwargs["favicon_path"] = favicon_path

    # Gradio 6 moved/removed several launch() parameters. Keep only what the
    # installed version really accepts instead of guessing from the docs.
    allowed = set(inspect.signature(app.launch).parameters)
    dropped = sorted(k for k in launch_kwargs if k not in allowed)
    if dropped:
        logging.info("[LAUNCH] Gradio %s ignores: %s", gr.__version__, ", ".join(dropped))
    launch_kwargs = {k: v for k, v in launch_kwargs.items() if k in allowed}

    logging.info("[LAUNCH] Starting on http://127.0.0.1:%d", PORT)
    try:
        app.launch(**launch_kwargs)
    except OSError as e:
        # Never drift to a random free port: 7860 belongs to LECTA and silent
        # drift breaks the EXIT logic that looks for the process on 7861.
        logging.error("[PORT] Could not bind %d: %s", PORT, e)
        print(f"[PORT] {PORT} is not available. Free it, or set GRADIO_SERVER_PORT to another port.")
        sys.exit(1)

if __name__ == "__main__":
    main()
