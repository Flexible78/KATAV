import os
import subprocess
import sys
import logging
from typing import List

# ==============================================================================
# 8. ВЗАИМОДЕЙСТВИЕ С ОС И ДИАЛОГАМИ (ПРЯМЫЕ ПУТИ И БУФЕР)
# ==============================================================================
def read_clipboard_text() -> str:
    """Return raw clipboard text, no filesystem filtering."""
    try:
        CREATE_NO_WINDOW = 0x08000000
        p = subprocess.Popen(
            ["powershell", "-NoProfile", "-command", "Get-Clipboard -Raw"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=CREATE_NO_WINDOW
        )
        out, _ = p.communicate(timeout=3)
        if out is not None:
            return out
    except Exception:
        pass

    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        clip_text = root.clipboard_get()
        root.destroy()
        return clip_text or ""
    except Exception:
        pass

    return ""


def read_clipboard_paths() -> str:
    paths = []
    
    try:
        CREATE_NO_WINDOW = 0x08000000
        p = subprocess.Popen(
            ["powershell", "-command", "(Get-Clipboard -Format FileDropList).FullName"], 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=CREATE_NO_WINDOW
        )
        out, err = p.communicate(timeout=2)
        if out and out.strip():
            for line in out.strip().split('\n'):
                clean = line.strip()
                if clean and os.path.exists(clean):
                    paths.append(clean)
    except Exception:
        pass

    if not paths:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            clip_text = root.clipboard_get()
            root.destroy()
            if clip_text:
                for line in clip_text.split('\n'):
                    clean = line.strip().strip('"').strip("'")
                    if clean and os.path.exists(clean):
                        paths.append(clean)
        except Exception:
            pass

    return " | ".join(paths) if paths else ""

def _run_tk_dialog(dialog_code: str) -> str:
    """Изолированный запуск Tkinter в отдельном процессе"""
    code = f"""
import tkinter as tk
from tkinter import filedialog
import sys
root = tk.Tk()
root.withdraw()
root.attributes('-topmost', True)
{dialog_code}
"""
    try:
        CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run(
            [sys.executable, "-c", code], 
            text=True, capture_output=True, 
            creationflags=CREATE_NO_WINDOW, timeout=120
        )
        if result.stderr and result.stderr.strip():
            logging.error(f"[TK_DIALOG] stderr: {result.stderr.strip()}")
        if result.returncode != 0:
            logging.error(f"[TK_DIALOG] Код возврата: {result.returncode}")
            return ""
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logging.error("[TK_DIALOG] Таймаут (120 сек)")
        return ""
    except Exception as e:
        logging.error(f"[TK_DIALOG] Исключение: {e}")
        return ""

def open_folder_dialog() -> str:
    return _run_tk_dialog('print(filedialog.askdirectory(title="Select a folder"))')

def open_files_batch_dialog() -> str:
    code = '''
res = filedialog.askopenfilenames(title="Select media files", filetypes=[("Media Files", "*.mp4 *.mkv *.avi *.mp3 *.wav *.m4a *.flac *.ogg"), ("All Files", "*.*")])
print(" | ".join(res) if res else "")
'''
    return _run_tk_dialog(code)

def open_dir_batch_dialog() -> str:
    return _run_tk_dialog('print(filedialog.askdirectory(title="Select media folder"))')

def open_srt_batch_dialog() -> str:
    code = '''
res = filedialog.askopenfilenames(title="Select text/SRT files", filetypes=[("Text/Subtitles", "*.srt *.txt *.csv *.json *.pdf *.md"), ("All Files", "*.*")])
print(" | ".join(res) if res else "")
'''
    return _run_tk_dialog(code)

def open_dir_srt_dialog() -> str:
    return _run_tk_dialog('print(filedialog.askdirectory(title="Select text/SRT folder"))')

def save_edited_text_dialog(text: str, base_name: str, actual_out_dir: str, save_format: str = "txt") -> str:
    if not text or not text.strip(): 
        logging.warning("[SAVE] Попытка сохранить пустой текст")
        return "⚠️ Текст пуст!"
    
    b_name = base_name.split('|')[0] if base_name else "Текст_перевода"
    ext = save_format if save_format else "txt"
    default_filename = f"{b_name}_EDITED.{ext}"
    
    initial_dir = actual_out_dir.replace('\\', '/') if actual_out_dir else os.path.expanduser("~").replace('\\', '/')
    
    logging.info(f"[SAVE] Формат: {ext} | Файл: {default_filename} | Папка: {initial_dir}")
    
    try:
        if ext == "csv":
            import csv, io
            output = io.StringIO()
            writer = csv.writer(output, quoting=csv.QUOTE_ALL)
            writer.writerow(["№", "Текст"])
            for i, line in enumerate(text.strip().split('\n'), 1):
                if line.strip():
                    writer.writerow([i, line.strip()])
            save_text = output.getvalue()
        elif ext == "json":
            import json as json_mod
            lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
            from datetime import datetime
            data = {
                "source": b_name,
                "exported_at": datetime.now().isoformat(),
                "total_lines": len(lines),
                "content": lines
            }
            save_text = json_mod.dumps(data, ensure_ascii=False, indent=2)
        elif ext == "md":
            save_text = f"# {b_name}\n\n{text}"
        else:
            save_text = text
        logging.info(f"[SAVE] Текст сконвертирован в {ext.upper()} ({len(save_text)} символов)")
    except Exception as e:
        logging.error(f"[SAVE] Ошибка конвертации в {ext}: {e}")
        return f"❌ Ошибка конвертации в {ext.upper()}: {e}"
    
    import tempfile
    temp_path = os.path.join(tempfile.gettempdir(), f"temp_save.{ext}").replace('\\', '/')
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(save_text)
        logging.info(f"[SAVE] Временный файл создан: {temp_path}")
    except Exception as e:
        logging.error(f"[SAVE] Ошибка создания временного файла: {e}")
        return f"❌ Ошибка записи временного файла: {e}"
    
    filetypes_map = {
        "txt": '("Текстовые файлы", "*.txt"), ("Все файлы", "*.*")',
        "md":  '("Markdown", "*.md"), ("Все файлы", "*.*")',
        "csv": '("CSV таблицы", "*.csv"), ("Все файлы", "*.*")',
        "json": '("JSON файлы", "*.json"), ("Все файлы", "*.*")',
    }
    ft = filetypes_map.get(ext, '("Все файлы", "*.*")')
    
    code = f'''
import os, shutil
from tkinter import filedialog
res = filedialog.asksaveasfilename(title="Save text as...", initialdir="{initial_dir}", initialfile="{default_filename}", defaultextension=".{ext}", filetypes=[{ft}])
if res:
    shutil.copy2("{temp_path}", res)
    print(res)
else:
    print("")
'''
    logging.info(f"[SAVE] Открываю диалог сохранения...")
    saved_path = _run_tk_dialog(code)
    
    try: os.remove(temp_path)
    except: pass
    
    if saved_path:
        logging.info(f"[SAVE] ✅ Файл сохранён: {saved_path}")
        return f"✅ Сохранено ({ext.upper()}): {saved_path}"
    
    logging.warning("[SAVE] Пользователь отменил сохранение или произошла ошибка диалога")
    return "⚠️ Отменено."

# 🚀 НОВЫЕ ФУНКЦИИ ДЛЯ РАБОТЫ С СУБТИТРАМИ (SRT) НАПРЯМУЮ
def copy_srt_to_clipboard(file_paths: str) -> str:
    if not file_paths: 
        return "⚠️ Нет SRT файлов (Сначала переведите или транскрибируйте)!"
    paths = [p.strip() for p in file_paths.split('|') if p.strip() and os.path.exists(p)]
    if not paths: 
        return "⚠️ Файлы не найдены на диске!"
    try:
        content = ""
        for p in paths:
            with open(p, 'r', encoding='utf-8') as f:
                content += f.read() + "\n\n"
        
        # Копируем через PowerShell для поддержки огромных текстов и UTF-8
        import tempfile
        temp_path = os.path.join(tempfile.gettempdir(), "clip_srt_temp.txt").replace('\\', '/')
        with open(temp_path, 'w', encoding='utf-8') as f: f.write(content)
        
        CREATE_NO_WINDOW = 0x08000000
        cmd = f'Get-Content -Path "{temp_path}" -Raw -Encoding UTF8 | Set-Clipboard'
        subprocess.run(['powershell', '-command', cmd], creationflags=CREATE_NO_WINDOW)
        
        try: os.remove(temp_path)
        except: pass
        
        return f"📋 Скопирован текст из {len(paths)} файлов (С ТАЙМКОДАМИ)!"
    except Exception as e:
        return f"❌ Ошибка копирования: {e}"

def save_srt_dialog(file_paths: str, actual_out_dir: str) -> str:
    if not file_paths: 
        return "⚠️ Нет SRT файлов для сохранения!"
    paths = [p.strip() for p in file_paths.split('|') if p.strip() and os.path.exists(p)]
    if not paths: 
        return "⚠️ Файлы не найдены на диске!"
    
    # Сохраняем первый файл из списка (обычно он один)
    path = paths[0]
    b_name = os.path.splitext(os.path.basename(path))[0]
    initial_dir = actual_out_dir.replace('\\', '/') if actual_out_dir else os.path.expanduser("~").replace('\\', '/')
    
    code = f'''
import os, shutil
from tkinter import filedialog
res = filedialog.asksaveasfilename(title="Save SRT file as...", initialdir="{initial_dir}", initialfile="{b_name}.srt", defaultextension=".srt", filetypes=[("Subtitles", "*.srt"), ("All files", "*.*")])
if res:
    shutil.copy2(r"{path}", res)
    print(res)
else:
    print("")
'''
    saved_path = _run_tk_dialog(code)
    if saved_path: return f"✅ SRT сохранен: {saved_path}"
    return "⚠️ Сохранение отменено."