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
# 3. SYSTEM PROMPTS (ANTI-HALLUCINATION GUARDRAILS)
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


# Target languages shown in the UI as (label, code) pairs for CheckboxGroup.
# Only the *code* is stored in settings, passed to handlers, and used in filenames.
TARGET_LANGUAGES = [("Russian", "RU"), ("English", "EN"), ("Hebrew", "HE")]

# The default selected language *codes* (not labels).
TARGET_LANGUAGE_DEFAULTS = ["EN", "HE"]

# Stable-code-keyed markers for source-language detection from filenames.
TARGET_LANGUAGE_MARKERS = {
    "RU": {"ru", "rus", "russian", "русский"},
    "EN": {"en", "eng", "english"},
    "HE": {"he", "heb", "hebrew", "עברית"},
}

# Maps any known variant (display name, old label, code) → stable code.
# Used for migration of saved settings and as a fallback in translation.
TARGET_LANGUAGE_CODE_MAP = {
    # Stable codes → self
    "RU": "RU", "EN": "EN", "HE": "HE",
    # Display labels
    "Russian": "RU", "English": "EN", "Hebrew": "HE",
    # Old / legacy labels (the ones that crash the UI)
    "Русский": "RU", "русский": "RU",
    "עברית (Hebrew)": "HE", "עברית": "HE",
    # Two-letter codes
    "ru": "RU", "en": "EN", "he": "HE",
    "rus": "RU", "eng": "EN", "heb": "HE",
    # Other variants
    "иврит": "HE",
}

# Compatibility table for settings migration: old value → stable code.
_LANG_MIGRATION_TABLE = TARGET_LANGUAGE_CODE_MAP


# ==============================================================================
# 4. КАСТОМНЫЕ СТИЛИ (CSS) ДЛЯ ВЕБ-ИНТЕРФЕЙСА
# ==============================================================================
def sanitize_choice_value(value: str, valid_choices: list) -> str | None:
    """Return *value* if it appears in *valid_choices*, otherwise None.

    For CheckboxGroup/Dropdown/Radio, valid_choices may be a flat list of
    codes or a list of (label, code) tuples.  In the tuple case we match
    against the second element only (the actual value).
    """
    if not valid_choices:
        return None
    # Flat list of strings
    if isinstance(valid_choices[0], str):
        return value if value in valid_choices else None
    # List of (label, value) pairs
    for pair in valid_choices:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2 and pair[1] == value:
            return value
    return None
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
    padding-top: 3px !important;
    transition: background-color 0.3s ease, color 0.3s ease;
}

/* Single CSS class for all service buttons (CLEAR, + URL, + PLAYLIST, etc.) */
.service-btn {
    height: 44px !important;
    font-size: 10px !important;
    line-height: 1.1 !important;
    white-space: normal !important;
    text-align: center !important;
    padding: 2px 6px !important;
    border-radius: 8px !important;
    border: 1px solid var(--katav-accent) !important;
    background: linear-gradient(180deg, #7c2d12 0%, #9a3412 100%) !important;
    color: #fff !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.15), 0 2px 4px rgba(0,0,0,0.4) !important;
    text-transform: uppercase;
    font-weight: 600 !important;
    transition: all 0.2s ease !important;
}
.service-btn:hover {
    background: linear-gradient(180deg, #9a3412 0%, #c2410c 100%) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.25), 0 4px 8px rgba(0,0,0,0.5) !important;
    transform: translateY(-1px);
}
body.katav-light .service-btn {
    background: linear-gradient(180deg, #ddd6fe 0%, #c4b5fd 100%) !important;
    color: #4c1d95 !important;
    border-color: #8b5cf6 !important;
}
.gap-4 { gap: 8px !important; }
.p-4 { padding: 12px !important; }
.gradio-row { margin-bottom: 0px !important; }

.options-row { flex-wrap: wrap !important; overflow-x: hidden !important; }

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

/* ═══ LECTA-LIKE CARD STYLING (BE3) ═══ */
.katav-card {
    background: rgba(30, 41, 59, 0.6) !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    padding: 12px !important;
    margin-bottom: 10px !important;
}
body.katav-light .katav-card {
    background: rgba(248, 250, 252, 0.9) !important;
    border-color: #cbd5e1 !important;
}
.katav-card h3, .katav-card-header {
    color: #f8fafc !important;
    font-size: 14px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    margin: 0 0 8px 0 !important;
    border-bottom: 1px solid #334155 !important;
    padding-bottom: 6px !important;
}
body.katav-light .katav-card h3, body.katav-light .katav-card-header {
    color: #1e293b !important;
    border-bottom-color: #cbd5e1 !important;
}

/* Progress bar in card — full width, LECTA-style */
.katav-progress-bar {
    width: 100% !important;
    background-color: #0f172a !important;
    border-radius: 8px !important;
    overflow: hidden !important;
    height: 20px !important;
    box-shadow: inset 0 2px 4px rgba(0,0,0,0.5) !important;
    margin-bottom: 8px !important;
}
.katav-progress-fill {
    height: 100% !important;
    background: linear-gradient(90deg, #ea580c, #f97316) !important;
    transition: width 0.3s ease !important;
}

/* Metrics row — one line, monospace, emoji icons */
.katav-metrics-row {
    display: flex !important;
    justify-content: space-between !important;
    margin-top: 8px !important;
    color: #94a3b8 !important;
    font-family: 'Consolas', 'Courier New', monospace !important;
    font-size: 13px !important;
}

/* Multi-line text fields — prevent single-line scrollbar */
.katav-card textarea {
    min-height: 60px !important;
}

/* Accordion restyling as cards (BE3: keeps collapse, looks like card) */
.gr-accordion {
    background: rgba(30, 41, 59, 0.6) !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    margin-bottom: 10px !important;
}
body.katav-light .gr-accordion {
    background: rgba(248, 250, 252, 0.9) !important;
    border-color: #cbd5e1 !important;
}
.gr-accordion > .label-wrap {
    padding: 10px 12px !important;
}
.gr-accordion > .label-wrap > span:first-child {
    color: #f8fafc !important;
    font-size: 13px !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
}
body.katav-light .gr-accordion > .label-wrap > span:first-child {
    color: #1e293b !important;
}
:root,body,.gradio-container{--katav-bg:#1f2937;--katav-panel:rgba(30,41,59,.92);--katav-text:#e2e8f0;--katav-muted:#94a3b8;--katav-accent:#3b82f6;--katav-border:#475569}
body,.gradio-container{background-image:none !important}
.service-btn,.fixed-height-btn{border:1px solid #64748b !important;background:linear-gradient(180deg,#64748b 0%,#475569 100%) !important;color:#f8fafc !important}
.service-btn:hover,.fixed-height-btn:hover{background:linear-gradient(180deg,#94a3b8 0%,#64748b 100%) !important}
body.katav-light .service-btn,body.katav-light .fixed-height-btn{background:linear-gradient(180deg,#e2e8f0 0%,#cbd5e1 100%) !important;color:#1e293b !important;border-color:#94a3b8 !important}
.btn-primary,#start_btn,#start_full_btn{background:linear-gradient(180deg,#3b82f6 0%,#1d4ed8 100%) !important;border:1px solid #60a5fa !important;color:#fff !important}
.btn-primary:hover,#start_btn:hover,#start_full_btn:hover{background:linear-gradient(180deg,#60a5fa 0%,#2563eb 100%) !important}
.btn-save{background:linear-gradient(180deg,#0ea5e9 0%,#0369a1 100%) !important;border:1px solid #38bdf8 !important;color:#fff !important}
.btn-warning{background:linear-gradient(180deg,#f59e0b 0%,#b45309 100%) !important;border:1px solid #fbbf24 !important;color:#1f2937 !important}
.btn-danger,#stop_btn,#exit_btn{background:linear-gradient(180deg,#dc2626 0%,#991b1b 100%) !important;border:1px solid #ef4444 !important;color:#fff !important}
.btn-danger:hover,#stop_btn:hover,#exit_btn:hover{background:linear-gradient(180deg,#ef4444 0%,#b91c1c 100%) !important}
.btn-clear,.btn-danger-strong{background:linear-gradient(180deg,#f43f5e 0%,#9f1239 100%) !important;border:1px solid #fb7185 !important;color:#fff !important;font-weight:700 !important}
.btn-clear:hover,.btn-danger-strong:hover{background:linear-gradient(180deg,#fb7185 0%,#be123c 100%) !important}
.service-btn:focus-visible,.fixed-height-btn:focus-visible{outline:2px solid #93c5fd !important;outline-offset:2px !important}
.service-btn[disabled],.fixed-height-btn[disabled]{opacity:.45 !important;filter:grayscale(.6) !important;cursor:not-allowed !important}
.status-running{border:2px solid #3b82f6 !important;box-shadow:0 0 15px rgba(59,130,246,.5) !important}
.katav-progress-fill{background:linear-gradient(90deg,#3b82f6,#60a5fa) !important}

/* ===== KATAV v2 inline controls ===== */
.katav-inline-row{display:flex !important;align-items:center !important;gap:10px !important;flex-wrap:wrap !important;overflow:visible !important;margin-bottom:8px !important}
.katav-inline-row>*{overflow:visible !important;min-width:0 !important}
.katav-inline-row .fixed-height-btn{margin:0 !important}
.katav-switch{display:flex !important;align-items:center !important;min-height:48px !important;margin:0 !important;padding:0 14px !important;border:1px solid #475569 !important;border-radius:8px !important;background:linear-gradient(180deg,#334155 0%,#1e293b 100%) !important;box-shadow:inset 0 1px 0 rgba(255,255,255,.06),0 2px 4px rgba(0,0,0,.35) !important;transition:all .2s ease !important}
.katav-switch:hover{border-color:#94a3b8 !important;background:linear-gradient(180deg,#3f4d63 0%,#26334a 100%) !important}
.katav-switch label{display:flex !important;align-items:center !important;gap:10px !important;width:100% !important;margin:0 !important;padding:0 !important;border:0 !important;background:transparent !important;box-shadow:none !important;cursor:pointer !important}
.katav-switch label>span{font-size:11px !important;font-weight:600 !important;letter-spacing:.5px !important;text-transform:uppercase !important;color:#e2e8f0 !important;line-height:1.15 !important;white-space:nowrap !important;overflow:hidden !important;text-overflow:ellipsis !important}
.katav-switch input[type="checkbox"]{flex:0 0 18px !important;width:18px !important;height:18px !important;margin:0 !important;border-radius:5px !important;accent-color:#3b82f6 !important;cursor:pointer !important}
body.katav-light .katav-switch{background:linear-gradient(180deg,#f1f5f9 0%,#e2e8f0 100%) !important;border-color:#cbd5e1 !important}
body.katav-light .katav-switch label>span{color:#1e293b !important}
.katav-segmented{min-height:48px !important;display:flex !important;align-items:center !important;margin:0 !important;padding:0 !important;border:0 !important;background:transparent !important;box-shadow:none !important;overflow:visible !important}
.katav-segmented fieldset,.katav-segmented .wrap{display:flex !important;flex-direction:row !important;flex-wrap:nowrap !important;align-items:center !important;gap:8px !important;margin:0 !important;padding:0 !important;border:0 !important;background:transparent !important;overflow:visible !important}
.katav-segmented label{display:flex !important;align-items:center !important;gap:8px !important;min-height:44px !important;padding:0 16px !important;border:1px solid #475569 !important;border-radius:8px !important;background:linear-gradient(180deg,#334155 0%,#1e293b 100%) !important;font-size:11px !important;font-weight:600 !important;letter-spacing:.5px !important;text-transform:uppercase !important;color:#e2e8f0 !important;white-space:nowrap !important;cursor:pointer !important;transition:all .2s ease !important}
.katav-segmented label:hover{border-color:#93c5fd !important}
.katav-segmented label:has(input:checked){border-color:#3b82f6 !important;background:linear-gradient(180deg,#3b82f6 0%,#1d4ed8 100%) !important;color:#f8fafc !important;box-shadow:0 2px 8px rgba(59,130,246,.35) !important}
.katav-segmented input[type="radio"]{width:15px !important;height:15px !important;margin:0 !important;accent-color:#3b82f6 !important;cursor:pointer !important}
body.katav-light .katav-segmented label{background:linear-gradient(180deg,#f1f5f9 0%,#e2e8f0 100%) !important;border-color:#cbd5e1 !important;color:#1e293b !important}
#output_size_box{display:flex !important;align-items:center !important;min-height:48px !important}
#output_size_box textarea,#output_size_box input{height:48px !important;min-height:48px !important;padding:0 14px !important;border:1px solid #475569 !important;border-radius:8px !important;background:rgba(15,23,42,.55) !important;color:#cbd5e1 !important;font-size:11px !important;letter-spacing:.5px !important;text-transform:uppercase !important;text-align:center !important;resize:none !important;overflow:hidden !important}
body.katav-light #output_size_box textarea,body.katav-light #output_size_box input{background:#f8fafc !important;color:#334155 !important;border-color:#cbd5e1 !important}
*{scrollbar-width:thin;scrollbar-color:rgba(100,116,139,.55) transparent}
*::-webkit-scrollbar{width:10px;height:10px}
*::-webkit-scrollbar-track{background:transparent}
*::-webkit-scrollbar-thumb{background:rgba(100,116,139,.55);border-radius:999px;border:2px solid transparent;background-clip:content-box}
*::-webkit-scrollbar-thumb:hover{background:rgba(148,163,184,.85);background-clip:content-box}
*::-webkit-scrollbar-corner{background:transparent}
.katav-inline-row *::-webkit-scrollbar{display:none !important}

/* ===== KATAV v3 pastel production palette (single accent, low glare) ===== */
:root{--katav-accent:#7d9dc4 !important;--katav-border:#3d4859 !important}
.service-btn,.fixed-height-btn,button.lg,button.sm{background:linear-gradient(180deg,#2b3444 0%,#232b38 100%) !important;border:1px solid #3d4859 !important;color:#c3ccd9 !important;box-shadow:0 1px 2px rgba(0,0,0,.22) !important;text-shadow:none !important;font-weight:600 !important;letter-spacing:.4px !important}
.service-btn:hover,.fixed-height-btn:hover{background:linear-gradient(180deg,#333d4e 0%,#29323f 100%) !important;border-color:#4c586b !important;color:#dbe3ec !important}
.service-btn:active,.fixed-height-btn:active{transform:translateY(1px) !important;box-shadow:none !important}
.btn-primary,#start_btn,#start_full_btn{background:linear-gradient(180deg,#48678c 0%,#3c5675 100%) !important;border:1px solid #587aa1 !important;color:#e9f0f7 !important}
.btn-primary:hover,#start_btn:hover,#start_full_btn:hover{background:linear-gradient(180deg,#53749c 0%,#446184 100%) !important;border-color:#6b8cb2 !important}
.btn-save{background:linear-gradient(180deg,#47786f 0%,#3a625b 100%) !important;border:1px solid #588e84 !important;color:#e7f1ee !important}
.btn-save:hover{background:linear-gradient(180deg,#51867c 0%,#426e66 100%) !important}
.btn-warning{background:linear-gradient(180deg,#7d6a4c 0%,#645540 100%) !important;border:1px solid #96805f !important;color:#f2ece0 !important}
.btn-warning:hover{background:linear-gradient(180deg,#8b7757 0%,#6f5f48 100%) !important}
.btn-danger,#stop_btn,#exit_btn{background:linear-gradient(180deg,#83514e 0%,#68403e 100%) !important;border:1px solid #9c6663 !important;color:#f5eae9 !important}
.btn-danger:hover,#stop_btn:hover,#exit_btn:hover{background:linear-gradient(180deg,#915b58 0%,#754947 100%) !important}
.btn-clear,.btn-danger-strong{background:linear-gradient(180deg,#7f4a55 0%,#653a44 100%) !important;border:1px solid #98606c !important;color:#f5e9ec !important}
.btn-clear:hover,.btn-danger-strong:hover{background:linear-gradient(180deg,#8c535f 0%,#71424d 100%) !important}
.service-btn:focus-visible,.fixed-height-btn:focus-visible{outline:2px solid #7d9dc4 !important;outline-offset:2px !important}
.service-btn[disabled],.fixed-height-btn[disabled]{opacity:.4 !important;filter:grayscale(.7) !important;box-shadow:none !important}
.katav-progress-fill{background:linear-gradient(90deg,#4d6a8f,#7d9dc4) !important}
.katav-switch{background:linear-gradient(180deg,#2b3444 0%,#232b38 100%) !important;border-color:#3d4859 !important;box-shadow:0 1px 2px rgba(0,0,0,.22) !important}
.katav-switch:hover{background:linear-gradient(180deg,#333d4e 0%,#29323f 100%) !important;border-color:#4c586b !important}
.katav-switch label>span{color:#c3ccd9 !important}
.katav-switch input[type="checkbox"]{accent-color:#7d9dc4 !important}
.katav-segmented label{background:linear-gradient(180deg,#2b3444 0%,#232b38 100%) !important;border-color:#3d4859 !important;color:#c3ccd9 !important}
.katav-segmented label:hover{border-color:#4c586b !important}
.katav-segmented label:has(input:checked){background:linear-gradient(180deg,#48678c 0%,#3c5675 100%) !important;border-color:#587aa1 !important;color:#e9f0f7 !important;box-shadow:none !important}
.katav-segmented input[type="radio"]{accent-color:#7d9dc4 !important}
#output_size_box textarea,#output_size_box input{background:rgba(35,43,56,.7) !important;border-color:#3d4859 !important;color:#a9b6c7 !important}
input[type="checkbox"],input[type="radio"]{accent-color:#7d9dc4 !important}
body.katav-light .service-btn,body.katav-light .fixed-height-btn{background:linear-gradient(180deg,#f3f5f8 0%,#e6eaf0 100%) !important;border-color:#cfd7e2 !important;color:#41505f !important}
body.katav-light .service-btn:hover,body.katav-light .fixed-height-btn:hover{background:linear-gradient(180deg,#e9edf3 0%,#dbe1ea 100%) !important;border-color:#b9c5d4 !important}
body.katav-light .btn-primary,body.katav-light #start_btn,body.katav-light #start_full_btn{background:linear-gradient(180deg,#ccd9e9 0%,#b6c8de 100%) !important;border-color:#9db3cf !important;color:#26374a !important}
body.katav-light .btn-save{background:linear-gradient(180deg,#cbe0da 0%,#b1cdc5 100%) !important;border-color:#94b8ae !important;color:#22403a !important}
body.katav-light .btn-warning{background:linear-gradient(180deg,#eae0cb 0%,#dbcbab 100%) !important;border-color:#c4ae8b !important;color:#493d28 !important}
body.katav-light .btn-danger,body.katav-light #stop_btn,body.katav-light #exit_btn{background:linear-gradient(180deg,#eed2d0 0%,#dcb9b6 100%) !important;border-color:#c69d9a !important;color:#4a2f2d !important}
body.katav-light .btn-clear,body.katav-light .btn-danger-strong{background:linear-gradient(180deg,#eccdd3 0%,#d9aeb7 100%) !important;border-color:#c3939d !important;color:#4a2b33 !important}
body.katav-light .katav-switch{background:linear-gradient(180deg,#f3f5f8 0%,#e6eaf0 100%) !important;border-color:#cfd7e2 !important}
body.katav-light .katav-switch label>span{color:#41505f !important}
body.katav-light .katav-segmented label{background:linear-gradient(180deg,#f3f5f8 0%,#e6eaf0 100%) !important;border-color:#cfd7e2 !important;color:#41505f !important}
body.katav-light .katav-segmented label:has(input:checked){background:linear-gradient(180deg,#ccd9e9 0%,#b6c8de 100%) !important;border-color:#9db3cf !important;color:#26374a !important}
body.katav-light #output_size_box textarea,body.katav-light #output_size_box input{background:#f7f9fb !important;border-color:#cfd7e2 !important;color:#4b5a6b !important}

/* ===== KATAV v4: CLEAR emphasis (destructive action) ===== */
.btn-clear,.btn-danger-strong{background:linear-gradient(180deg,#93555f 0%,#75414c 100%) !important;border:1px solid #c98c98 !important;color:#fdf2f4 !important;box-shadow:0 0 0 1px rgba(201,140,152,.25),0 2px 6px rgba(0,0,0,.3) !important;font-weight:700 !important;letter-spacing:.8px !important}
.btn-clear:hover,.btn-danger-strong:hover{background:linear-gradient(180deg,#a3616c 0%,#834a56 100%) !important;border-color:#dda3ae !important;box-shadow:0 0 0 2px rgba(221,163,174,.28),0 3px 8px rgba(0,0,0,.35) !important}
.btn-clear:active,.btn-danger-strong:active{transform:translateY(1px) !important}
.btn-clear:focus-visible,.btn-danger-strong:focus-visible{outline:2px solid #dda3ae !important;outline-offset:2px !important}
body.katav-light .btn-clear,body.katav-light .btn-danger-strong{background:linear-gradient(180deg,#f0cdd4 0%,#deacb6 100%) !important;border-color:#c07f8d !important;color:#43222a !important;box-shadow:0 0 0 1px rgba(192,127,141,.3) !important}

/* ===== KATAV v5: START and CLEAR share one exact palette by ID ===== */
#start_btn,#start_full_btn,#clear_media_btn,#clear_trans_files_btn,.btn-clear,.btn-danger-strong{background:linear-gradient(180deg,#48678c 0%,#3c5675 100%) !important;border:1px solid #587aa1 !important;color:#e9f0f7 !important;text-shadow:0 1px 2px rgba(0,0,0,.5) !important;box-shadow:inset 0 1px 0 rgba(255,255,255,.2),inset 0 0 10px rgba(0,0,0,.2),0 3px 6px rgba(0,0,0,.4) !important;font-weight:600 !important;letter-spacing:.4px !important}
#start_btn:hover,#start_full_btn:hover,#clear_media_btn:hover,#clear_trans_files_btn:hover,.btn-clear:hover,.btn-danger-strong:hover{background:linear-gradient(180deg,#53749c 0%,#446184 100%) !important;border-color:#6b8cb2 !important;color:#e9f0f7 !important;box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 5px 10px rgba(234,88,12,.4) !important;transform:translateY(-1px) !important}
#start_btn:active,#start_full_btn:active,#clear_media_btn:active,#clear_trans_files_btn:active,.btn-clear:active,.btn-danger-strong:active{transform:translateY(1px) !important;box-shadow:none !important}
#start_btn:focus-visible,#start_full_btn:focus-visible,#clear_media_btn:focus-visible,#clear_trans_files_btn:focus-visible,.btn-clear:focus-visible,.btn-danger-strong:focus-visible{outline:2px solid #7d9dc4 !important;outline-offset:2px !important}
body.katav-light #start_btn,body.katav-light #start_full_btn,body.katav-light #clear_media_btn,body.katav-light #clear_trans_files_btn,body.katav-light .btn-clear,body.katav-light .btn-danger-strong{background:linear-gradient(180deg,#ccd9e9 0%,#b6c8de 100%) !important;border-color:#9db3cf !important;color:#26374a !important}
body.katav-light #start_btn:hover,body.katav-light #start_full_btn:hover,body.katav-light #clear_media_btn:hover,body.katav-light #clear_trans_files_btn:hover,body.katav-light .btn-clear:hover,body.katav-light .btn-danger-strong:hover{background:linear-gradient(180deg,#ccd9e9 0%,#b6c8de 100%) !important;border-color:#9db3cf !important;color:#26374a !important}
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

# ==============================================================================
# 7b. CUSTOM AI PROVIDERS (OpenAI-compatible, managed from the UI)
# ==============================================================================
import os as _os_cp
import json as _json_cp

CUSTOM_PROVIDERS_FILE = _os_cp.path.join(_os_cp.path.dirname(_os_cp.path.abspath(__file__)), "custom_providers.json")


def load_custom_providers() -> dict:
    try:
        if _os_cp.path.exists(CUSTOM_PROVIDERS_FILE):
            with open(CUSTOM_PROVIDERS_FILE, "r", encoding="utf-8") as fh:
                data = _json_cp.load(fh)
            if isinstance(data, dict):
                return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def custom_provider_names() -> list:
    return sorted(load_custom_providers().keys())


def get_custom_provider(name):
    key = str(name or "").strip()
    if not key:
        return None
    return load_custom_providers().get(key)


def save_custom_provider(name, base_url, api_key="", models=None) -> dict:
    key = str(name or "").strip()
    url = str(base_url or "").strip().rstrip("/")
    if not key:
        raise ValueError("Provider name is required.")
    if not url:
        raise ValueError("Base URL is required, for example http://127.0.0.1:1234/v1")
    data = load_custom_providers()
    existing = data.get(key, {})
    data[key] = {
        "base_url": url,
        "api_key": api_key if api_key else existing.get("api_key", ""),
        "models": list(models) if models else existing.get("models", []),
    }
    with open(CUSTOM_PROVIDERS_FILE, "w", encoding="utf-8") as fh:
        _json_cp.dump(data, fh, indent=4, ensure_ascii=False)
    return data[key]


def delete_custom_provider(name) -> bool:
    key = str(name or "").strip()
    data = load_custom_providers()
    if key not in data:
        return False
    data.pop(key, None)
    with open(CUSTOM_PROVIDERS_FILE, "w", encoding="utf-8") as fh:
        _json_cp.dump(data, fh, indent=4, ensure_ascii=False)
    return True
