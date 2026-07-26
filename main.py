import os
import sys
import logging
import warnings
import subprocess

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
        logging.FileHandler("whisper_app.log", encoding="utf-8", mode="a"), # append mode
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
             f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess"],
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
                if image.lower() in ("python.exe", "pythonw.exe"):
                    try:
                        cmdline_result = subprocess.run(
                            ["powershell", "-NoProfile", "-Command",
                             f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
                            capture_output=True, text=True, timeout=5,
                            creationflags=0x08000000,
                        )
                        cmdline = cmdline_result.stdout.strip()
                        if "main.py" in cmdline and os.path.dirname(os.path.abspath(__file__)) in cmdline:
                            logging.info("[PORT] Killing old KATAV instance (PID %d)", pid)
                            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                           capture_output=True, timeout=10,
                                           creationflags=0x08000000)
                    except Exception:
                        pass
                else:
                    logging.error("[PORT] %d held by foreign process %s (PID %d). Stop it or use GRADIO_SERVER_PORT.",
                                  port, image, pid)
                    return False
    except Exception as e:
        logging.debug("[PORT] check skipped: %s", e)
    return True


def main():
    # Убедимся, что папка Outputs существует
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    logging.info(f"Output folder '{DEFAULT_OUTPUT_DIR}' is ready.")

    app = build_app()
    from config import custom_css
    favicon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")

    if not _check_port(PORT):
        print(f"[PORT] {PORT} is held by another application. Set GRADIO_SERVER_PORT env var to use a different port.")
        sys.exit(1)

    try:
        app.launch(server_port=PORT, inbrowser=True, debug=False,
                   css=custom_css, favicon_path=favicon_path,
                   analytics_enabled=False)
    except OSError:
        print(f"Port {PORT} is busy. Starting on an automatically chosen free port.")
        app.launch(server_port=None, inbrowser=True, debug=False,
                   css=custom_css, favicon_path=favicon_path,
                   analytics_enabled=False)

if __name__ == "__main__":
    main()