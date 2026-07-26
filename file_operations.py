import os
import gradio as gr
from utils import get_actual_output_dir

def list_files(manual_path: str, use_custom: bool, custom_dir: str):
    out_dir = get_actual_output_dir(manual_path, use_custom, custom_dir)
    if not os.path.exists(out_dir): 
        # Reset value=[] to clear any stuck checkboxes
        return gr.update(choices=[], value=[]), f"️ Folder not found: {out_dir}"
    try:
        files = [f for f in os.listdir(out_dir) if os.path.isfile(os.path.join(out_dir, f))]
        files.sort()
        # Refresh file list and force-clear all checkboxes (value=[])
        return gr.update(choices=files, value=[]), f"📁 Scanning: {out_dir}"
    except Exception as e: 
        return gr.update(choices=[], value=[]), f"❌ Error: {e}"

def delete_selected(selected: list, manual_path: str, use_custom: bool, custom_dir: str):
    if not selected:
        files_update, _ = list_files(manual_path, use_custom, custom_dir)
        return files_update, "⚠️ Nothing selected!"
        
    out_dir = get_actual_output_dir(manual_path, use_custom, custom_dir)
    deleted_count = 0
    
    for filename in selected:
        try:
            target_path = os.path.join(out_dir, filename)
            if os.path.exists(target_path): 
                os.remove(target_path)
                deleted_count += 1
        except Exception: 
            pass
            
    # Rescan the folder. list_files will update the list and reset checkboxes
    updated_files, _ = list_files(manual_path, use_custom, custom_dir)
    return updated_files, f"✅ Deleted files: {deleted_count}"

def delete_all(manual_path: str, use_custom: bool, custom_dir: str):
    out_dir = get_actual_output_dir(manual_path, use_custom, custom_dir)
    deleted_count = 0
    if os.path.exists(out_dir):
        try:
            for filename in os.listdir(out_dir):
                target_path = os.path.join(out_dir, filename)
                if os.path.isfile(target_path): 
                    os.remove(target_path)
                    deleted_count += 1
        except Exception: 
            pass
            
    # После полного удаления отдаем пустой список и сбрасываем галочки
    return gr.update(choices=[], value=[]), f"💣 Cleared files: {deleted_count}"