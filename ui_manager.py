import os
import json
from typing import Dict, Any

# Импортируем SETTINGS_FILE из config.py
from config import SETTINGS_FILE

# ==============================================================================
# 5. МЕНЕДЖЕР СОСТОЯНИЙ ИНТЕРФЕЙСА (АВТОСОХРАНЕНИЕ)
# ==============================================================================
class UIStateManager:
    def __init__(self, filepath: str = SETTINGS_FILE):
        self.filepath = filepath
        self.settings = self.load_settings()

    def load_settings(self) -> Dict[str, Any]:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f: return json.load(f)
            except Exception: return {}
        return {}

    def save_settings(self, new_settings: Dict[str, Any]) -> None:
        self.settings.update(new_settings)
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f: json.dump(self.settings, f, indent=4, ensure_ascii=False)
        except Exception: pass

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key, default)

ui_state = UIStateManager()
