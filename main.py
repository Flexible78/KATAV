import os
import sys
import logging

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

def main():
    # Убедимся, что папка Outputs существует
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    logging.info(f"Output folder '{DEFAULT_OUTPUT_DIR}' is ready.")

    app = build_app()
    # ИСПРАВЛЕНИЕ: Удален show_api=False, который вызывал фатальную ошибку
    from config import custom_css
    favicon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "favicon.ico")
    try:
        app.launch(server_port=PORT, inbrowser=True, debug=False,
                   css=custom_css, favicon_path=favicon_path)
    except OSError:
        print(f"Port {PORT} is busy. Starting on an automatically chosen free port.")
        app.launch(server_port=None, inbrowser=True, debug=False,
                   css=custom_css, favicon_path=favicon_path)

if __name__ == "__main__":
    main()