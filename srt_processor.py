import os
import re
import json
import csv
import glob
import time
from typing import List, Dict, Any, Tuple

import gradio as gr # Gradio is imported here only for gr.update; revisit if srt_processor drops Gradio

from utils import log_to_terminal, sanitize_srt_text, interruptible_sleep, log_queue, clean_srt_text
from config import DEFAULT_OUTPUT_DIR

# ==============================================================================
# 9. SYSTEM UTILITIES AND AUTO-CLEANER (SANITIZER) (some functions)
# ==============================================================================
def chunk_text(text: str, chunk_size: int, by_paragraphs: bool = False,
               max_chars: int = 0) -> List[List[str]]:
    """Batch whole subtitle cues, never separate an index from its timestamp.

    Character limits are soft for a single oversized cue: it stays intact.
    Existing paragraph callers retain their original count-based behavior.
    """
    if chunk_size < 1:
        raise ValueError('chunk_size must be positive')
    normalized = text.replace('\r\n', '\n').replace('\r', '\n').strip('\ufeff\n ')
    if not normalized:
        return []
    if by_paragraphs:
        blocks = re.split(r'\n\s*\n', normalized)
    else:
        boundary = r'(?m)(?=^\d+\s*\n\d{2,}:\d{2}:\d{2}[,.]\d{3}\s*-->)'
        blocks = re.split(boundary, normalized)
    blocks = [block.strip() for block in blocks if block.strip()]
    chunks, current, length = [], [], 0
    for block in blocks:
        added = len(block) + (2 if current else 0)
        if current and (len(current) >= chunk_size or (max_chars > 0 and length + added > max_chars)):
            chunks.append(current)
            current, length = [], 0
        length += len(block) + (2 if current else 0)
        current.append(block)
    if current:
        chunks.append(current)
    return chunks


# ==============================================================================
# 11. BULLETPROOF PARSER AND EXTRACTOR (JSON + CSV EXPORT)
# ==============================================================================
def validate_srt_translation(original: str, translated: str) -> str:
    """Require complete cues with unchanged IDs and timestamps before saving."""
    translated = re.sub(r'^```(?:srt)?\s*\n(.*?)\n```\s*$', r'\1',
                        translated.strip(), flags=re.DOTALL | re.IGNORECASE)

    def structure(text):
        cues = [cue for batch in chunk_text(text, 1) for cue in batch]
        if not cues:
            raise ValueError('Subtitle response contains no cues')
        identities = []
        pattern = (r'(\d+)\n(\d{2,}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*'
                   r'(\d{2,}:\d{2}:\d{2}[,.]\d{3})\n(.+)')
        for cue in cues:
            match = re.fullmatch(pattern, cue, flags=re.DOTALL)
            if not match or not match.group(4).strip():
                raise ValueError('Subtitle response contains an incomplete cue')
            identities.append(tuple(value.replace('.', ',') for value in match.group(1, 2, 3)))
        return identities

    if structure(original) != structure(translated):
        raise ValueError('Subtitle response changed or omitted cue IDs/timestamps')
    return translated.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff').strip()


def robust_parse_srt(content: str, lang_key: str, dict_data: dict, is_srt: bool = True) -> None:
    if is_srt:
        content = sanitize_srt_text(content)
    blocks = re.split(r'\n\s*\n', content.strip())

    for idx, block in enumerate(blocks):
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if not lines:
            continue

        idx_line = None
        timecode_line = None
        text_lines = []

        if is_srt:
            for line in lines:
                if line.isdigit() and not idx_line: 
                    idx_line = line
                elif re.search(r'^\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}$', line) and not timecode_line:
                    timecode_line = line
                elif idx_line and timecode_line:
                    text_lines.append(line)
        
        if is_srt and idx_line and timecode_line and text_lines:
            clean_idx = idx_line
            text = " ".join(text_lines)
            if clean_idx not in dict_data: dict_data[clean_idx] = {"id": clean_idx, "time": timecode_line}
            dict_data[clean_idx][lang_key] = text
        else:
            # Fallback for plain text or broken SRT
            if is_srt:
                text = " ".join(lines)
            else:
                text = " ".join(lines)
            
            clean_idx = str(idx + 1)
            timecode_line = f"00:00:00,000 --> 00:00:00,000" if is_srt else ""
            if clean_idx not in dict_data: dict_data[clean_idx] = {"id": clean_idx, "time": timecode_line}
            dict_data[clean_idx][lang_key] = text

def export_to_json_dict(srt_local_path: str, custom_srt_files: List[Any], plain_text: str, hidden_actual_out_dir: str, hidden_srt_paths: str) -> Tuple[str, List[str]]:
    global log_queue # Use the global log queue from utils
    
    # Global progress variables from utils (if they aren't global here yet)
    from utils import current_percent, time_elapsed, time_remaining, audio_speed, current_action, stop_requested
    global current_percent, time_elapsed, time_remaining, audio_speed, current_action, stop_requested

    stop_requested = False
    current_action = "Creating dictionaries (JSON + CSV)"
    current_percent = 0; time_elapsed = "00:00"; time_remaining = "00:00"; audio_speed = "Parsing"
    start_time = time.time()

    saved_jsons = []
    report_lines = [] 
    actual_bases = set()
    scan_dirs = set()
    all_clean_editor_text = ""
    
    valid_exts = ('.srt', '.txt', '.csv', '.json', '.pdf', '.md')
    srt_local_path = (srt_local_path or "").strip()
    if srt_local_path:
        paths = [p.strip().strip('"').strip("'") for p in srt_local_path.split('|') if p.strip()]
        for p in paths:
            if os.path.isdir(p):
                scan_dirs.add(p)
                for f in glob.glob(os.path.join(p, '*.*')):
                    if f.lower().endswith(valid_exts):
                        fname = os.path.basename(f)
                        match = re.search(r'^(.*)_TRANSLATED_[A-Z]+(_PARTIAL)?\.[a-z]+$', fname, re.I)
                        if match: 
                            actual_bases.add(match.group(1))
                        elif f.lower().endswith(('.srt', '.md')): 
                            actual_bases.add(os.path.splitext(fname)[0])
            elif os.path.isfile(p) and p.lower().endswith(valid_exts):
                scan_dirs.add(os.path.dirname(os.path.abspath(p)))
                fname = os.path.basename(p)
                match = re.search(r'^(.*)_TRANSLATED_[A-Z]+(_PARTIAL)?\.[a-z]+$', fname, re.I)
                if match: actual_bases.add(match.group(1))
                else: actual_bases.add(os.path.splitext(fname)[0])
                
    if custom_srt_files:
        for file_obj in custom_srt_files:
            fpath = file_obj if isinstance(file_obj, str) else getattr(file_obj, 'name', str(file_obj))
            if fpath.lower().endswith(valid_exts):
                if "Temp" in fpath or "temp" in fpath: scan_dirs.add(DEFAULT_OUTPUT_DIR) 
                else: scan_dirs.add(os.path.dirname(os.path.abspath(fpath)))
                fname = os.path.basename(fpath)
                match = re.search(r'^(.*)_TRANSLATED_[A-Z]+(_PARTIAL)?\.[a-z]+$', fname, re.I)
                if match: actual_bases.add(match.group(1))
                else: actual_bases.add(os.path.splitext(fname)[0])
                
    if not actual_bases and hidden_srt_paths:
        for p in hidden_srt_paths.split('|'):
            if p.strip() and os.path.isfile(p.strip()) and p.strip().lower().endswith(valid_exts): 
                if "Temp" in p.strip() or "temp" in p.strip(): scan_dirs.add(DEFAULT_OUTPUT_DIR)
                else: scan_dirs.add(os.path.dirname(os.path.abspath(p.strip())))
                actual_bases.add(os.path.splitext(os.path.basename(p.strip()))[0])

    if not actual_bases:
        actual_bases.add("Text_Translation")
        if hidden_actual_out_dir: scan_dirs.add(hidden_actual_out_dir)

    if not scan_dirs: scan_dirs.add(DEFAULT_OUTPUT_DIR)

    total_bases = len(actual_bases)
    processed = 0

    for base in actual_bases:
        if stop_requested: 
            log_queue.put("\n⚠️ Сборка словарей прервана.\n")
            break
            
        dict_data = {}
        langs_found = set()
        
        for scan_dir in scan_dirs:
            search_pattern = os.path.join(glob.escape(scan_dir), f"{glob.escape(base)}*.*")
            related_files = [f for f in glob.glob(search_pattern) if os.path.isfile(f) and f.lower().endswith(valid_exts)]
            
            for fpath in related_files:
                fname = os.path.basename(fpath)
                lang_key = "ORIGINAL"
                match = re.search(r'_TRANSLATED_([A-Z]+)(_PARTIAL)?\.[a-z]+$', fname, re.I)
                
                if match: 
                    lang_key = match.group(1).upper()
                elif fname.startswith(f"{base}.") or fname.startswith(f"{base}_PARTIAL."): 
                    lang_key = "ORIGINAL"
                else:
                    continue
                    
                try:
                    with open(fpath, 'r', encoding='utf-8') as f: content = f.read()
                    
                    # 1) Generate a clean plain-text sidecar during extraction.
                    clean_text = clean_srt_text(content)
                    
                    clean_txt_path = os.path.join(scan_dir, f"{os.path.splitext(fname)[0]}_CLEAN.txt")
                    with open(clean_txt_path, 'w', encoding='utf-8') as f:
                        f.write(clean_text)
                    if clean_txt_path not in saved_jsons:
                        saved_jsons.append(clean_txt_path)
                        
                    all_clean_editor_text += f"\n--- {fname} ({lang_key}) ---\n{clean_text}\n"

                    # 2) PARSING FOR THE DICTIONARY (WITH TIMECODES FOR STITCHING)
                    is_srt = fname.lower().endswith('.srt')
                    robust_parse_srt(content, lang_key, dict_data, is_srt=is_srt)
                    langs_found.add(lang_key)
                except Exception as e: 
                    log_to_terminal(f"Parsing error {fname}: {e}")
            
        if dict_data:
            def safe_sort_key(x):
                val = str(x.get('id', ''))
                if val.isdigit(): return (0, int(val), val)
                return (1, 0, val)
                    
            sorted_list = sorted(dict_data.values(), key=safe_sort_key)
            
            # --- STRIP THE JUNK (REMOVE ID AND TIME FROM FINAL FILES) ---
            clean_export_list = [{k: v for k, v in item.items() if k not in ["id", "time"]} for item in sorted_list]

            target_dir = list(scan_dirs)[0] if scan_dirs else DEFAULT_OUTPUT_DIR
            p_tag = "_PARTIAL" if stop_requested else ""
            
            # --- SAVE JSON ---
            json_path = os.path.join(target_dir, f"{base}_MULTILANG_DICT{p_tag}.json")
            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(clean_export_list, f, ensure_ascii=False, indent=4)
                saved_jsons.append(json_path)
            except Exception as e: log_to_terminal(f"JSON save error: {e}")
                
            # --- CSV SAVE (for F5-TTS and Excel) ---
            csv_path = os.path.join(target_dir, f"{base}_MULTILANG_DICT{p_tag}.csv")
            try:
                lang_headers = set()
                for item in clean_export_list:
                    for k in item.keys():
                        lang_headers.add(k)
                
                # Sort the headers so ORIGINAL comes first
                lang_list = list(lang_headers)
                if "ORIGINAL" in lang_list:
                    lang_list.remove("ORIGINAL")
                    lang_list.insert(0, "ORIGINAL")
                    
                headers = lang_list
                
                # Use utf-8-sig (with BOM) so Excel reads Cyrillic and Hebrew correctly
                with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=headers, quoting=csv.QUOTE_MINIMAL)
                    # HEADERS REMOVED (AT THE USER'S REQUEST)
                    # writer.writeheader() 
                    writer.writerows(clean_export_list)
                saved_jsons.append(csv_path)
                
                report_lines.append(f"✅ {base} -> Языки: {', '.join(langs_found)}")
            except Exception as e: 
                log_to_terminal(f"CSV save error: {e}")

        processed += 1
        current_percent = int((processed / total_bases) * 100) if total_bases > 0 else 100
        e_sec = int(time.time() - start_time)
        time_elapsed = f"{e_sec//60:02d}:{e_sec%60:02d}"
        if interruptible_sleep(0.05): break
    
    if not saved_jsons and plain_text and plain_text.strip():
        try:
            lines = plain_text.strip().split('\n')
            dict_data = [{"text": line.strip()} for i, line in enumerate(lines) if line.strip()]
            target_dir = list(scan_dirs)[0] if scan_dirs else DEFAULT_OUTPUT_DIR
            
            json_path = os.path.join(target_dir, "Text_Translation_DICT.json")
            with open(json_path, 'w', encoding='utf-8') as f: json.dump(dict_data, f, ensure_ascii=False, indent=4)
            saved_jsons.append(json_path)
            
            csv_path = os.path.join(target_dir, "Text_Translation_DICT.csv")
            with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=["text"], quoting=csv.QUOTE_MINIMAL)
                # HEADERS REMOVED
                writer.writerows(dict_data)
            saved_jsons.append(csv_path)
            
            report_lines.append("✅ Text_Translation -> Сохранен (JSON + CSV).")
            current_percent = 100
        except Exception: pass

    current_action = "Остановлено" if stop_requested else "Готово"
    
    if saved_jsons: 
        status_msg = f"{ '⚠️ Выполнено частично' if stop_requested else '✅'} Созданы словари: {len(saved_jsons)//2} видео\n\n"
        status_msg += "\n".join(report_lines)
        return status_msg, saved_jsons, all_clean_editor_text
        
    return "⚠️ Нет файлов для экстракции (или не найдены переводы)!", [], ""
