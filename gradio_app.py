import gradio as gr
import webbrowser
import os
import re
import json
import subprocess
import sys
from typing import List, Any

# Импорты из других модулей
from config import (
    DEFAULT_OUTPUT_DIR, GOOGLE_STUDIO_MODELS, 
    LOCAL_PROXY_MODELS, OPENROUTER_MODELS, OMNIROUTE_MODELS, FREEWAY_MODELS, MISTRAL_MODELS,
    DEFAULT_SYSTEM_PROMPT, GEMMA_SYSTEM_PROMPT, CONFIG_FILE, custom_css
)
from ui_manager import ui_state
from utils import (
    log_to_terminal, stop_all_processes, restart_app, kill_program,
    log_queue
)
# Оставляем только старые безопасные функции из dialogs
from dialogs import (
    read_clipboard_paths, open_folder_dialog, open_files_batch_dialog,
    open_dir_batch_dialog, open_srt_batch_dialog, open_dir_srt_dialog,
    save_edited_text_dialog
)
from file_operations import list_files, delete_selected, delete_all
from whisper_core import run_transcription
from srt_processor import export_to_json_dict

from ai_translator import translate_content, check_api, fetch_models
import utils 

GROQ_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-safeguard-20b",
    "llama3-70b-8192",
    "mixtral-8x7b-32768"
]

def load_keys_safe() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: return {}
    return {}

current_action = "Waiting..."
current_percent = 0
current_file_action = ""
current_file_percent = 0
time_elapsed = "00:00"
time_remaining = "00:00"
audio_speed = "0.00x"
full_whisper_log = ""

def get_model_choices(models_config):
    if isinstance(models_config, dict): return [v[0] for k, v in models_config.items()]
    elif isinstance(models_config, list):
        if len(models_config) > 0 and isinstance(models_config[0], tuple): return [v[0] for v in models_config]
        return models_config
    return []

def prepare_start():
    utils.stop_requested = False
    return gr.update(elem_classes=["status-running"])

def eco_preset():
    """turbo model + int8 + beam_size=1 (greedy) drastically reduce GPU/CPU work
    vs large-v2 + float16 + beam 5, which is the main heat source."""
    # Use large-v3-turbo if available, else fallback to "turbo"
    eco_model = "large-v3-turbo"
    return (
        gr.update(value=eco_model),       # model_size
        gr.update(value="int8"),           # compute_type
        gr.update(value=1),                # beam_size
        gr.update(value=False),            # condition_on_prev
        gr.update(value=True),             # use_vad_filter
    )

def process_logs(current_log: str):
    global current_percent, time_elapsed, time_remaining, audio_speed, full_whisper_log, current_action
    global current_file_percent, current_file_action
    
    new_text = current_log or ""
    lines_added = False
    
    try:
        while not log_queue.empty():
            line = log_queue.get()
            
            match_w = re.search(r'(\d+)%\s*\|\s*\d+/\d+\s*\|\s*(\d{2}:\d{2})<<?(\d{2}:\d{2})\s*\|\s*([\d.]+)', line)
            if match_w:
                current_percent = int(match_w.group(1))
                time_elapsed = match_w.group(2)
                time_remaining = match_w.group(3)
                audio_speed = f"{match_w.group(4)}x"
                current_action = "Transcription"
                
            match_t = re.search(r'\[PROGRESS_TRANS\] \| (\d+) \| (\d+) \| (\d+)', line)
            if match_t:
                req_done = int(match_t.group(1))
                req_total = int(match_t.group(2))
                e_sec = int(match_t.group(3))
                
                current_action = f"AI Translation ({req_done}/{req_total})"
                current_percent = int((req_done / req_total) * 100) if req_total > 0 else 100
                time_elapsed = f"{e_sec//60:02d}:{e_sec%60:02d}"
                r_sec = int((e_sec / req_done) * (req_total - req_done)) if req_done > 0 else 0
                time_remaining = f"{r_sec//60:02d}:{r_sec%60:02d}"
                audio_speed = "API"
                continue

            match_f = re.search(r'\[PROGRESS_FILE\] \| (\d+) \| (\d+)', line)
            if match_f:
                f_done = int(match_f.group(1))
                f_total = int(match_f.group(2))
                current_file_action = f"FILE ({f_done}/{f_total})"
                current_file_percent = int((f_done / f_total) * 100) if f_total > 0 else 100
                continue

            new_text += line
            full_whisper_log += line 
            lines_added = True
    except Exception: pass 
            
    if lines_added:
        lines = new_text.split('\n')
        if len(lines) > 15: new_text = '\n'.join(lines[-15:])

    file_progress_html = ""
    if current_file_action:
        file_progress_html = f"""
        <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #3f3f46;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 5px; font-weight: bold; font-size: 13px; color: #a1a1aa; text-transform: uppercase;">
                <span>{current_file_action}</span><span style="color: #3b82f6;">{current_file_percent}%</span>
            </div>
            <div style="width: 100%; background-color: #18181b; border-radius: 4px; overflow: hidden; height: 12px; border: 1px solid #27272a;">
                <div style="width: {current_file_percent}%; height: 100%; background: linear-gradient(90deg, #1d4ed8, #3b82f6); transition: width 0.3s ease;"></div>
            </div>
        </div>
        """

    metrics_html = f"""
    <div style="background: rgba(30, 30, 32, 0.9); padding: 15px; border-radius: 12px; border: 1px solid #52525b; margin-bottom: 10px; box-shadow: inset 0 2px 10px rgba(0,0,0,0.5);">
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
        {file_progress_html}
    </div>
    """
    return new_text, metrics_html


# ==============================================================================
# 🚀 НОВЫЕ БРОНЕБОЙНЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С ФАЙЛАМИ СУБТИТРОВ
# ==============================================================================
def smart_copy_srt(hidden_paths: str, manual_path: str):
    """Копирует ФАЙЛЫ как объекты в буфер обмена Windows (Ctrl+C)"""
    paths_to_use = hidden_paths if (hidden_paths and hidden_paths.strip()) else manual_path
    if not paths_to_use: return "⚠️ No SRT files! Specify a path in the field or run a translation."
    
    paths = [p.strip().strip('"').strip("'") for p in paths_to_use.split('|') if p.strip() and os.path.exists(p.strip().strip('"').strip("'"))]
    if not paths: return "⚠️ Files not found on disk!"
    
    try:
        CREATE_NO_WINDOW = 0x08000000
        # Оборачиваем каждый путь в одинарные кавычки для PowerShell
        ps_paths = ",".join([f"'{os.path.abspath(p)}'" for p in paths])
        # Команда PowerShell, которая помещает ФАЙЛ в буфер обмена
        cmd = f"Set-Clipboard -Path {ps_paths}"
        subprocess.run(["powershell", "-command", cmd], creationflags=CREATE_NO_WINDOW)
        return f"📋 Copied {len(paths)} files as objects. (Press Ctrl+V in the target Windows folder!)"
    except Exception as e:
        return f"❌ File copy error: {e}"

def smart_save_srt(hidden_paths: str, manual_path: str, actual_out_dir: str):
    """Вызывает системное окно сохранения ФАЙЛА"""
    paths_to_use = hidden_paths if (hidden_paths and hidden_paths.strip()) else manual_path
    if not paths_to_use: return "⚠️ No SRT files to save!"
    
    paths = [p.strip().strip('"').strip("'") for p in paths_to_use.split('|') if p.strip() and os.path.exists(p.strip().strip('"').strip("'"))]
    if not paths: return "⚠️ Files not found on disk!"
    
    path = paths[0]
    b_name = os.path.splitext(os.path.basename(path))[0]
    initial_dir = actual_out_dir.replace('\\', '/') if actual_out_dir else os.path.expanduser("~").replace('\\', '/')
    
    # Изолированный запуск Tkinter (чтобы не вешать Gradio)
    code = f'''
import os, shutil
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
res = filedialog.asksaveasfilename(title="Save SRT file as...", initialdir="{initial_dir}", initialfile="{b_name}.srt", defaultextension=".srt", filetypes=[("Subtitles", "*.srt"), ("All files", "*.*")])
if res:
    shutil.copy2(r"{os.path.abspath(path)}", res)
    print(res)
else:
    print("")
'''
    try:
        CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True, creationflags=CREATE_NO_WINDOW, timeout=120)
        saved_path = result.stdout.strip()
        if saved_path: return f"✅ SRT saved successfully: {saved_path}"
        return "⚠️ Save cancelled."
    except Exception as e:
        return f"❌ Save dialog error: {e}"


def build_app():
    saved_keys = load_keys_safe()
    
    with gr.Blocks(title="AT Whisper ULTIMATE") as app:
        hidden_base_name = gr.State("") 
        hidden_actual_out_dir = gr.State("") 
        hidden_srt_paths = gr.State("")
        hidden_dl_files = gr.State([]) 
        
        gr.Markdown("<div class='micro-title'>🎙️ AT Whisper ULTIMATE + AI Translator</div>")
        
        with gr.Row():
            # ==================== ЛЕВАЯ КОЛОНКА ====================
            with gr.Column(scale=5):
                gr.Markdown("### 📁 MEDIA FILES")
                
                urls_input = gr.Textbox(
                    label="🌐 URLS (YouTube, VK, TikTok)", 
                    value=ui_state.get("whisper_urls", ""),
                    placeholder="https://youtube.com/watch?v=...",
                    lines=1
                )
                
                with gr.Row(elem_classes=["uniform-row"]):
                    manual_path = gr.Textbox(
                        label="📂 FILE / FOLDER PATH", 
                        value=ui_state.get("whisper_manual_path", ""), 
                        scale=5
                    )
                    clear_media_btn = gr.Button("🗑️ CLEAR", variant="secondary", elem_classes=["fixed-height-btn"], scale=1, min_width=40)
                    paste_btn = gr.Button("📋 PASTE", variant="secondary", elem_classes=["fixed-height-btn"], scale=1, min_width=40)
                    file_btn = gr.Button("📄 FILE", variant="secondary", elem_classes=["fixed-height-btn"], scale=1, min_width=40)
                    folder_batch_btn = gr.Button("📂 DIR", variant="secondary", elem_classes=["fixed-height-btn"], scale=1, min_width=40)
                
                input_file = gr.File(
                    label="OR DRAG & DROP FILES HERE", 
                    file_types=["audio", "video"], 
                    file_count="multiple"
                )
                
                with gr.Accordion("📌 OUTPUT DIRECTORY", open=False):
                    use_custom_output = gr.Checkbox(
                        label="USE CUSTOM OUTPUT DIR", 
                        value=ui_state.get("whisper_use_custom_output", False)
                    )
                    with gr.Row(elem_classes=["uniform-row"]):
                        output_folder = gr.Textbox(
                            label="PATH", 
                            value=ui_state.get("whisper_output_dir", DEFAULT_OUTPUT_DIR), 
                            scale=4
                        )
                        folder_btn = gr.Button("📂 BROWSE", variant="secondary", elem_classes=["fixed-height-btn"], scale=1, min_width=40)

                gr.Markdown("### ⚙️ WHISPER SETTINGS")
                
                with gr.Row():
                    language = gr.Dropdown(choices=["auto", "he", "ru", "en"], value=ui_state.get("whisper_language", "auto"), label="🌐 LANGUAGE")
                    vad_method = gr.Dropdown(choices=["pyannote_v3", "silero_v3", "Без VAD"], value=ui_state.get("whisper_vad", "pyannote_v3"), label="✂️ VAD")
                with gr.Row():
                    model_size = gr.Dropdown(choices=["large-v2", "large-v3", "large-v3-turbo", "turbo", "medium"], value=ui_state.get("whisper_model", "large-v2"), label="🧠 MODEL")
                    compute_type = gr.Dropdown(choices=["float16", "int8", "float32"], value=ui_state.get("whisper_compute", "float16"), label="⚡ COMPUTE")
                with gr.Row():
                    eco_btn = gr.Button("🌿 ECO (quiet/cool)", elem_classes=["fixed-height-btn"])
                
                with gr.Accordion("🛠 ADVANCED SETTINGS", open=False):
                    initial_prompt = gr.Textbox(label="📝 CONTEXT (-prompt)", value=ui_state.get("whisper_prompt", "auto"))
                    hotwords = gr.Textbox(label="🔥 HOTWORDS (--hotwords)", value=ui_state.get("whisper_hotwords", ""))
                    temperature = gr.Slider(minimum=0.0, maximum=1.0, step=0.1, value=ui_state.get("whisper_temp", 0.0), label="TEMPERATURE")
                    rep_penalty = gr.Slider(minimum=1.0, maximum=2.0, step=0.1, value=ui_state.get("whisper_rep", 1.0), label="REP PENALTY")
                    beam_size = gr.Slider(minimum=1, maximum=10, step=1, value=ui_state.get("whisper_beam", 5), label="BEAM SIZE")
                    patience = gr.Slider(minimum=0.0, maximum=2.0, step=0.1, value=ui_state.get("whisper_patience", 1.0), label="PATIENCE")
                    condition_on_prev = gr.Checkbox(label="COND ON PREV TEXT", value=ui_state.get("whisper_cond", True))
                    no_speech_thresh = gr.Slider(minimum=0.0, maximum=1.0, step=0.1, value=ui_state.get("whisper_nospeech", 0.6), label="NO SPEECH THRESH")

                with gr.Row():
                    output_formats = gr.CheckboxGroup(choices=["srt", "vtt", "txt", "json"], value=["srt"], label="FORMATS")
                with gr.Row():
                    save_audio_track = gr.Checkbox(label="💾 SAVE AUDIO TRACK (MP3)", value=False, elem_id="save_audio_track")
                with gr.Row():
                    use_sentence = gr.Checkbox(label="BY SENTENCES", value=ui_state.get("whisper_sentence", True))
                    use_print_progress = gr.Checkbox(label="PROGRESS BAR", value=ui_state.get("whisper_progress", True))
                    use_vad_filter = gr.Checkbox(label="VAD FILTER", value=ui_state.get("whisper_vadfilter", True))
                    use_beep_off = gr.Checkbox(label="DISABLE BEEPS", value=ui_state.get("whisper_beep", True))

                with gr.Row():
                    start_btn = gr.Button("🚀 START (SUBS ONLY)", variant="primary", elem_id="start_btn", elem_classes=["fixed-height-btn"])
                    start_full_btn = gr.Button("🔥 FULL CYCLE (SUBS+TRANS)", variant="primary", elem_id="start_full_btn", elem_classes=["fixed-height-btn"])
                    pause_btn = gr.Button("⏸ PAUSE", variant="secondary", elem_classes=["fixed-height-btn"])
                    stop_btn = gr.Button("🛑 STOP", variant="stop", elem_id="stop_btn", elem_classes=["fixed-height-btn"])
                    restart_btn = gr.Button("🔄 RELOAD UI", variant="secondary", elem_classes=["fixed-height-btn"], min_width=40)
                    exit_btn = gr.Button("🚪 EXIT", variant="secondary", elem_id="exit_btn", elem_classes=["fixed-height-btn"], min_width=40)
                
                with gr.Accordion("🗑️ CLEAN OUTPUT DIRECTORY", open=False):
                    with gr.Row(elem_classes=["file-manager"]):
                        with gr.Column(scale=3):
                            files_to_delete = gr.CheckboxGroup(choices=[], label="SELECT FILES TO DELETE")
                        with gr.Column(scale=1):
                            refresh_files_btn = gr.Button("🔄 SHOW", size="sm", elem_classes=["fixed-height-btn"])
                            del_selected_btn = gr.Button("🗑 DELETE", size="sm", variant="secondary", elem_classes=["fixed-height-btn"])
                            del_all_btn = gr.Button("💣 ALL", size="sm", variant="stop", elem_classes=["fixed-height-btn"])
                            del_status = gr.Markdown("")
                
            # ==================== ПРАВАЯ КОЛОНКА ====================
            with gr.Column(scale=4):
                metrics_panel = gr.HTML(value="<div style='background: rgba(30, 41, 59, 0.8); padding: 15px; border-radius: 12px;'><h3 style='color: white;'>Waiting...</h3></div>")
                
                with gr.Group(elem_id="log_group") as log_box:
                    output_log = gr.Textbox(label="LIVE LOG", lines=4, max_lines=4, elem_classes=["big-text"], value="")
                
                with gr.Column(elem_classes=["translate-box"]):
                    gr.Markdown("### 🤖 AI TRANSLATOR")
                    
                    api_provider_val = ui_state.get("trans_provider", "Local Proxy (127.0.0.1)")
                    with gr.Row():
                        api_provider = gr.Radio(choices=["Local Proxy (127.0.0.1)", "OmniRoute", "Freeway", "Mistral", "Google Studio (Gemma 4)", "Groq (OSS 120b)", "OpenRouter"], value=api_provider_val, label="PROVIDER")
                        translate_mode = gr.Radio(choices=["Files", "Text (from Editor)"], value="Files", label="MODE")
                        
                    target_languages = gr.CheckboxGroup(choices=["Русский", "English", "עברית (Hebrew)"], value=ui_state.get("trans_langs", ["Русский"]), label="TARGET LANGUAGES")
                    
                    init_key = ""
                    if api_provider_val == "OpenRouter": init_key = saved_keys.get("openrouter", "")
                    elif api_provider_val == "Groq (OSS 120b)": init_key = saved_keys.get("groq", "")
                    elif api_provider_val == "Google Studio (Gemma 4)": init_key = saved_keys.get("google_studio", "") or saved_keys.get("google", "")
                    elif api_provider_val == "Google Gemini": init_key = saved_keys.get("google", "")
                    elif api_provider_val == "OmniRoute": init_key = saved_keys.get("omniroute", "")
                    elif api_provider_val == "Freeway": init_key = saved_keys.get("freeway", "") or "123"
                    elif api_provider_val == "Mistral": init_key = saved_keys.get("mistral", "")
                    else: init_key = "dummy" if api_provider_val == "Local Proxy (127.0.0.1)" else ""
                    
                    api_key_input = gr.Textbox(label=f"API Key ({api_provider_val})", value=init_key, type="password")
                    save_key_btn = gr.Button("💾 SAVE KEY", variant="secondary", elem_classes=["fixed-height-btn"], min_width=40)
                    
                    if api_provider_val == "OpenRouter": init_choices = get_model_choices(OPENROUTER_MODELS)
                    elif api_provider_val == "Groq (OSS 120b)": init_choices = GROQ_MODELS
                    elif api_provider_val == "Google Studio (Gemma 4)": init_choices = get_model_choices(GOOGLE_STUDIO_MODELS)
                    elif api_provider_val == "OmniRoute": init_choices = get_model_choices(OMNIROUTE_MODELS)
                    elif api_provider_val == "Freeway": init_choices = get_model_choices(FREEWAY_MODELS)
                    elif api_provider_val == "Mistral": init_choices = get_model_choices(MISTRAL_MODELS)
                    else: init_choices = get_model_choices(LOCAL_PROXY_MODELS)
                    
                    with gr.Row(elem_classes=["uniform-row"]):
                        api_model = gr.Dropdown(choices=init_choices, value=ui_state.get("trans_model", "auto"), label="MODEL", allow_custom_value=True, scale=4)
                        check_api_btn = gr.Button("🔍 CHECK API", variant="secondary", elem_classes=["fixed-height-btn"], scale=1)
                        refresh_models_btn = gr.Button("🔄", variant="secondary", elem_classes=["fixed-height-btn"], scale=1, min_width=40)
                        
                    translate_status = gr.Textbox(label="TRANSLATION STATUS", lines=2, interactive=False)
                        
                    # 🚀 ИДЕАЛЬНЫЙ ДИЗАЙН: Кнопки файлов и SRT скомпонованы 2х2 точно как на фото!
                    with gr.Group():
                        with gr.Row():
                            srt_local_path = gr.Textbox(label="AUTOFILL FILE PATH", value=ui_state.get("trans_srt_path", ""), placeholder="D:\\Video\\docs", scale=5, lines=2)
                            with gr.Column(scale=4):
                                with gr.Row(elem_classes=["uniform-row"]):
                                    clear_trans_files_btn = gr.Button("🗑️ CLEAR", variant="secondary", elem_classes=["fixed-height-btn"], min_width=40)
                                    srt_paste_btn = gr.Button("📋 PASTE", variant="secondary", elem_classes=["fixed-height-btn"], min_width=40)
                                    srt_file_btn = gr.Button("📄 FILE", variant="secondary", elem_classes=["fixed-height-btn"], min_width=40)
                                    srt_folder_btn = gr.Button("📂 DIR", variant="secondary", elem_classes=["fixed-height-btn"], min_width=40)
                                with gr.Row(elem_classes=["uniform-row"]):
                                    copy_srt_btn = gr.Button("📋 COPY SRT", variant="primary", elem_classes=["fixed-height-btn"])
                                    save_srt_btn = gr.Button("💾 SAVE SRT AS...", variant="primary", elem_classes=["fixed-height-btn"])
                        
                    custom_srt = gr.File(label="OR DRAG & DROP FILES HERE", file_types=[".srt", ".txt", ".csv", ".json", ".pdf", ".md"], file_count="multiple")
                    
                    with gr.Row():
                        translate_btn = gr.Button("🪄 TRANSLATE", variant="secondary", elem_classes=["fixed-height-btn"])
                        export_json_btn = gr.Button("📚 EXTRACT VOCAB", variant="secondary", elem_classes=["fixed-height-btn"])
                        
                    export_json_status = gr.Textbox(label="VOCAB STATUS", lines=2, interactive=False)

                clean_text_output = gr.Textbox(label="📄 TEXT EDITOR (NO TIMECODES)", lines=12, max_lines=12, elem_classes=["big-text"], interactive=True, value="")
                
                gr.Markdown("#### 📝 TEXT EDITOR ACTIONS (NO TIMECODES)")
                with gr.Row(elem_classes=["uniform-row"]):
                    save_format = gr.Dropdown(
                        choices=["txt", "md", "csv", "json"], 
                        value="txt", 
                        label="FORMAT", 
                        scale=1
                    )
                    save_text_btn = gr.Button("💾 SAVE TEXT", variant="secondary", elem_classes=["fixed-height-btn"], scale=4)
                
                save_status = gr.Markdown("")
                
                with gr.Accordion("⚙️ SYSTEM PROMPT (AI TRANSLATOR)", open=False):
                    sys_prompt = gr.Textbox(label="PROMPT", value=ui_state.get("trans_prompt", GEMMA_SYSTEM_PROMPT), lines=5, show_label=False)
                
                timer = gr.Timer(0.3)
                timer.tick(fn=process_logs, inputs=[output_log], outputs=[output_log, metrics_panel])
                
                clear_media_btn.click(
                    fn=lambda: ("", "", None),
                    inputs=[],
                    outputs=[urls_input, manual_path, input_file]
                )

                clear_trans_files_btn.click(
                    fn=lambda: ("", None),
                    inputs=[],
                    outputs=[srt_local_path, custom_srt]
                )

        def update_ui_for_provider(provider: str):
            keys = load_keys_safe()
            last_models = keys.get("last_models", {})
            cached_models = keys.get("cached_models", {})
            loc_choices = get_model_choices(LOCAL_PROXY_MODELS)
            
            def get_cached_or_default(provider_key: str, default_choices: list):
                """Use cached models if available, otherwise fall back to static defaults."""
                cached = cached_models.get(provider_key, [])
                return cached if cached else default_choices
            
            if provider == "Local Proxy (127.0.0.1)":
                choices = get_cached_or_default("local_proxy", loc_choices)
                saved_model = last_models.get("Local Proxy (127.0.0.1)", choices[0] if choices else "auto")
                return gr.update(label="API Key (Not required)", value="dummy"), gr.update(choices=choices, value=saved_model), gr.update(value=DEFAULT_SYSTEM_PROMPT)
            elif provider == "OpenRouter":
                or_choices = get_cached_or_default("openrouter", get_model_choices(OPENROUTER_MODELS))
                saved_model = last_models.get("OpenRouter", or_choices[0] if or_choices else "")
                return gr.update(label="API Key (OpenRouter)", value=keys.get("openrouter", "")), gr.update(choices=or_choices, value=saved_model), gr.update(value=DEFAULT_SYSTEM_PROMPT)
            elif provider == "Google Studio (Gemma 4)":
                gs_choices = get_cached_or_default("google_studio", get_model_choices(GOOGLE_STUDIO_MODELS))
                val = keys.get("google_studio", "") or keys.get("google", "")
                saved_model = last_models.get("Google Studio (Gemma 4)", gs_choices[0] if gs_choices else "")
                return gr.update(label="API Key (Google Studio)", value=val), gr.update(choices=gs_choices, value=saved_model), gr.update(value=GEMMA_SYSTEM_PROMPT)
            elif provider == "Groq (OSS 120b)":
                groq_choices = get_cached_or_default("groq", GROQ_MODELS)
                saved_model = last_models.get("Groq (OSS 120b)", groq_choices[0] if groq_choices else "")
                return gr.update(label="API Key (Groq)", value=keys.get("groq", "")), gr.update(choices=groq_choices, value=saved_model), gr.update(value=DEFAULT_SYSTEM_PROMPT)
            elif provider == "OmniRoute":
                omniroute_choices = get_cached_or_default("omniroute", get_model_choices(OMNIROUTE_MODELS))
                if not omniroute_choices:
                    omniroute_choices = ["🔄 Click 🔄 to load models"]
                    saved_model = ""
                else:
                    saved_model = last_models.get("OmniRoute", omniroute_choices[0])
                return gr.update(label="API Key (OmniRoute)", value=keys.get("omniroute", "")), gr.update(choices=omniroute_choices, value=saved_model), gr.update(value=DEFAULT_SYSTEM_PROMPT)
            elif provider == "Freeway":
                freeway_choices = get_cached_or_default("freeway", get_model_choices(FREEWAY_MODELS))
                if not freeway_choices:
                    freeway_choices = ["🔄 Click 🔄 to load models"]
                    saved_model = ""
                else:
                    saved_model = last_models.get("Freeway", freeway_choices[0])
                return gr.update(label="API Key (Freeway)", value=keys.get("freeway", "") or "123"), gr.update(choices=freeway_choices, value=saved_model), gr.update(value=DEFAULT_SYSTEM_PROMPT)
            elif provider == "Mistral":
                mistral_choices = get_cached_or_default("mistral", get_model_choices(MISTRAL_MODELS))
                saved_model = last_models.get("Mistral", mistral_choices[0] if mistral_choices else "")
                return gr.update(label="API Key (Mistral)", value=keys.get("mistral", "")), gr.update(choices=mistral_choices, value=saved_model), gr.update(value=DEFAULT_SYSTEM_PROMPT)
            else:
                return gr.update(label="API Key", value=keys.get("google", "")), gr.update(choices=[], value=""), gr.update(value=DEFAULT_SYSTEM_PROMPT)

        api_provider.change(fn=update_ui_for_provider, inputs=[api_provider], outputs=[api_key_input, api_model, sys_prompt])

        def on_save_key(provider: str, api_key_val: str):
            """Save the current API key to whisper_api_keys.json immediately."""
            if not api_key_val and provider != "Local Proxy (127.0.0.1)":
                gr.Warning("⚠️ Enter an API key before saving!")
                return "⚠️ Key is empty — not saved."
            try:
                keys = load_keys_safe()
                provider_key_map = {
                    "Local Proxy (127.0.0.1)": "google",
                    "OpenRouter": "openrouter",
                    "Google Studio (Gemma 4)": "google_studio",
                    "Groq (OSS 120b)": "groq",
                    "OmniRoute": "omniroute",
                    "Freeway": "freeway",
                    "Mistral": "mistral",
                }
                pk = provider_key_map.get(provider, "google")
                keys[pk] = api_key_val
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(keys, f, indent=4)
                return f"✅ Key for {provider} saved."
            except Exception as e:
                gr.Warning(f"❌ Save error: {e}")
                return f"❌ Error: {e}"

        save_key_btn.click(
            fn=on_save_key,
            inputs=[api_provider, api_key_input],
            outputs=[translate_status]
        )

        def on_refresh_models(provider: str, api_key_val: str):
            """Fetch models from provider, cache them, and update dropdown."""
            models = fetch_models(provider, api_key_val)
            if not models:
                gr.Warning(f"⚠️ Could not load models for {provider}. Check your API key and connection.")
                return gr.update()
            # Cache in whisper_api_keys.json
            try:
                keys = load_keys_safe()
                cached = keys.get("cached_models", {})
                # Map provider display name to key
                provider_key_map = {
                    "Local Proxy (127.0.0.1)": "local_proxy",
                    "OpenRouter": "openrouter",
                    "Google Studio (Gemma 4)": "google_studio",
                    "Groq (OSS 120b)": "groq",
                    "OmniRoute": "omniroute",
                    "Freeway": "freeway",
                    "Mistral": "mistral",
                }
                pk = provider_key_map.get(provider, provider.lower().replace(" ", "_"))
                cached[pk] = models
                keys["cached_models"] = cached
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(keys, f, indent=4)
            except Exception:
                pass
            return gr.update(choices=models, value=models[0] if models else None)

        refresh_models_btn.click(
            fn=on_refresh_models,
            inputs=[api_provider, api_key_input],
            outputs=[api_model]
        )
        
        paste_btn.click(fn=read_clipboard_paths, outputs=manual_path)
        srt_paste_btn.click(fn=read_clipboard_paths, outputs=srt_local_path)
        file_btn.click(fn=open_files_batch_dialog, outputs=manual_path)
        folder_batch_btn.click(fn=open_dir_batch_dialog, outputs=manual_path)
        folder_btn.click(fn=open_folder_dialog, outputs=output_folder)
        srt_file_btn.click(fn=open_srt_batch_dialog, outputs=srt_local_path)
        srt_folder_btn.click(fn=open_dir_srt_dialog, outputs=srt_local_path)
        refresh_files_btn.click(fn=list_files, inputs=[manual_path, use_custom_output, output_folder], outputs=[files_to_delete, del_status])
        del_selected_btn.click(fn=delete_selected, inputs=[files_to_delete, manual_path, use_custom_output, output_folder], outputs=[files_to_delete, del_status])
        del_all_btn.click(fn=delete_all, inputs=[manual_path, use_custom_output, output_folder], outputs=[files_to_delete, del_status])
        
        save_text_btn.click(fn=save_edited_text_dialog, inputs=[clean_text_output, hidden_base_name, hidden_actual_out_dir, save_format], outputs=save_status)
        
        # 🚀 Вызов умных функций, которые сами выберут откуда взять путь к файлу
        copy_srt_btn.click(
            fn=smart_copy_srt,
            inputs=[hidden_srt_paths, srt_local_path],
            outputs=[translate_status]
        )
        
        save_srt_btn.click(
            fn=smart_save_srt,
            inputs=[hidden_srt_paths, srt_local_path, hidden_actual_out_dir],
            outputs=[translate_status]
        )

        whisper_inputs = [
            input_file, manual_path, urls_input, initial_prompt, hotwords, vad_method, 
            language, model_size, compute_type, temperature, rep_penalty, 
            beam_size, patience, condition_on_prev, no_speech_thresh, 
            use_sentence, use_print_progress, use_vad_filter, use_beep_off, 
            use_custom_output, output_folder, output_formats, save_audio_track
        ]

        check_api_btn.click(
            fn=check_api,
            inputs=[api_provider, api_key_input, api_model],
            outputs=[translate_status]
        )

        start_btn.click(fn=prepare_start, outputs=log_box).then(
            fn=run_transcription,
            inputs=whisper_inputs,
            outputs=[clean_text_output, hidden_dl_files, log_box, hidden_srt_paths, srt_local_path, hidden_actual_out_dir] 
        )

        start_full_btn.click(fn=prepare_start, outputs=log_box).then(
            fn=run_transcription,
            inputs=whisper_inputs,
            outputs=[clean_text_output, hidden_dl_files, log_box, hidden_srt_paths, srt_local_path, hidden_actual_out_dir] 
        ).then(
            fn=lambda: "⏳ SUBTITLES READY! Starting automatic translation...", outputs=translate_status
        ).then(
            fn=translate_content, 
            inputs=[
                api_provider, api_key_input, target_languages, api_model, 
                sys_prompt, custom_srt, srt_local_path, hidden_actual_out_dir, 
                hidden_srt_paths, translate_mode, clean_text_output
            ], 
            outputs=[translate_status, clean_text_output, hidden_srt_paths]
        )
        
        translate_btn.click(fn=prepare_start, outputs=log_box).then(
            fn=translate_content, 
            inputs=[
                api_provider, api_key_input, target_languages, api_model, 
                sys_prompt, custom_srt, srt_local_path, hidden_actual_out_dir, 
                hidden_srt_paths, translate_mode, clean_text_output
            ], 
            outputs=[translate_status, clean_text_output, hidden_srt_paths]
        )

        export_json_btn.click(
            fn=export_to_json_dict, 
            inputs=[
                srt_local_path, custom_srt, clean_text_output, 
                hidden_actual_out_dir, hidden_srt_paths
            ], 
            outputs=[export_json_status, hidden_dl_files, clean_text_output]
        )
        
        pause_btn.click(fn=utils.toggle_pause, outputs=[pause_btn])
        stop_btn.click(fn=stop_all_processes, outputs=[log_box], queue=False)
        restart_btn.click(fn=restart_app, js="function(){ setTimeout(() => location.reload(), 2000); }", queue=False)
        exit_btn.click(fn=kill_program, queue=False)

        eco_btn.click(
            fn=eco_preset,
            outputs=[model_size, compute_type, beam_size, condition_on_prev, use_vad_filter]
        )

    return app