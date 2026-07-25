import os
import re
import json
import csv
import glob
import time
from typing import List, Dict, Any, Tuple

import gradio as gr # Импорт Gradio здесь только для gr.update, пересмотреть, если srt_processor будет без Gradio

from utils import log_to_terminal, sanitize_srt_text, interruptible_sleep, log_queue # Импортируем нужные утилиты
from config import DEFAULT_OUTPUT_DIR # Импортируем DEFAULT_OUTPUT_DIR

# ==============================================================================
# 9. СИСТЕМНЫЕ УТИЛИТЫ И АВТО-ОЧИСТИТЕЛЬ (SANITIZER) (часть функций)
# ==============================================================================
def chunk_text(text: str, chunk_size: int, by_paragraphs: bool = False) -> List[List[str]]:
    if by_paragraphs:
        blocks = text.strip().split('\n\n')
    else:
        blocks = text.strip().split('\n') # Для SRT, где каждый блок - это строка субтитров
        
    # Удаляем пустые строки/блоки, которые могли появиться из-за split
    blocks = [block for block in blocks if block.strip()]

    # Собираем блоки в чанки, стараясь не разбивать SRT-блоки (номер, таймкод, текст)
    # Для SRT-режима, chunk_size - это количество *полных* SRT-блоков.
    # Для обычного текста, chunk_size - это количество абзацев/строк.

    if by_paragraphs:
        # Если режим по абзацам (для обычного текста), просто делим список абзацев
        return [blocks[i:i + chunk_size] for i in range(0, len(blocks), chunk_size)]
    else:
        # Для SRT-режима, мы предполагаем, что text уже представляет собой последовательность SRT-блоков,
        # разделённых \n\n. Функция sanitize_srt_text уже убирает мусор. 
        # Здесь просто делим полученные блоки на части.
        # Каждый элемент в `blocks` уже является полным SRT-блоком (или его частью до \n\n)
        chunks = []
        current_chunk = []
        srt_block_pattern = re.compile(r'^\d+$|^\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}$')

        temp_blocks = []
        current_srt_block_lines = []
        block_num = 0

        # Пересобираем в логические SRT-блоки, чтобы не разбивать их
        for line in blocks:
            if srt_block_pattern.match(line):
                # Если это номер блока или таймкод, значит, мы начинаем новый SRT-блок
                if current_srt_block_lines:
                    temp_blocks.append('\n'.join(current_srt_block_lines))
                    current_srt_block_lines = []
                current_srt_block_lines.append(line)
                if line.isdigit(): # Это номер блока, увеличиваем счетчик
                    block_num = int(line)
            elif line.strip(): # Это строка текста, добавляем к текущему SRT-блоку
                current_srt_block_lines.append(line)

        if current_srt_block_lines:
            temp_blocks.append('\n'.join(current_srt_block_lines))

        # Теперь temp_blocks содержит целые SRT-блоки, которые можно делить по chunk_size
        for i in range(0, len(temp_blocks), chunk_size):
            chunks.append(temp_blocks[i:i + chunk_size])

        return chunks


# ==============================================================================
# 11. БРОНЕБОЙНЫЙ ПАРСЕР И ЭКСТРАКТОР (JSON + CSV EXPORT)
# ==============================================================================
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
    global log_queue # Используем глобальную очередь логов из utils
    
    # Глобальные переменные прогресса из utils (если они еще не глобальные здесь)
    from utils import current_percent, time_elapsed, time_remaining, audio_speed, current_action, stop_requested
    global current_percent, time_elapsed, time_remaining, audio_speed, current_action, stop_requested

    stop_requested = False
    current_action = "Создание словарей (JSON + CSV)"
    current_percent = 0; time_elapsed = "00:00"; time_remaining = "00:00"; audio_speed = "Парсинг"
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
                    
                    # 1) АВТОМАТИЧЕСКАЯ ГЕНЕРАЦИЯ ЧИСТОГО TXT ПРИ ЭКСТРАКЦИИ
                    clean_text = re.sub(r'(?m)^\d+\s*\n\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*\n', '', content)
                    clean_text = re.sub(r'<[^>]+>', '', clean_text)
                    clean_text = re.sub(r'\n\n+', '\n', clean_text).strip()
                    
                    clean_txt_path = os.path.join(scan_dir, f"{os.path.splitext(fname)[0]}_CLEAN.txt")
                    with open(clean_txt_path, 'w', encoding='utf-8') as f:
                        f.write(clean_text)
                    if clean_txt_path not in saved_jsons:
                        saved_jsons.append(clean_txt_path)
                        
                    all_clean_editor_text += f"\n--- {fname} ({lang_key}) ---\n{clean_text}\n"

                    # 2) ПАРСИНГ ДЛЯ СЛОВАРЯ (С ТАЙМКОДАМИ ДЛЯ СШИВКИ)
                    is_srt = fname.lower().endswith('.srt')
                    robust_parse_srt(content, lang_key, dict_data, is_srt=is_srt)
                    langs_found.add(lang_key)
                except Exception as e: 
                    log_to_terminal(f"Ошибка парсинга {fname}: {e}")
            
        if dict_data:
            def safe_sort_key(x):
                val = str(x.get('id', ''))
                if val.isdigit(): return (0, int(val), val)
                return (1, 0, val)
                    
            sorted_list = sorted(dict_data.values(), key=safe_sort_key)
            
            # --- ВЫРЕЗАЕМ МУСОР (УДАЛЯЕМ ID И TIME ИЗ ФИНАЛЬНЫХ ФАЙЛОВ) ---
            clean_export_list = [{k: v for k, v in item.items() if k not in ["id", "time"]} for item in sorted_list]

            target_dir = list(scan_dirs)[0] if scan_dirs else DEFAULT_OUTPUT_DIR
            p_tag = "_PARTIAL" if stop_requested else ""
            
            # --- СОХРАНЕНИЕ JSON ---
            json_path = os.path.join(target_dir, f"{base}_MULTILANG_DICT{p_tag}.json")
            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(clean_export_list, f, ensure_ascii=False, indent=4)
                saved_jsons.append(json_path)
            except Exception as e: log_to_terminal(f"Ошибка сохранения JSON: {e}")
                
            # --- СОХРАНЕНИЕ CSV (Для F5-TTS и Excel) ---
            csv_path = os.path.join(target_dir, f"{base}_MULTILANG_DICT{p_tag}.csv")
            try:
                lang_headers = set()
                for item in clean_export_list:
                    for k in item.keys():
                        lang_headers.add(k)
                
                # Сортируем заголовки, чтобы ORIGINAL был первым
                lang_list = list(lang_headers)
                if "ORIGINAL" in lang_list:
                    lang_list.remove("ORIGINAL")
                    lang_list.insert(0, "ORIGINAL")
                    
                headers = lang_list
                
                # Используем utf-8-sig (с BOM), чтобы Excel корректно читал кириллицу и иврит
                with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=headers, quoting=csv.QUOTE_MINIMAL)
                    # ЗАГОЛОВКИ УБРАНЫ (ПО ЗАПРОСУ ПОЛЬЗОВАТЕЛЯ)
                    # writer.writeheader() 
                    writer.writerows(clean_export_list)
                saved_jsons.append(csv_path)
                
                report_lines.append(f"✅ {base} -> Языки: {', '.join(langs_found)}")
            except Exception as e: 
                log_to_terminal(f"Ошибка сохранения CSV: {e}")

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
                # ЗАГОЛОВКИ УБРАНЫ
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
