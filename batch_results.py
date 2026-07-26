"""
batch_results.py — Batch post-processing helpers for KATAV.
Implements "JOIN into one file" and "ZIP results" after a batch completes.
"""

import logging
import os
import re
import zipfile
from datetime import datetime
from typing import List, Dict, Any, Tuple

from config import DEFAULT_OUTPUT_DIR
from queue_manager import batch_queue
from utils import clean_srt_text, _url_cache_dir


def _language_suffix(path: str) -> str:
    """Infer a language suffix from a filename, e.g. _EN, _HE, _RU, or UNKNOWN."""
    base = os.path.splitext(os.path.basename(path))[0]
    # Match language markers at end of base name or before _TRANSLATED_
    m = re.search(r'_([A-Z]{2,3})(?:_\d+)?$', base)
    if m:
        return m.group(1)
    m = re.search(r'_TRANSLATED_([A-Z]{2,3})', base)
    if m:
        return m.group(1)
    return "UNKNOWN"


def _pick_text_file(paths: List[str], plain_text: bool) -> Tuple[str, bool]:
    """Choose the best representative text file from a list for JOIN/ZIP.

    Returns (path, needs_cleaning). SRT/VTT are never returned as-is; if no
    plain text exists, an SRT will be cleaned on read.
    """
    if not paths:
        return "", False
    if plain_text:
        clean = [p for p in paths if p.endswith("_CLEAN.txt")]
        if clean:
            return clean[0], False
    txts = [p for p in paths if p.endswith(".txt") and not p.endswith("_CLEAN.txt")]
    if txts:
        return txts[0], False
    srts = [p for p in paths if p.lower().endswith(".srt") or p.lower().endswith(".vtt")]
    if srts:
        # SRT/VTT must be cleaned before joining
        return srts[0], True
    return paths[0], False


def join_batch_results(output_dir: str, plain_text: bool = False) -> List[str]:
    """
    Join the current batch's text results into one document per language.

    Returns a list of generated file paths.
    """
    if not output_dir:
        output_dir = DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    results = batch_queue.get_batch_results()
    # Sort by playlist_index, then by original queue idx
    results.sort(key=lambda r: (r.get("playlist_index") or r["idx"], r["idx"]))

    # Group files by inferred language, picking the best file per item per language
    lang_files: Dict[str, List[Tuple[int, str, str, bool]]] = {}
    for item in results:
        idx = item["idx"]
        name = item.get("name", "")
        produced = [p for p in item.get("produced_files", []) if os.path.isfile(p)]
        # Group text/subtitle files by inferred language first
        by_lang: Dict[str, List[str]] = {}
        for path in produced:
            if os.path.splitext(path)[1].lower() not in (".txt", ".srt", ".vtt"):
                continue
            lang = _language_suffix(path)
            by_lang.setdefault(lang, []).append(path)
        for lang, text_paths in by_lang.items():
            path, needs_clean = _pick_text_file(text_paths, plain_text)
            if path:
                lang_files.setdefault(lang, []).append((idx, name, path, needs_clean))

    written: List[str] = []
    for lang, entries in lang_files.items():
        if lang == "UNKNOWN":
            # Warn but still produce a file so the user can inspect the contents
            # if any files failed language inference.
            logging.getLogger("batch_results").warning("JOIN: could not infer language for some produced files; grouping under UNKNOWN.")
        # Deduplicate by path while preserving order
        seen: set = set()
        unique_entries: List[Tuple[int, str, str, bool]] = []
        for idx, name, path, needs_clean in entries:
            if path not in seen:
                seen.add(path)
                unique_entries.append((idx, name, path, needs_clean))

        out_path = os.path.join(output_dir, f"batch_JOINED_{lang}.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            for order, (idx, name, path, needs_clean) in enumerate(unique_entries, start=1):
                try:
                    with open(path, "r", encoding="utf-8") as src:
                        content = src.read()
                except Exception:
                    continue
                if needs_clean or (plain_text and (path.lower().endswith(".srt") or path.lower().endswith(".vtt"))):
                    content = clean_srt_text(content)
                header = f"## {order:03d} — {name}\n\n"
                f.write(header)
                f.write(content.strip())
                f.write("\n\n")
        written.append(out_path)

    return written


def zip_batch_results(output_dir: str, include_audio: bool = False) -> str:
    """
    Zip the current batch's results into a single archive.

    Returns the path to the created zip file.
    """
    if not output_dir:
        output_dir = DEFAULT_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    results = batch_queue.get_batch_results()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    zip_path = os.path.join(output_dir, f"batch_{timestamp}.zip")

    written_any = False
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        seen: set = set()
        for item in results:
            for path in item.get("produced_files", []):
                if not os.path.isfile(path):
                    continue
                if path in seen:
                    continue
                seen.add(path)
                arcname = os.path.basename(path)
                ext = os.path.splitext(path)[1].lower()
                if ext == ".mp3" and not include_audio:
                    continue
                if path.startswith(_url_cache_dir()):
                    continue
                zf.write(path, arcname=arcname)
                written_any = True

    if not written_any:
        try:
            os.remove(zip_path)
        except Exception:
            pass
        return ""
    return zip_path
