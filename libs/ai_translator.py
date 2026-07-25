import os
import time
import glob
import traceback

def chunk_text(text, chunk_size, by_paragraphs=False):
    """Умная нарезка текста или субтитров на куски"""
    if by_paragraphs:
        blocks = text.strip().split('\n\n')
    else:
        blocks = text.strip().split('\n\n') # Для SRT тоже используем двойной перенос
    
    return [blocks[i:i + chunk_size] for i in range(0, len(blocks), chunk_size)]

def translate_content(provider, api_key, target_langs, model_name, sys_prompt, custom_srt_file, hidden_out_dir, hidden_base_name, translate_mode, plain_text_input, log_func):
    if not api_key:
        return "❌ Ошибка: Не указан API Key!", None
        
    if not target_langs:
        return "❌ Ошибка: Выберите хотя бы один язык для перевода!", None

    original_text = ""
    out_dir_for_save = ""
    final_base_name = ""
    is_srt_mode = (translate_mode == "Субтитры (.srt)")
    
    # 1. ЧТЕНИЕ ИСХОДНИКА
    if is_srt_mode:
        if custom_srt_file is not None:
            try:
                with open(custom_srt_file.name, 'r', encoding='utf-8') as f: original_text = f.read()
                out_dir_for_save = os.path.dirname(custom_srt_file.name)
                final_base_name = os.path.splitext(os.path.basename(custom_srt_file.name))[0]
            except Exception as e: return f"❌ Ошибка чтения загруженного файла: {e}", None
        else:
            if not hidden_out_dir or not hidden_base_name:
                return "❌ Ошибка: Выполните транскрибацию или загрузите свой .srt файл!", None
            srt_pattern = os.path.join(hidden_out_dir, f"{hidden_base_name}*.srt")
            found_srt = glob.glob(srt_pattern)
            if not found_srt: return "❌ Ошибка: Не найден SRT файл от Whisper.", None
            try:
                with open(found_srt[0], 'r', encoding='utf-8') as f: original_text = f.read()
                out_dir_for_save = hidden_out_dir; final_base_name = hidden_base_name
            except Exception as e: return f"❌ Ошибка чтения файла Whisper: {e}", None
    else:
        # Режим простого текста
        if not plain_text_input.strip():
            return "❌ Ошибка: Текстовое поле пустое!", None
        original_text = plain_text_input
        out_dir_for_save = hidden_out_dir if hidden_out_dir else os.path.expanduser("~")
        final_base_name = hidden_base_name if hidden_base_name else "Plain_Text"

    # 2. НАРЕЗКА НА КУСКИ
    chunk_size = 60 if is_srt_mode else 30
    chunks = chunk_text(original_text, chunk_size, by_paragraphs=not is_srt_mode)
    
    log_func(f"=== СТАРТ ПЕРЕВОДА ({provider} - {model_name}) ===")
    log_func(f"Файл разбит на {len(chunks)} частей.")
    
    saved_files = []
    
    # Подключаем библиотеки только при необходимости
    try:
        if provider == "Google Gemini":
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name=model_name, system_instruction=sys_prompt)
        elif provider in ["OpenRouter", "Google Studio (Gemma 4)"]:
            from openai import OpenAI
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai/" if provider == "Google Studio (Gemma 4)" else "https://openrouter.ai/api/v1"
            client = OpenAI(base_url=base_url, api_key=api_key)
    except Exception as e:
        return f"❌ Ошибка инициализации API: {e}", None

    # 3. ЦИКЛ ПЕРЕВОДА ДЛЯ КАЖДОГО ЯЗЫКА
    for target_lang in target_langs:
        translated_blocks = []
        log_func(f"\n🌍 Перевод на язык: {target_lang}")
        
        for idx, chunk in enumerate(chunks):
            chunk_text_str = "\n\n".join(chunk)
            prompt = f"Переведи этот текст на язык: {target_lang}. \n\nТЕКСТ:\n{chunk_text_str}"
            log_func(f"Обработка куска {idx+1} из {len(chunks)}...")
            
            try:
                if provider == "Google Gemini":
                    response = model.generate_content(prompt)
                    result_text = response.text
                elif provider in ["OpenRouter", "Google Studio (Gemma 4)"]:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": sys_prompt},
                            {"role": "user", "content": prompt}
                        ]
                    )
                    result_text = response.choices[0].message.content
                    
                if result_text:
                    translated_blocks.append(result_text.strip())
                else:
                    raise Exception("API вернул пустой ответ")
                    
                if idx < len(chunks) - 1:
                    time.sleep(3) # Пауза между кусками
                    
            except Exception as e:
                log_func(f"❌ ОШИБКА перевода куска {idx+1}: {e}")
                translated_blocks.append(f"==== ОШИБКА ПЕРЕВОДА БЛОКА ====\n{chunk_text_str}")

        # Сохранение файла для текущего языка
        final_translated_text = "\n\n".join(translated_blocks)
        
        lang_map = {"Русский": "RU", "English": "EN", "עברית (Hebrew)": "HE", "Українська": "UK"}
        lang_suffix = lang_map.get(target_lang, "TRANS")
        ext = ".srt" if is_srt_mode else ".txt"
        
        translated_path = os.path.join(out_dir_for_save, f"{final_base_name}_TRANSLATED_{lang_suffix}{ext}")
        
        try:
            with open(translated_path, "w", encoding="utf-8") as f:
                f.write(final_translated_text)
            log_func(f"Успешно сохранено: {translated_path}")
            saved_files.append(translated_path)
        except Exception as e:
            log_func(f"❌ Ошибка сохранения файла: {e}")

    final_msg = f"✅ Перевод завершен! Сохранено файлов: {len(saved_files)}.\n" + "\n".join(saved_files)
    return final_msg, saved_files if saved_files else None