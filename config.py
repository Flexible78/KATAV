import os
import json
from pathlib import Path

# ==============================================================================
# 2. КОНСТАНТЫ И ПУТИ ФАЙЛОВОЙ СИСТЕМЫ
# ==============================================================================
PORT = 7861


def _settings_whisper_exe() -> str:
    """Read the Whisper executable path from the local whisper_settings.json if present."""
    try:
        f = Path(__file__).resolve().parent / "whisper_settings.json"
        if f.is_file():
            return json.loads(f.read_text(encoding="utf-8")).get("whisper_exe", "") or ""
    except Exception:
        pass
    return ""


def _autodiscover_whisper_exe() -> str:
    """Search for faster-whisper-xxl.exe in the project directory and its parent."""
    here = Path(__file__).resolve().parent
    for base in (here, here.parent):
        try:
            for p in base.rglob("faster-whisper-xxl.exe"):
                return str(p)
        except (PermissionError, OSError):
            continue
    return ""


WHISPER_EXE = (
    os.getenv("WHISPER_EXE", "")
    or _settings_whisper_exe()
    or _autodiscover_whisper_exe()
)

WHISPER_EXE_HINT = (
    "faster-whisper-xxl.exe was not found.\n"
    "Set it in one of these ways:\n"
    "  1) environment variable WHISPER_EXE\n"
    "  2) whisper_settings.json -> \"whisper_exe\"\n"
    "  3) place the Faster-Whisper-XXL folder next to the app"
)

DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Outputs")

# Windows process priority for faster-whisper-xxl.exe: "normal", "below_normal", or "idle"
WHISPER_PROCESS_PRIORITY = "below_normal"

# CPU thread cap: default = half the logical cores, minimum 1
import os as _os
WHISPER_MAX_THREADS = max(1, (_os.cpu_count() or 4) // 2)

# Pause between batch files for hardware cooldown (0 = off)
WHISPER_COOLDOWN_SEC = 20

# Optional GPU power limit in watts (e.g. 120); None = do nothing. Requires nvidia-smi + admin rights.
WHISPER_GPU_POWER_LIMIT_W = None

CONFIG_FILE = "whisper_api_keys.json"
SETTINGS_FILE = "whisper_settings.json"

# ==============================================================================
# 3. ПРОМПТЫ НЕЙРОСЕТЕЙ (ЗАЩИТА ОТ ГАЛЛЮЦИНАЦИЙ)
# ==============================================================================
DEFAULT_SYSTEM_PROMPT = (
    "You are a professional subtitle translator. Your only task is to translate the provided text into the requested language.\n\n"
    "STRICT RULES (CRITICALLY IMPORTANT):\n"
    "1. Respond STRICTLY in SRT format. NEVER use lists, bullets, or asterisks (*).\n"
    "2. NEVER write comments, thoughts, introductory, or concluding phrases.\n"
    "3. NEVER leave the original text. Write only the translation.\n"
    "4. PRESERVE original sequence numbers and timecodes unchanged.\n"
    "5. Do not merge blocks. Return exactly as many blocks as you received.\n\n"
    "EXAMPLE OF YOUR RESPONSE:\n"
    "1\n"
    "00:00:19,560 --> 00:00:21,570\n"
    "Only translated text goes here"
)

GEMMA_SYSTEM_PROMPT = f"disable reasoning and thought. </thought off>.\n{DEFAULT_SYSTEM_PROMPT}"


# Target languages shown in the UI and their matching metadata.
TARGET_LANGUAGES = ["Russian", "English", "Hebrew"]
TARGET_LANGUAGE_DEFAULTS = ["English", "Hebrew"]
TARGET_LANGUAGE_MARKERS = {
    "Russian": {"ru", "rus", "russian", "русский"},
    "English": {"en", "eng", "english"},
    "Hebrew": {"he", "heb", "hebrew", "עברית"},
}
TARGET_LANGUAGE_CODE_MAP = {
    "Russian": "RU",
    "English": "EN",
    "Hebrew": "HE",
}


# ==============================================================================
# 4. КАСТОМНЫЕ СТИЛИ (CSS) ДЛЯ ВЕБ-ИНТЕРФЕЙСА
# ==============================================================================
custom_css = """
:root {
    --katav-bg: #2d2d30;
    --katav-panel: rgba(30, 30, 32, 0.9);
    --katav-text: #e4e4e7;
    --katav-muted: #71717a;
    --katav-accent: #ea580c;
    --katav-border: #52525b;
}

body.katav-light, body.katav-light .gradio-container {
    --katav-bg: #f4f4f5;
    --katav-panel: rgba(255, 255, 255, 0.95);
    --katav-text: #18181b;
    --katav-muted: #52525b;
    --katav-accent: #c2410c;
    --katav-border: #d4d4d8;
}

body, .gradio-container {
    background-color: var(--katav-bg) !important;
    background-image: repeating-linear-gradient(90deg, rgba(0,0,0,0.05) 0px, rgba(0,0,0,0.05) 2px, transparent 2px, transparent 4px) !important;
    color: var(--katav-text) !important;
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif !important;
    max-width: 98% !important;
    padding: 10px !important;
    transition: background-color 0.3s ease, color 0.3s ease;
}
.gap-4 { gap: 8px !important; }
.p-4 { padding: 12px !important; }
.gradio-row { margin-bottom: 0px !important; }

.micro-title {
    text-align: right !important;
    font-size: 11px !important;
    color: var(--katav-muted) !important;
    margin-bottom: -15px !important;
    margin-top: -5px !important;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.fixed-height-btn {
    height: 48px !important;
    font-size: 11px !important;
    line-height: 1.1 !important;
    white-space: normal !important;
    text-align: center !important;
    padding: 2px 5px !important;
    border-radius: 8px !important;
    border: 1px solid var(--katav-border) !important;
    background: linear-gradient(180deg, #3f3f46 0%, #1e293b 100%) !important;
    color: #f8fafc !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), 0 2px 4px rgba(0,0,0,0.4) !important;
    text-transform: uppercase;
    font-weight: 600 !important;
    transition: all 0.2s ease !important;
}
body.katav-light .fixed-height-btn {
    background: linear-gradient(180deg, #f4f4f5 0%, #e4e4e7 100%) !important;
    color: #18181b !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.8), 0 2px 4px rgba(0,0,0,0.1) !important;
}
.fixed-height-btn:hover {
    transform: translateY(-1px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.2), 0 4px 8px rgba(0,0,0,0.5) !important;
    background: linear-gradient(180deg, #4b5563 0%, #334155 100%) !important;
}
body.katav-light .fixed-height-btn:hover {
    background: linear-gradient(180deg, #ffffff 0%, #d4d4d8 100%) !important;
}

#start_btn, #start_full_btn {
    background: linear-gradient(180deg, #c2410c 0%, #9a3412 100%) !important;
    border: 1px solid var(--katav-accent) !important;
    color: #fff !important;
    text-shadow: 0 1px 2px rgba(0,0,0,0.5);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.2), inset 0 0 10px rgba(0,0,0,0.2), 0 3px 6px rgba(0,0,0,0.4) !important;
}
#start_btn:hover, #start_full_btn:hover {
    background: linear-gradient(180deg, #ea580c 0%, #c2410c 100%) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.3), 0 5px 10px rgba(234, 88, 12, 0.4) !important;
}

#stop_btn, #exit_btn {
    background: linear-gradient(180deg, #4c1d95 0%, #312e81 100%) !important;
    border: 1px solid #6d28d9 !important;
}
body.katav-light #stop_btn, body.katav-light #exit_btn {
    background: linear-gradient(180deg, #7c3aed 0%, #5b21b6 100%) !important;
    color: #fff !important;
}
#stop_btn:hover, #exit_btn:hover {
    background: linear-gradient(180deg, #5b21b6 0%, #3730a3 100%) !important;
}

.translate-box, .file-manager {
    background-color: var(--katav-panel) !important;
    background-image: repeating-linear-gradient(90deg, rgba(255,255,255,0.01) 0px, rgba(255,255,255,0.01) 2px, transparent 2px, transparent 4px) !important;
    border: 1px solid var(--katav-border) !important;
    border-radius: 12px !important;
    padding: 15px !important;
    box-shadow: inset 0 0 20px rgba(0,0,0,0.3), 0 4px 10px rgba(0,0,0,0.2) !important;
    margin-bottom: 5px !important;
}
body.katav-light .translate-box, body.katav-light .file-manager {
    box-shadow: inset 0 0 20px rgba(0,0,0,0.05), 0 4px 10px rgba(0,0,0,0.1) !important;
}

.big-text textarea {
    background: rgba(15, 15, 15, 0.6) !important;
    border: 1px solid var(--katav-border) !important;
    color: var(--katav-text) !important;
    font-size: 15px !important;
    border-radius: 8px !important;
}
body.katav-light .big-text textarea {
    background: rgba(255, 255, 255, 0.9) !important;
    color: #18181b !important;
}

.status-running { border: 2px solid var(--katav-accent) !important; box-shadow: 0 0 15px rgba(234, 88, 12, 0.5) !important; }
.status-done { border: 2px solid #10b981 !important; box-shadow: 0 0 15px rgba(16, 185, 129, 0.3) !important; }
.status-error { border: 2px solid #e11d48 !important; box-shadow: 0 0 15px rgba(225, 29, 72, 0.3) !important; }

#log_group .wrap {
    background: rgba(15, 15, 15, 0.6) !important;
    border: 1px solid var(--katav-border) !important;
}
body.katav-light #log_group .wrap {
    background: rgba(255, 255, 255, 0.9) !important;
    color: #18181b !important;
}
"""

# ==============================================================================
# 6. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ УПРАВЛЕНИЯ (ТОЛЬКО СПИСКИ МОДЕЛЕЙ)
# ==============================================================================
GOOGLE_STUDIO_MODELS = [
    "models/gemma-4-31b-it", 
    "models/gemma-4-26b-a4b-it", 
    "models/gemini-3.1-pro-preview", 
    "models/gemini-3-flash-preview",
    "models/gemini-2.5-pro",
    "models/deep-research-max-preview-04-2026"
]

GEMINI_MODELS = [
    "models/gemini-3.1-pro-preview", 
    "models/gemini-3-flash-preview", 
    "models/gemini-2.5-flash", 
    "models/gemini-2.5-pro",
    "models/gemma-4-31b-it"
]

LOCAL_PROXY_MODELS = [
    "models/gemma-4-31b-it", 
    "models/gemma-4-26b-a4b-it",
    "models/gemini-3.1-pro-preview", 
    "models/gemini-3-flash-preview", 
    "models/gemini-2.5-pro",
    "models/gemini-2.5-flash"
]

OPENROUTER_MODELS = [
    "arcee-ai/trinity-large-thinking:free",
    "baidu/cobuddy:free",
    "baidu/qianfan-ocr-fast:free",
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "google/lyria-3-clip-preview",
    "google/lyria-3-pro-preview",
    "inclusionai/ring-2.6-1t:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "liquid/lfm-2.5-1.2b-thinking:free",
    "minimax/minimax-m2.5:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "openrouter/free",
    "openrouter/owl-alpha",
    "poolside/laguna-m.1:free",
    "poolside/laguna-xs.2:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "z-ai/glm-4.5-air:free"
]

# ==============================================================================
# 7. НОВЫЕ AI-ПРОВАЙДЕРЫ (OpenAI-совместимые)
# ==============================================================================
# OmniRoute (порт 20128 — подтверждён ATS Checker 3.3 + curl /v1/models и /v1/chat/completions)
OMNIROUTE_BASE_URL = "http://127.0.0.1:20128/v1"
# Freeway (порт 8787 — отвечает на /v1/models, подтверждён curl-ом)
FREEWAY_BASE_URL = "http://127.0.0.1:8787/v1"
FREEWAY_DEFAULT_KEY = "123"  # ключ по умолчанию для Freeway
# Mistral (облачный, OpenAI-совместимый)
MISTRAL_BASE_URL = "https://api.mistral.ai/v1"

OMNIROUTE_MODELS = []   # заполнится «подкачкой моделей» (C3)
FREEWAY_MODELS = []     # заполнится «подкачкой моделей» (C3)
MISTRAL_MODELS = [
    "mistral-large-latest",
    "mistral-small-latest",
    "open-mistral-nemo"
]