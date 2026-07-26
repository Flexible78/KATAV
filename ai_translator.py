import os
import re
import time
import glob
import logging
from typing import List, Tuple, Any
import gradio as gr
import utils 
from config import DEFAULT_OUTPUT_DIR, DEFAULT_SYSTEM_PROMPT, GEMMA_SYSTEM_PROMPT, CONFIG_FILE
from config import OMNIROUTE_BASE_URL, FREEWAY_BASE_URL, FREEWAY_DEFAULT_KEY, MISTRAL_BASE_URL
from ui_manager import ui_state
from srt_processor import chunk_text, sanitize_srt_text
import json

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

def translate_content(
    provider: str, current_api_key: str, target_langs: List[str], model_name: str,
    sys_prompt: str, custom_srt_files: List[Any], srt_local_path: str,
    hidden_actual_out_dir: str, hidden_srt_paths: str, translate_mode: str, plain_text_input: str,
    force_all_langs: bool = False
) -> Tuple[str, str, str]: # 🚀 Возвращаем три параметра!
    
    if getattr(utils, 'stop_requested', False):
        return "⚠️ Translation cancelled before start.", "", ""

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
        else: keys["google"] = current_api_key
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(keys, f, indent=4)
    except Exception: pass
    
    api_key = current_api_key

    def live_log(msg: str):
        utils.log_to_terminal(msg); utils.log_queue.put(msg + "\n")

    if not api_key and provider != "Local Proxy (127.0.0.1)": return "❌ Error: No API key specified!", "", ""
    if not model_name or not model_name.strip(): return "❌ Error: No model selected! Click 🔄 to refresh models.", "", ""

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
                        if f.lower().endswith(('.srt', '.md')): files_to_translate.append(f)
                elif os.path.isfile(p) and p.lower().endswith(valid_exts): files_to_translate.append(p)
        if custom_srt_files:
            for f in custom_srt_files:
                fname = f.name if hasattr(f, 'name') else str(f)
                if fname.lower().endswith(valid_exts): files_to_translate.append(fname)
        elif hidden_srt_paths:
            for p in hidden_srt_paths.split('|'):
                if p.strip() and os.path.isfile(p.strip()) and p.strip().lower().endswith(valid_exts): files_to_translate.append(p.strip())
        if not files_to_translate:
            if not hidden_srt_paths.strip() and not srt_local_path.strip() and not custom_srt_files:
                return "❌ Error: Transcription produced no supported files to translate. Check the LIVE LOG for items that failed to produce output.", "", ""
            return "❌ Error: No supported files found (srt, txt, csv, json, pdf, md)!", "", ""
    else:
        if not plain_text_input.strip(): return "❌ Error: Text field is empty!", "", ""
        files_to_translate = ["PLAIN_TEXT"]

    saved_files = []
    all_clean_editor_text = ""
    
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
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=api_key, max_retries=0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2) 
        elif provider == "OpenRouter":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            headers = {"HTTP-Referer": "http://localhost", "X-Title": "AT-Whisper"}
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, default_headers=headers, max_retries=0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2) 
        elif provider == "Groq (OSS 120b)":
            if not GROQ_READY: raise ImportError("Module groq is not installed. Run: pip install groq")
            groq_client = Groq(api_key=api_key)
            groq_client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            client = groq_client
        elif provider == "OmniRoute":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=OMNIROUTE_BASE_URL, api_key=api_key, max_retries=0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
        elif provider == "Freeway":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=FREEWAY_BASE_URL, api_key=(api_key or FREEWAY_DEFAULT_KEY), max_retries=0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
        elif provider == "Mistral":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=MISTRAL_BASE_URL, api_key=api_key, max_retries=0)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
        logging.info(f"[CHECK_API] ✅ {provider} check passed successfully")
        _save_last_model(provider, model_name)
    except Exception as e:
        error_msg = f"❌ API CONNECTION ERROR: {str(e)}"
        logging.error(f"[CHECK_API] {error_msg}")
        live_log(error_msg)
        return error_msg, "", ""
    
    file_chunks_map = []
    total_requests = 0
        
    for fpath in files_to_translate:
        if fpath == "PLAIN_TEXT":
            orig_text = plain_text_input
            b_name = "Text_Translation"
            o_dir = hidden_actual_out_dir if hidden_actual_out_dir else os.path.expanduser("~")
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
            o_dir = DEFAULT_OUTPUT_DIR if "Temp" in fpath or "temp" in fpath else os.path.dirname(os.path.abspath(fpath))
            
        if provider == "Google Studio (Gemma 4)": chunk_lim = 6
        elif provider == "Groq (OSS 120b)": chunk_lim = 3
        else: chunk_lim = 15 if is_srt else 10
            
        c_list = chunk_text(orig_text, chunk_lim, by_paragraphs=not is_srt)
        file_chunks_map.append((fpath, orig_text, b_name, o_dir, c_list, is_srt))
        total_requests += len(c_list) * len(target_langs)

    processed_requests = 0
    start_time = time.time()
    google_api_requests_this_minute = 0
    google_api_minute_start = time.time()

    _lang_detect_map = {
        "Русский": {"ru", "rus", "russian"},
        "English": {"en", "eng", "english"},
        "עברית (Hebrew)": {"he", "heb", "hebrew"},
    }

    def _tokenize_filename(base_name: str):
        return {t.lower() for t in re.split(r'[_\\-\\.\\s\\(\\)\\[\\]]+', base_name) if t}

    def _matched_language_tokens(base_name: str, target_lang: str) -> List[str]:
        tokens = _tokenize_filename(base_name)
        markers = _lang_detect_map.get(target_lang, set())
        return [t for t in tokens if t in markers]

    for file_idx, (fpath, original_text, base_name, out_dir, chunks, is_srt) in enumerate(file_chunks_map):
        if getattr(utils, 'stop_requested', False): break
        
        utils.log_queue.put(f"[PROGRESS_FILE] | {file_idx} | {len(file_chunks_map)}\n")
        live_log(f"\n🚀 [BATCH TRANSLATE] File: {base_name} | 🧠 Model: {model_name}")
        
        if not target_langs:
            live_log(f"⏭ No translation needed (no languages selected). Outputting '{base_name}' to editor.")
            clean_text = original_text
            if is_srt:
                clean_text = re.sub(r'(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*\n', '', clean_text)
                clean_text = re.sub(r'\n\n+', '\n', clean_text).strip()
            all_clean_editor_text += f"\n--- {base_name} (ORIGINAL) ---\n{clean_text}\n"
            saved_files.append(fpath) # Сохраняем оригинал
            continue
            
        for target_lang in target_langs:
            if getattr(utils, 'stop_requested', False): break
            
            matched_tokens = _matched_language_tokens(base_name, target_lang)
            if matched_tokens and not force_all_langs:
                token_str = matched_tokens[0]
                live_log(f"[SKIP] {target_lang} skipped: filename token '{token_str.upper()}' indicates it is already {target_lang}. Use the FORCE ALL LANGUAGES checkbox to override.")
                clean_text = original_text
                if is_srt:
                    clean_text = re.sub(r'(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*\n', '', clean_text)
                    clean_text = re.sub(r'\n\n+', '\n', clean_text).strip()
                all_clean_editor_text += f"\n--- {base_name} ({target_lang}) ---\n{clean_text}\n"
                saved_files.append(fpath) # Сохраняем оригинал
                continue
            
            translated_blocks = []
            live_log(f"🌍 Translating to language: {target_lang}")
            
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

                processed_requests += 1 
                e_sec = int(time.time() - start_time)
                utils.log_queue.put(f"[PROGRESS_TRANS] | {processed_requests} | {total_requests} | {e_sec}\n")
                    
                chunk_text_str = "\n\n".join(chunk)
                user_prompt = f"Переведи этот текст на язык: {target_lang}. \n\nТЕКСТ:\n{chunk_text_str}"
                live_log(f"   Processing chunk {idx+1} of {len(chunks)}...")
                
                max_retries = 10 
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
                            if "Ошибка:" in _rt and "недоступны" in _rt:
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
                            max_completion_tokens=8192,
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
                                sub_prompt = f"Переведи этот текст на язык: {target_lang}. \n\nТЕКСТ:\n{single_block}"
                                try:
                                    sub_result = _send_to_api(sub_prompt)
                                    if sub_result:
                                        sub_clean = re.sub(r'<(thought|think)>.*?(<\/\1>|$)\s*', '', sub_result, flags=re.DOTALL).strip()
                                        sub_results.append(sub_clean)
                                        live_log(f"      ✅ Sub-block {sub_idx+1}/{len(chunk)} OK")
                                    else:
                                        sub_results.append(single_block)
                                        live_log(f"      ⚠️ Sub-block {sub_idx+1}/{len(chunk)} — empty response, keeping original")
                                    if sub_idx < len(chunk) - 1: time.sleep(0.5)
                                except Exception as sub_e:
                                    live_log(f"      ❌ Sub-block {sub_idx+1}/{len(chunk)} error: {str(sub_e)[:100]}")
                                    sub_results.append(single_block)
                            if sub_results:
                                translated_blocks.append("\n\n".join(sub_results))
                                success = True
                            break 
                        
                        if "429" in err_str or "too many requests" in err_str.lower() or "rate" in err_str.lower() or ("exhausted" in err_str.lower() and "quota" in err_str.lower()):
                            wait_secs = 60 
                            live_log(f"   ⏳ API limit (429/Quota). Pausing {wait_secs} sec before retry...")
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
                            translated_blocks.append(f"==== ОШИБКА ПЕРЕВОДА БЛОКА ====\n{chunk_text_str}")

                if not success and getattr(utils, 'stop_requested', False): break
                if idx < len(chunks) - 1: 
                    delay = 3.0 if provider == "Local Proxy (127.0.0.1)" else 1.5
                    if utils.interruptible_sleep(delay): break 

            if translated_blocks:
                final_translated_text = "\n\n".join(translated_blocks)
                lang_map = {"Русский": "RU", "English": "EN", "עברית (Hebrew)": "HE"}
                lang_suffix = lang_map.get(target_lang, "TRANS")
                orig_ext = os.path.splitext(fpath)[1] if fpath != "PLAIN_TEXT" else ".txt"
                ext = orig_ext if orig_ext else ".txt"
                
                partial_tag = "_PARTIAL" if getattr(utils, 'stop_requested', False) else ""
                translated_path = os.path.join(out_dir, f"{base_name}_TRANSLATED_{lang_suffix}{partial_tag}{ext}")
                
                try:
                    with open(translated_path, "w", encoding="utf-8") as f: f.write(final_translated_text)
                    saved_files.append(translated_path)
                    
                    clean_text = final_translated_text
                    if is_srt:
                        clean_text = re.sub(r'(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*\n', '', clean_text)
                        clean_text = re.sub(r'\n\n+', '\n', clean_text).strip()
                    all_clean_editor_text += f"\n--- {base_name} ({target_lang}) ---\n{clean_text}\n"
                except Exception as e: live_log(f"❌ File save error: {e}")

    if not getattr(utils, 'stop_requested', False):
        live_log("\n✅ ENTIRE BATCH TRANSLATED!")
        utils.log_queue.put(f"[PROGRESS_FILE] | {len(file_chunks_map)} | {len(file_chunks_map)}\n")
        # Log [RESULT] lines for every translated file written
        for sf in saved_files:
            if "_TRANSLATED_" in sf:
                match = re.search(r'_TRANSLATED_([A-Z]{2,3})', os.path.basename(sf))
                if match:
                    lang_code = match.group(1)
                    live_log(f"[RESULT] {lang_code} -> {sf}")

    status_msg = f"{'⚠️ Interrupted. Partial progress saved' if getattr(utils, 'stop_requested', False) else '✅ Completed'}: {len(saved_files)} files." 
    # 🚀 Возвращаем ТРИ переменные (третья - список путей к SRT через |)
    return status_msg, all_clean_editor_text, "|".join(saved_files)

def check_api(provider: str, current_api_key: str, model_name: str) -> str:
    if not current_api_key and provider != "Local Proxy (127.0.0.1)":
        return "❌ Error: Enter an API key!"
    if not model_name or not model_name.strip():
        return "❌ Error: No model selected! Click 🔄 to refresh models or enter a model name manually."
        
    try:
        if provider == "Google Gemini":
            if not GEMINI_READY: raise ImportError("Module google.generativeai is not installed.")
            genai.configure(api_key=current_api_key)
            model = genai.GenerativeModel(model_name=model_name)
            model.generate_content("Ping")
            _save_last_model(provider, model_name)
            return f"✅ Success! Connection to {provider} (model {model_name}) works."
            
        elif provider == "Local Proxy (127.0.0.1)":
            import requests
            try:
                requests.get("http://127.0.0.1:8080/", timeout=5.0)
            except requests.exceptions.ConnectionError:
                return "❌ Error: Proxy server is not running! Start it on port 8080."
            except Exception:
                pass  
            resp = requests.post("http://127.0.0.1:8080/v1/messages", json={"model": model_name, "system": "ping", "messages": [{"role": "user", "content": "Ping"}]}, timeout=180.0)
            if resp.status_code == 401: return "❌ Error: Google token expired! Run 'gemini login'."
            resp.raise_for_status()
            _save_last_model(provider, model_name)
            return f"✅ Success! Local Proxy responds normally."
            
        elif provider == "Google Studio (Gemma 4)":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=current_api_key)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            _save_last_model(provider, model_name)
            return f"✅ Success! Connection to {provider} works."
            
        elif provider == "Groq (OSS 120b)":
            if not GROQ_READY: raise ImportError("Module groq is not installed. Run: pip install groq")
            groq_client = Groq(api_key=current_api_key)
            groq_client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            _save_last_model(provider, model_name)
            return f"✅ Success! Connection to Groq (model {model_name}) works."
            
        elif provider == "OpenRouter":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            headers = {"HTTP-Referer": "http://localhost", "X-Title": "AT-Whisper"}
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=current_api_key, default_headers=headers)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            _save_last_model(provider, model_name)
            return f"✅ Success! Connection to OpenRouter works."

        elif provider == "OmniRoute":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=OMNIROUTE_BASE_URL, api_key=current_api_key)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            _save_last_model(provider, model_name)
            return f"✅ Success! Connection to OmniRoute works."

        elif provider == "Freeway":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=FREEWAY_BASE_URL, api_key=(current_api_key or FREEWAY_DEFAULT_KEY))
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            _save_last_model(provider, model_name)
            return f"✅ Success! Connection to Freeway works."

        elif provider == "Mistral":
            if not OPENAI_READY: raise ImportError("Module openai is not installed.")
            client = OpenAI(base_url=MISTRAL_BASE_URL, api_key=current_api_key)
            client.chat.completions.create(model=model_name, messages=[{"role": "user", "content": "Ping"}], max_tokens=2)
            _save_last_model(provider, model_name)
            return f"✅ Success! Connection to Mistral works."
            
    except Exception as e:
        return f"❌ CONNECTION ERROR: {str(e)}"


def fetch_models(provider: str, api_key: str) -> list:
    """
    Dynamically fetch available models from the selected provider.
    Returns a sorted list of model IDs (strings). On failure returns empty list.
    """
    if not api_key and provider != "Local Proxy (127.0.0.1)":
        return []

    try:
        if provider == "Local Proxy (127.0.0.1)":
            import requests
            resp = requests.get("http://127.0.0.1:8080/v1/models", timeout=15.0)
            resp.raise_for_status()
            data = resp.json()
            models = []
            if "data" in data:
                models = [m.get("id", "") for m in data["data"] if m.get("id")]
            elif isinstance(data, list):
                models = [m.get("id", "") for m in data if m.get("id")]
            return sorted(models)

        elif provider in ("Google Gemini", "Google Studio (Gemma 4)"):
            # Use OpenAI-compatible endpoint for Google Studio
            if not OPENAI_READY:
                return []
            if provider == "Google Studio (Gemma 4)":
                client = OpenAI(base_url="https://generativelanguage.googleapis.com/v1beta/openai/", api_key=api_key)
            else:
                # Google Gemini via genai
                if not GEMINI_READY:
                    return []
                genai.configure(api_key=api_key)
                return sorted([m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods])
            models = [m.id for m in client.models.list().data]
            return sorted(models)

        elif provider == "Groq (OSS 120b)":
            if not OPENAI_READY:
                return []
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
            models = [m.id for m in client.models.list().data]
            return sorted(models)

        elif provider == "OpenRouter":
            if not OPENAI_READY:
                return []
            headers = {"HTTP-Referer": "http://localhost", "X-Title": "AT-Whisper"}
            client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, default_headers=headers)
            models = [m.id for m in client.models.list().data]
            return sorted(models)

        elif provider == "OmniRoute":
            if not OPENAI_READY:
                return []
            client = OpenAI(base_url=OMNIROUTE_BASE_URL, api_key=api_key)
            models = [m.id for m in client.models.list().data]
            return sorted(models)

        elif provider == "Freeway":
            if not OPENAI_READY:
                return []
            client = OpenAI(base_url=FREEWAY_BASE_URL, api_key=(api_key or FREEWAY_DEFAULT_KEY))
            models = [m.id for m in client.models.list().data]
            return sorted(models)

        elif provider == "Mistral":
            if not OPENAI_READY:
                return []
            client = OpenAI(base_url=MISTRAL_BASE_URL, api_key=api_key)
            models = [m.id for m in client.models.list().data]
            return sorted(models)

        else:
            return []

    except Exception as e:
        logging.warning(f"[FETCH_MODELS] Failed for {provider}: {str(e)[:200]}")
        return []