import os
import re
import time
import glob
import logging
import threading
from typing import List, Tuple, Any, Set
import gradio as gr
import utils 
from config import (
    DEFAULT_OUTPUT_DIR, DEFAULT_SYSTEM_PROMPT, GEMMA_SYSTEM_PROMPT, CONFIG_FILE,
    OMNIROUTE_BASE_URL, FREEWAY_BASE_URL, FREEWAY_DEFAULT_KEY, MISTRAL_BASE_URL,
    TARGET_LANGUAGES, TARGET_LANGUAGE_MARKERS, TARGET_LANGUAGE_CODE_MAP,
    get_custom_provider, save_custom_provider,
)
from ui_manager import ui_state
from srt_processor import chunk_text, sanitize_srt_text, validate_srt_translation
from queue_manager import batch_queue
import json


def _custom_cfg(provider):
    """Config of a user-defined OpenAI-compatible provider, or None."""
    try:
        return get_custom_provider(provider)
    except Exception:
        return None


def _openai_endpoint(provider, api_key=""):
    """Resolve (base_url, api_key) for OpenAI-compatible providers, custom included."""
    cfg = _custom_cfg(provider)
    if cfg:
        return cfg.get("base_url", ""), (api_key or cfg.get("api_key", "") or "not-needed")
    if provider == "OmniRoute":
        return OMNIROUTE_BASE_URL, api_key
    if provider == "Freeway":
        return FREEWAY_BASE_URL, (api_key or FREEWAY_DEFAULT_KEY)
    if provider == "Mistral":
        return MISTRAL_BASE_URL, api_key
    return "", api_key


# Normalized language detection map shared across helpers.
_LANG_DETECT_MAP = TARGET_LANGUAGE_MARKERS

GEMINI_READY = False
try:
    import google.generativeai as genai
    GEMINI_READY = True
except ImportError: pass

OPENAI_READY = False
try:
    from openai import OpenAI
    OPENAI_READY = True
except ImportError: pass

GROQ_READY = False
try:
    from groq import Groq
    GROQ_READY = True
except ImportError: pass

# Module-level guard to prevent concurrent translate_content runs.
_translate_lock = threading.Lock()
_translate_running = False


def lang_code(value: str) -> str:
    """Normalize a language name/code to a two-letter code (ru/en/he) or 'auto'."""
    if not value:
        return "auto"
    v = str(value).strip().lower()
    if v == "auto":
        return "auto"
    if v in ("ru", "rus", "russian", "русский"):
        return "ru"
    if v in ("en", "eng", "english"):
        return "en"
    if v in ("he", "heb", "hebrew", "עברית"):
        return "he"
    return v


def _detect_source_language(fpath: str, base_name: str, source_language: str) -> str:
    """Determine the source language code using setting, queue metadata, or filename."""
    # 1. Explicit setting (when not auto)
    if source_language and source_language.lower() != "auto":
        return lang_code(source_language)

    # 2. faster-whisper detected language stored in the queue item metadata
    if fpath and fpath != "PLAIN_TEXT":
        item = batch_queue.find_item_by_path(fpath)
        if item is not None:
            detected = batch_queue.get_detected_language(item.idx)
            if detected:
                return lang_code(detected)

    # 3. Filename token matching (markers are now keyed by stable code)
    tokens = {t.lower() for t in re.split(r'[_\\-\\.\\s\\(\\)\\[\\]]+', base_name) if t}
    for lang_code_key, markers in _LANG_DETECT_MAP.items():
        if tokens & markers:
            return lang_code(lang_code_key)

    return "auto"


def _ensure_singleton(func):
    """Decorator ensuring only one translate_content runs at a time."""
    def wrapper(*args, **kwargs):
        global _translate_running
        with _translate_lock:
            if _translate_running:
                return "[TRANSLATE] Already running, duplicate start ignored.", "", ""
            _translate_running = True
        try:
            return func(*args, **kwargs)
        finally:
            _translate_running = False
    return wrapper

def _save_last_model(provider: str, model_name: str) -> None:
    """Save last successful model for provider into whisper_api_keys.json."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                keys = json.load(f)
        else:
            keys = {}
        last_models = keys.get("last_models", {})
        last_models[provider] = model_name
        keys["last_models"] = last_models
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(keys, f, indent=4)
    except Exception:
        pass


def _prepare_files_to_translate(files_to_translate: List[str]) -> Tuple[List[str], int]:
    """Deduplicate paths and drop files that are already translation outputs.

    Returns the cleaned list and the number of already-translated files skipped.
    """
    # Deduplicate while preserving order.
    seen_paths: Set[str] = set()
    deduplicated: List[str] = []
    for p in files_to_translate:
        key = os.path.normcase(os.path.abspath(p))
        if key in seen_paths:
            continue
        seen_paths.add(key)
        deduplicated.append(p)

    # Drop files that are already translation outputs.
    filtered: List[str] = []
    for p in deduplicated:
        if "_TRANSLATED_" not in os.path.basename(p):
            filtered.append(p)
    skipped_translated = len(deduplicated) - len(filtered)
    return filtered, skipped_translated
@_ensure_singleton
def translate_content(
    provider: str, current_api_key: str, target_langs: List[str], model_name: str,
    sys_prompt: str, custom_srt_files: List[Any], srt_local_path: str,
    hidden_actual_out_dir: str, hidden_srt_paths: str, translate_mode: str, plain_text_input: str,
    force_all_langs: bool = False, source_language: str = "auto",
    plain_text_output: bool = False,
    use_custom_output: bool = False, output_dir: str = ""
) -> Tuple[str, str, str]:  # return three values
    if getattr(utils, 'stop_requested', False):
        return "⚠️ Translation cancelled before start.", "", ""

    selected_output_dir = ""
    if use_custom_output:
        try:
            selected_output_dir = utils.get_actual_output_dir("", True, output_dir)
            os.makedirs(selected_output_dir, exist_ok=True)
        except (OSError, ValueError) as e:
            return "❌ Output folder error: " + str(e), "", ""

    client = None
    ui_state.save_settings({
        "trans_provider": provider, "trans_mode": translate_mode, "trans_srt_path": srt_local_path,
        "trans_langs": target_langs, "trans_model": model_name, "trans_prompt": sys_prompt
    })
    
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: keys = json.load(f)
        else: keys = {}
        
        if provider == "OpenRouter": keys["openrouter"] = current_api_key
        elif provider == "Google Studio (Gemma 4)": keys["google_studio"] = current_api_key
        elif provider == "Groq (OSS 120b)": keys["groq"] = current_api_key
        elif provider == "OmniRoute": keys["omniroute"] = current_api_key
        elif provider == "Freeway": keys["freeway"] = current_api_key or FREEWAY_DEFAULT_KEY
        elif provider == "Mistral": keys["mistral"] = current_api_key
        elif _custom_cfg(provider):
            try:
                save_custom_provider(provider, (_custom_cfg(provider) or {}).get("base_url", ""), current_api_key)
            except Exception:
                pass
        else: keys["google"] = current_api_key
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(keys, f, indent=4)
    except Exception: pass
    
    api_key = current_api_key

    def live_log(msg: str):
        utils.log_to_terminal(msg); utils.log_queue.put(msg + "\n")

    if not api_key and provider not in ("Local Proxy (127.0.0.1)", "Freeway") and not _custom_cfg(provider):
        return "❌ Error: No API key specified!", "", ""
    if not model_name or not model_name.strip():
        return "❌ Error: No model selected! Click 🔄 to refresh models.", "", ""

    is_file_mode = (translate_mode == "Files")
    files_to_translate = []
    valid_exts = ('.srt', '.txt', '.csv', '.json', '.pdf', '.md')
    
    if is_file_mode:
        srt_local_path = (srt_local_path or "").strip()
        if srt_local_path:
            paths = [p.strip().strip('"').strip("'") for p in srt_local_path.split('|') if p.strip()]
            for p in paths:
                if os.path.isdir(p):
                    for f in glob.glob(os.path.join(p, '*.*')):
                        if f.lower().endswith(valid_exts): files_to_translate.append(f)
                elif os.path.isfile(p) and p.lower().endswith(valid_exts): files_to_translate.append(p)
        if custom_srt_files:
            for f in custom_srt_files:
                fname = f.name if hasattr(f, 'name') else str(f)
                if fname.lower().endswith(valid_exts): files_to_translate.append(fname)
        if hidden_srt_paths:
            for p in hidden_srt_paths.split('|'):
                if p.strip() and os.path.isfile(p.strip()) and p.strip().lower().endswith(valid_exts): files_to_translate.append(p.strip())

        files_to_translate, skipped_translated = _prepare_files_to_translate(files_to_translate)
        if skipped_translated > 0:
            live_log(f"[TRANSLATE] Skipped {skipped_translated} already translated file(s).")

        if not files_to_translate:
            if not hidden_srt_paths.strip() and not srt_local_path.strip() and not custom_srt_files:
                return "❌ Error: Transcription produced no supported files to translate. Check the LIVE LOG for items that failed to produce output.", "", ""
            return "❌ Error: No supported files found (srt, txt, csv, json, pdf, md)!", "", ""
    else:
        if not plain_text_input.strip(): return "❌ Error: Text field is empty!", "", ""
        files_to_translate = ["PLAIN_TEXT"]

    saved_files = []
    all_clean_editor_text = ""
    files_written_count = 0
    translation_errors = 0
    processed_pairs: Set[Tuple[str, str]] = set()

    try:
        live_log(f"=== TESTING API CONNECTION ({provider}) ===")
        logging.info(f"[CHECK_API] Start check | Provider: {provider} | Model: {model_name}")
        if provider == "Google Gemini":
            if not GEMINI_READY: raise ImportError("Module google-generativeai is not installed.")
            genai.configure(api_key=api_key)
            safety = [{"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"}, {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}, {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"}, {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}]
            model = genai.GenerativeModel(model_name=model_name, system_instruction=sys_prompt, safety_settings=safety)
            model.generate_content("Ping") 
        elif provider == "Local Proxy (127.0.0.1)":
            import requests
            logging.info("[CHECK_API] Checking proxy server availability...")
            try:
                requests.get("http://127.0.0.1:8080/", timeout=5.0)
                logging.info("[CHECK_API] ✅ Proxy server available on port 8080")
            except requests.exceptions.ConnectionError:
                logging.error("[CHECK_API] ❌ Proxy server is not responding on port 8080!")
                raise Exception("CRITICAL_API_ERROR: Proxy server is not running! Start it on port 8080.")
            except Exception as e:
                logging.info(f"[CHECK_API] Proxy available (response: {type(e).__name__})")
            logging.info("[CHECK_API] Sending test Ping request...")
            resp = requests.post("http://127.0.0.1:8080/v1/messages", json={"model": model_name, "system": sys_prompt, "messages": [{"role": "user", "content": "Ping"}]}, timeout=180.0)
            logging.info(f"[CHECK_API] Proxy response: HTTP {resp.status_code}")
            if resp.status_code == 401: raise Exception("CRITICAL_API_ERROR: Google token expired!")
            if resp.status_code == 429: raise Exception("CRITICAL_API_ERROR: Google API request limit exhausted (429). Wait 1-2 minutes.")
            if resp.status_code in [404, 400]: raise Exception(f"CRITICAL_API_ERROR: Proxy error {resp.status_code}")
            resp.raise_for_status()
        elif provider == "Google Studio (Gemma 4)":
            model_name = model_name.removeprefix("models/")
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=api_key, max_retries=0, timeout=60.0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2) 
        elif provider == "OpenRouter":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            headers = {"HTTP-Referer": "http://localhost", "X-Title": "AT-Whisper"}
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, default_headers=headers, max_retries=0, timeout=60.0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2) 
        elif provider == "Groq (OSS 120b)":
            if not GROQ_READY: raise ImportError("Module groq is not installed. Run: pip install groq")
            groq_client = Groq(api_key=api_key, timeout=60.0, max_retries=0)
            groq_client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            client = groq_client
        elif provider == "OmniRoute" or _custom_cfg(provider):
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            _base, _key = _openai_endpoint(provider, api_key)
            client = OpenAI(base_url=(_base or OMNIROUTE_BASE_URL), api_key=_key, max_retries=0, timeout=60.0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
        elif provider == "Freeway":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=FREEWAY_BASE_URL, api_key=(api_key or FREEWAY_DEFAULT_KEY), max_retries=0, timeout=60.0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
        elif provider == "Mistral":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=MISTRAL_BASE_URL, api_key=api_key, max_retries=0, timeout=60.0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
        logging.info(f"[CHECK_API] ✅ {provider} check passed successfully")
        _save_last_model(provider, model_name)
    except Exception as e:
        error_msg = f"❌ API CONNECTION ERROR: {str(e)}"
        logging.error(f"[CHECK_API] {error_msg}")
        live_log(error_msg)
        return error_msg, "", ""
    
    file_chunks_map = []
        
    for fpath in files_to_translate:
        if fpath == "PLAIN_TEXT":
            orig_text = plain_text_input
            b_name = "Text_Translation"
            o_dir = selected_output_dir or hidden_actual_out_dir or DEFAULT_OUTPUT_DIR
            is_srt = False
        else:
            ext = fpath.lower().split('.')[-1] if '.' in fpath else ''
            is_srt = (ext == 'srt')
            if ext == 'pdf':
                try:
                    import PyPDF2
                    with open(fpath, 'rb') as f:
                        pdf_reader = PyPDF2.PdfReader(f)
                        orig_text = "\n".join((page.extract_text() or "") for page in pdf_reader.pages)
                except ImportError:
                    live_log("❌ ERROR: install PyPDF2 to read PDF files (pip install PyPDF2)")
                    continue
            elif ext == 'json':
                import json as json_mod
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        orig_text = json_mod.dumps(json_mod.load(f), ensure_ascii=False, indent=2)
                except Exception as e:
                    live_log(f"❌ Error reading JSON '{fpath}': {e}")
                    continue
            else:
                with open(fpath, 'r', encoding='utf-8') as f: orig_text = f.read()
            
            if is_srt:
                orig_text = sanitize_srt_text(orig_text)
                
            b_name = os.path.splitext(os.path.basename(fpath))[0]
            o_dir = selected_output_dir or (DEFAULT_OUTPUT_DIR if "Temp" in fpath or "temp" in fpath else os.path.dirname(os.path.abspath(fpath)))

        os.makedirs(o_dir, exist_ok=True)
            
        if provider == "Google Studio (Gemma 4)": chunk_lim = 20
        elif provider == "Groq (OSS 120b)": chunk_lim = 24
        else: chunk_lim = 15 if is_srt else 10
            
        c_list = chunk_text(orig_text, chunk_lim, by_paragraphs=not is_srt,
                            max_chars=3000 if provider == "Groq (OSS 120b)" else 6000)
        file_chunks_map.append((fpath, orig_text, b_name, o_dir, c_list, is_srt))

    # Determine source language per file and filter out targets matching it.
    file_source_langs = {}
    for fpath, orig_text, b_name, o_dir, c_list, is_srt in file_chunks_map:
        src = _detect_source_language(fpath, b_name, source_language)
        file_source_langs[fpath] = src
        if src != "auto":
            utils.log_queue.put(f"[TRANSLATE] Detected source language for {b_name}: {src}\n")

    # Total work units for the progress bar is chunk-based so the ETA is real
    total_chunks_all = sum(len(item[4]) for item in file_chunks_map) * max(len(target_langs), 1) if target_langs else 0
    processed_chunks = 0
    start_time = time.time()
    google_api_requests_this_minute = 0
    google_api_minute_start = time.time()

    _lang_detect_map = TARGET_LANGUAGE_MARKERS

    def _tokenize_filename(base_name: str):
        return {t.lower() for t in re.split(r'[_\\-\\.\\s\\(\\)\\[\\]]+', base_name) if t}

    def _matched_language_tokens(base_name: str, target_lang: str) -> List[str]:
        tokens = _tokenize_filename(base_name)
        # target_lang is a stable code (RU/EN/HE); look up markers by code.
        markers = _LANG_DETECT_MAP.get(target_lang, set())
        return [t for t in tokens if t in markers]

    for file_idx, (fpath, original_text, base_name, out_dir, chunks, is_srt) in enumerate(file_chunks_map):
        if getattr(utils, 'stop_requested', False): break
        
        utils.log_queue.put(f"[PROGRESS_FILE] | {file_idx + 1} | {len(file_chunks_map)} | {base_name} | running\n")
        live_log(f"\n🚀 [BATCH TRANSLATE] File: {base_name} | 🧠 Model: {model_name}")
        
        if not target_langs:
            live_log(f"⏭ No translation needed (no languages selected). Outputting '{base_name}' to editor.")
            clean_text = original_text
            if is_srt:
                clean_text = re.sub(r'(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*\n', '', clean_text)
                clean_text = re.sub(r'\n\n+', '\n', clean_text).strip()
            all_clean_editor_text += f"\n--- {base_name} (ORIGINAL) ---\n{clean_text}\n"
            saved_files.append(fpath)  # keep original
            continue
            
        source_lang_code = file_source_langs.get(fpath, "auto")
        effective_target_langs = []
        for target_lang in target_langs:
            target_code = lang_code(target_lang)
            if target_code == source_lang_code and not force_all_langs:
                live_log(f"[SKIP] {base_name}: source language is already {source_lang_code}. Skipped, moving on.")
                continue
            if target_code == source_lang_code and force_all_langs:
                live_log(f"[TRANSLATE] TRANSLATE ANYWAY is on, same-language target kept.")
            effective_target_langs.append(target_lang)

        if not effective_target_langs:
            live_log(f"[TRANSLATE] Nothing to translate: all targets match the source language.")
            clean_text = original_text
            if is_srt:
                clean_text = re.sub(r'(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*\n', '', clean_text)
                clean_text = re.sub(r'\n\n+', '\n', clean_text).strip()
            all_clean_editor_text += f"\n--- {base_name} (ORIGINAL) ---\n{clean_text}\n"
            saved_files.append(fpath)
            continue

        for target_lang in effective_target_langs:
            if getattr(utils, 'stop_requested', False): break

            pair_key = (os.path.normcase(os.path.abspath(fpath)) if fpath != "PLAIN_TEXT" else fpath, target_lang)
            if pair_key in processed_pairs:
                live_log(f"[TRANSLATE] Duplicate target skipped: {base_name} -> {target_lang}.")
                continue
            processed_pairs.add(pair_key)

            # Do not redo work that already exists in the output folder.
            lang_suffix = TARGET_LANGUAGE_CODE_MAP.get(target_lang, lang_code(target_lang).upper())
            if fpath != "PLAIN_TEXT":
                _exist_ext = os.path.splitext(fpath)[1] or ".txt"
                _exist_path = os.path.join(out_dir, f"{base_name}_TRANSLATED_{lang_suffix}{_exist_ext}")
                if os.path.isfile(_exist_path):
                    live_log(f"[SKIP] Translation already exists, not overwritten: {os.path.basename(_exist_path)}")
                    saved_files.append(_exist_path)
                    continue
            
            matched_tokens = _matched_language_tokens(base_name, target_lang)
            if matched_tokens and not force_all_langs:
                token_str = matched_tokens[0]
                live_log(f"[SKIP] {target_lang} skipped: filename token '{token_str.upper()}' indicates it is already {target_lang}. Use the TRANSLATE ANYWAY checkbox to override.")
                clean_text = original_text
                if is_srt:
                    clean_text = re.sub(r'(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*\n', '', clean_text)
                    clean_text = re.sub(r'\n\n+', '\n', clean_text).strip()
                all_clean_editor_text += f"\n--- {base_name} ({target_lang}) ---\n{clean_text}\n"
                saved_files.append(fpath)  # keep original
                continue

            translated_blocks = []
            live_log(f"🌍 Translating to language: {target_lang}")

            # Single-chunk clarity message
            if len(chunks) == 1:
                live_log(f"[TRANSLATE] Single chunk ({len(chunks[0])} blocks) - no split needed.")

            # lang_suffix is the stable code (RU/EN/HE) — always resolves from CODE_MAP
            lang_suffix = TARGET_LANGUAGE_CODE_MAP.get(target_lang, lang_code(target_lang).upper())
            
            for idx, chunk in enumerate(chunks):
                while getattr(utils, 'pause_requested', False) and not getattr(utils, 'stop_requested', False):
                    time.sleep(1)

                if getattr(utils, 'stop_requested', False): 
                    live_log("\n🛑 STOPPING TRANSLATION! Saving what we have...")
                    break

                if provider in ["Google Studio (Gemma 4)", "Google Gemini"]:
                    current_time = time.time()
                    if current_time - google_api_minute_start > 65:
                        google_api_requests_this_minute = 0
                        google_api_minute_start = current_time
                    if google_api_requests_this_minute >= 14: 
                        wait_time = 65 - (current_time - google_api_minute_start)
                        if wait_time > 0:
                            live_log(f"⏳ GOOGLE LIMIT REACHED (15/min). Waiting {int(wait_time)} sec...")
                            if utils.interruptible_sleep(wait_time): break
                        google_api_requests_this_minute = 0
                        google_api_minute_start = time.time()

                processed_chunks += 1 
                e_sec = int(time.time() - start_time)
                utils.log_queue.put(f"[PROGRESS_TRANS] | {processed_chunks} | {total_chunks_all} | {e_sec} | {file_idx} | {len(file_chunks_map)} | {lang_suffix} | {idx} | {len(chunks)} | {base_name}\n")
                    
                chunk_text_str = "\n\n".join(chunk)
                user_prompt = f"Translate this text into {target_lang}.\n\nTEXT:\n{chunk_text_str}"
                live_log(f"   Processing chunk {idx+1} of {len(chunks)}...")
                
                max_retries = 4
                success = False
                
                def _send_to_api(prompt_text: str) -> str:
                    if provider == "Google Gemini":
                        _resp = model.generate_content(prompt_text)
                        return _resp.text
                    elif provider == "Local Proxy (127.0.0.1)":
                        import requests
                        _payload = {
                            "model": model_name, "system": sys_prompt, 
                            "messages": [{"role": "user", "content": prompt_text}]
                        }
                        _r = requests.post("http://127.0.0.1:8080/v1/messages", json=_payload, timeout=180.0)
                        if _r.status_code == 401: raise Exception("CRITICAL_API_ERROR: Google token expired!")
                        if _r.status_code in [429, 404, 400]: raise Exception(f"CRITICAL_API_ERROR: Proxy error {_r.status_code}")
                        _r.raise_for_status()
                        _rj = _r.json()
                        if "content" in _rj and isinstance(_rj["content"], list):
                            return _rj["content"][0].get("text", "")
                        else:
                            _rt = _rj.get("choices", [{}])[0].get("message", {}).get("content", "")
                            if "Error:" in _rt and "unavailable" in _rt:
                                raise Exception(f"CRITICAL_API_ERROR: Proxy found no working models (404/429).")
                            return _rt
                    elif provider == "Google Studio (Gemma 4)":
                        _cp = f"SYSTEM INSTRUCTION: {sys_prompt}\n\n---\n\nUSER PROMPT: {prompt_text}"
                        _resp = client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": _cp}], max_tokens=4000)
                        return _resp.choices[0].message.content
                    elif provider == "Groq (OSS 120b)":
                        _resp = client.chat.completions.create(
                            model=model_name,
                            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt_text}],
                            max_completion_tokens=min(4096, max(768, len(prompt_text) // 2 + 768)),
                            temperature=1,
                            top_p=1,
                        )
                        return _resp.choices[0].message.content
                    else:
                        _resp = client.chat.completions.create(model=model_name, messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt_text}], max_tokens=4000)
                        return _resp.choices[0].message.content

                for attempt in range(max_retries):
                    if getattr(utils, 'stop_requested', False): break
                    while getattr(utils, 'pause_requested', False) and not getattr(utils, 'stop_requested', False): time.sleep(1)

                    try:
                        if provider in ["Google Gemini", "Google Studio (Gemma 4)"]:
                            google_api_requests_this_minute += 1
                        
                        logging.info(f"[TRANSLATE] Chunk {idx+1}/{len(chunks)} | Attempt {attempt+1} | Provider: {provider} | Model: {model_name}")
                        result_text = _send_to_api(user_prompt)
                            
                        if result_text: 
                            clean_result = re.sub(r'<(thought|think)>.*?(<\/\1>|$)\s*', '', result_text, flags=re.DOTALL).strip()
                            if is_srt:
                                clean_result = validate_srt_translation(chunk_text_str, clean_result)
                            translated_blocks.append(clean_result)
                            success = True
                            logging.info(f"[TRANSLATE] ✅ Chunk {idx+1} — OK ({len(clean_result)} chars)")
                            break 
                        else: raise Exception("API returned an empty response")
                            
                    except Exception as e:
                        err_str = str(e)
                        logging.warning(f"[TRANSLATE] ⚠️ Chunk {idx+1} attempt {attempt+1}: {err_str[:200]}")
                        
                        if "413" in err_str and len(chunk) > 1:
                            live_log(f"   📦 Chunk {idx+1} too large ({len(chunk)} blocks). Splitting into individual blocks...")
                            sub_results = []
                            sub_success = True
                            for sub_idx, single_block in enumerate(chunk):
                                if getattr(utils, 'stop_requested', False): sub_success = False; break
                                sub_prompt = f"Translate this text into {target_lang}.\n\nTEXT:\n{single_block}"
                                try:
                                    sub_result = _send_to_api(sub_prompt)
                                    if sub_result:
                                        sub_clean = re.sub(r'<(thought|think)>.*?(<\/\1>|$)\s*', '', sub_result, flags=re.DOTALL).strip()
                                        if is_srt:
                                            sub_clean = validate_srt_translation(single_block, sub_clean)
                                        sub_results.append(sub_clean)
                                        live_log(f"      ✅ Sub-block {sub_idx+1}/{len(chunk)} OK")
                                    else:
                                        translation_errors += 1
                                        sub_results.append(single_block)
                                        live_log(f"      ⚠️ Sub-block {sub_idx+1}/{len(chunk)} — empty response, keeping original")
                                    if sub_idx < len(chunk) - 1: time.sleep(0.5)
                                except Exception as sub_e:
                                    translation_errors += 1
                                    live_log(f"      ❌ Sub-block {sub_idx+1}/{len(chunk)} error: {str(sub_e)[:100]}")
                                    sub_results.append(single_block)
                            if sub_results:
                                translated_blocks.append("\n\n".join(sub_results))
                                success = True
                            break 
                        
                        if "429" in err_str or "too many requests" in err_str.lower() or "rate" in err_str.lower() or ("exhausted" in err_str.lower() and "quota" in err_str.lower()):
                            wait_secs = 60 
                            live_log(f"[TRANSLATE] Paused {wait_secs}s by rate limit. ETA extended.")
                            logging.warning(f"[TRANSLATE] Rate limit / quota exhausted — pausing {wait_secs}s")
                            if utils.interruptible_sleep(wait_secs): break
                            continue  
                        
                        if any(trigger in err_str.lower() for trigger in ["critical_api_error", "403", "permission_denied", "api key not valid"]):
                            live_log(f"\n🚨 [EMERGENCY STOP] Access denied:\n{err_str}\n")
                            logging.error(f"[TRANSLATE] 🛑 CRITICAL ERROR: {err_str}")
                            utils.stop_requested = True
                            return "❌ CRITICAL ERROR: ACCESS DENIED. TRANSLATION ABORTED!", all_clean_editor_text, ""

                        if attempt < max_retries - 1: 
                            live_log(f"   ⚠️ Chunk {idx+1} error (attempt {attempt+1}/{max_retries}): {err_str[:150]}...")
                            if "503" in err_str or "500" in err_str:
                                if utils.interruptible_sleep(10.0): break
                            else:
                                if utils.interruptible_sleep(2.0): break
                        else:
                            live_log(f"   ❌ Final error for chunk {idx+1}: {err_str}")
                            logging.error(f"[TRANSLATE] ❌ All attempts exhausted for chunk {idx+1}: {err_str}")

                if not success and getattr(utils, 'stop_requested', False): break
                if not success:
                    translation_errors += 1
                    translated_blocks.append(chunk_text_str)
                    live_log(f"[WARNING] Chunk {idx+1} was not translated; original retained. Batch is not successful.")
                if idx < len(chunks) - 1: 
                    delay = 3.0 if provider == "Local Proxy (127.0.0.1)" else 1.5
                    if utils.interruptible_sleep(delay): break 

            if translated_blocks:
                final_translated_text = "\n\n".join(translated_blocks)
                # lang_suffix already resolved to a stable code above
                orig_ext = os.path.splitext(fpath)[1] if fpath != "PLAIN_TEXT" else ".txt"
                ext = orig_ext if orig_ext else ".txt"
                
                partial_tag = "_PARTIAL" if getattr(utils, 'stop_requested', False) or translation_errors else ""
                translated_path = os.path.join(out_dir, f"{base_name}_TRANSLATED_{lang_suffix}{partial_tag}{ext}")
                translated_path = utils.unique_path(translated_path)
                if translated_path != os.path.join(out_dir, f"{base_name}_TRANSLATED_{lang_suffix}{partial_tag}{ext}"):
                    live_log(f"[SAVE] Existing file kept. Writing {os.path.basename(translated_path)} instead.")

                try:
                    with open(translated_path, "w", encoding="utf-8") as f: f.write(final_translated_text)
                    saved_files.append(translated_path)
                    files_written_count += 1

                    if plain_text_output and is_srt:
                        try:
                            clean_text = utils.clean_srt_text(final_translated_text)
                            clean_path = os.path.join(
                                out_dir,
                                f"{os.path.splitext(os.path.basename(translated_path))[0]}_CLEAN.txt"
                            )
                            with open(clean_path, "w", encoding="utf-8") as f:
                                f.write(clean_text)
                            saved_files.append(clean_path)
                            live_log(f"[CLEAN] {os.path.basename(clean_path)}")
                        except Exception as e:
                            translation_errors += 1
                            live_log(f"❌ Clean text save error: {e}")

                    clean_text = final_translated_text
                    if is_srt:
                        clean_text = utils.clean_srt_text(clean_text)
                    all_clean_editor_text += f"\n--- {base_name} ({target_lang}) ---\n{clean_text}\n"
                except Exception as e:
                    translation_errors += 1
                    live_log(f"❌ File save error: {e}")

    if not getattr(utils, 'stop_requested', False):
        live_log("\n⚠️ BATCH COMPLETED WITH TRANSLATION ERRORS." if translation_errors else "\n✅ ENTIRE BATCH TRANSLATED!")
        utils.log_queue.put(f"[PROGRESS_FILE] | {len(file_chunks_map)} | {len(file_chunks_map)} | done | done\n")
        # Log [RESULT] lines for every translated file written
        for sf in saved_files:
            if "_TRANSLATED_" in sf:
                match = re.search(r'_TRANSLATED_([A-Z]{2,3})', os.path.basename(sf))
                if match:
                    result_lang = match.group(1)
                    live_log(f"[RESULT] {result_lang} -> {sf}")

        live_log(f"[TRANSLATE] Batch finished: {len(file_chunks_map)} file(s), {len(target_langs)} language(s), {files_written_count} file(s) written.")

    result_label = "⚠️ Interrupted. Partial progress saved" if getattr(utils, 'stop_requested', False) else ("⚠️ Completed with errors" if translation_errors else "✅ Completed")
    status_msg = f"{result_label}: {len(saved_files)} files."
    # Return three values (third is the SRT path list joined by |)
    return status_msg, all_clean_editor_text, "|".join(saved_files)

def _provider_error(error):
    """Do not expose response bodies, URLs with credentials, or API keys."""
    status = getattr(error, 'status_code', None)
    if status is None and getattr(error, 'response', None) is not None:
        status = error.response.status_code
    labels = {400: 'Invalid model or request parameters', 401: 'Authentication failed / token expired',
              403: 'Access denied', 404: 'Model or API endpoint not found',
              402: 'Payment or credit required', 429: 'Rate limit or quota exhausted'}
    if status:
        return f"HTTP {status}: {labels.get(status, 'Provider request failed')}"
    name = type(error).__name__
    if 'Timeout' in name:
        return 'Provider timed out; try again later.'
    if 'Connection' in name:
        return 'Cannot connect to provider; check server/network.'
    if isinstance(error, ValueError):
        return 'Invalid provider configuration or response.'
    if isinstance(error, ImportError):
        return 'Required provider SDK is not installed.'
    return 'Provider request failed (' + name + ').'


def _health_client(provider, api_key):
    endpoints = {'Google Studio (Gemma 4)': 'https://generativelanguage.googleapis.com/v1beta/openai',
                 'OpenRouter': 'https://openrouter.ai/api/v1',
                 'Groq (OSS 120b)': 'https://api.groq.com/openai/v1'}
    base, key = _openai_endpoint(provider, api_key)
    base = base or endpoints.get(provider, '')
    if not base:
        raise ValueError('Unknown provider')
    if not OPENAI_READY:
        raise ImportError('openai')
    headers = {'HTTP-Referer': 'http://localhost', 'X-Title': 'KATAV'} if provider == 'OpenRouter' else None
    return OpenAI(base_url=base, api_key=key or 'not-needed', timeout=30.0, max_retries=0, default_headers=headers)


def check_api(provider: str, current_api_key: str, model_name: str, *, persist=True) -> str:
    if not current_api_key and provider not in ('Local Proxy (127.0.0.1)', 'Freeway') and not _custom_cfg(provider):
        return '❌ Error: Enter an API key!'
    model_name = str(model_name or '').strip()
    if not model_name or model_name == 'auto' or model_name.startswith('🔄'):
        return '❌ Select or enter an exact MODEL ID, then CHECK API.'
    try:
        if provider == 'Google Gemini':
            if not GEMINI_READY:
                raise ImportError('google.generativeai')
            genai.configure(api_key=current_api_key)
            response = genai.GenerativeModel(model_name=model_name).generate_content(
                'Reply OK.', generation_config={'max_output_tokens': 16}, request_options={'timeout': 30})
            if not response.candidates:
                raise ValueError('No inference response')
        elif provider == 'Local Proxy (127.0.0.1)':
            import requests
            response = requests.post('http://127.0.0.1:8080/v1/messages',
                json={'model': model_name, 'max_tokens': 16, 'messages': [{'role': 'user', 'content': 'Reply OK.'}]},
                timeout=(5, 30), allow_redirects=False)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or not (body.get('content') or body.get('choices')):
                raise ValueError('No inference response')
        else:
            resolved = model_name.removeprefix('models/') if provider == 'Google Studio (Gemma 4)' else model_name
            with _health_client(provider, current_api_key) as client:
                response = client.chat.completions.create(model=resolved,
                    messages=[{'role': 'user', 'content': 'Reply OK.'}], max_tokens=16)
                if not response.choices:
                    raise ValueError('No inference response')
        if persist:
            _save_last_model(provider, model_name)
        return f'✅ Inference verified: {provider} · {model_name}'
    except Exception as error:
        return '❌ ' + _provider_error(error)


def fetch_models(provider: str, api_key: str) -> list:
    """Bounded discovery; a model catalog is not proof that inference works."""
    if not api_key and provider not in ('Local Proxy (127.0.0.1)', 'Freeway') and not _custom_cfg(provider):
        return []
    try:
        if provider == 'Local Proxy (127.0.0.1)':
            import requests
            response = requests.get('http://127.0.0.1:8080/v1/models', timeout=(5, 15), allow_redirects=False)
            response.raise_for_status()
            data = response.json()
            rows = data.get('data', []) if isinstance(data, dict) else data
            return sorted({row['id'] for row in rows if isinstance(row, dict) and row.get('id')})
        if provider == 'Google Gemini':
            if not GEMINI_READY:
                raise ImportError('google.generativeai')
            genai.configure(api_key=api_key)
            return sorted(m.name for m in genai.list_models(request_options={'timeout': 15})
                          if 'generateContent' in m.supported_generation_methods)
        with _health_client(provider, api_key) as client:
            return sorted({model.id for model in client.models.list(timeout=15).data if model.id})
    except Exception as error:
        logging.warning('[FETCH_MODELS] %s: %s', provider, _provider_error(error))
        return []
