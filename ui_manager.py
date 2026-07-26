import os
import json
import logging
from typing import Dict, Any

# Импортируем SETTINGS_FILE из config.py
from config import SETTINGS_FILE, TARGET_LANGUAGE_CODE_MAP, TARGET_LANGUAGES

# ==============================================================================
# 5. МЕНЕДЖЕР СОСТОЯНИЙ ИНТЕРФЕЙСА (АВТОСОХРАНЕНИЕ)
# ==============================================================================


def _migrate_lang_list(values: list) -> list:
    """Walk a list of language values, convert old display labels to codes,
    drop anything unrecognised (with a log warning), and deduplicate.
    Returns a clean code list."""
    seen = set()
    clean = []
    valid_codes = {pair[1] for pair in TARGET_LANGUAGES}
    for v in values:
        if not v:
            continue
        raw = str(v)
        # Try the global migration table (handles old labels + codes).
        migrated = TARGET_LANGUAGE_CODE_MAP.get(raw, "")
        if migrated and migrated in valid_codes:
            if migrated not in seen:
                seen.add(migrated)
                clean.append(migrated)
        elif raw in valid_codes:
            # Raw value is already a valid code.
            if raw not in seen:
                seen.add(raw)
                clean.append(raw)
        else:
            logging.warning("[MIGRATE] Discarded unrecognised language value: %r", raw)
    return clean


class UIStateManager:
    def __init__(self, filepath: str = SETTINGS_FILE):
        self.filepath = filepath
        self.settings = self.load_settings()

    def load_settings(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            except Exception:
                settings = {}
        else:
            settings = {}

        # ── Migrate legacy language display labels to stable codes ──
        raw_langs = settings.get("trans_langs")
        if isinstance(raw_langs, list):
            clean = _migrate_lang_list(raw_langs)
            if clean != raw_langs:
                settings["trans_langs"] = clean
                # Persist the migrated list back to disk immediately.
                try:
                    with open(self.filepath, 'w', encoding='utf-8') as f:
                        json.dump(settings, f, indent=4, ensure_ascii=False)
                except Exception:
                    pass

        return settings

    def save_settings(self, new_settings: Dict[str, Any]) -> None:
        self.settings.update(new_settings)
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)


ui_state = UIStateManager()
