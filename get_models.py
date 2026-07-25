import os
import json
import google.generativeai as genai

# Read the API key from the local, gitignored config file (never hardcode secrets).
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whisper_api_keys.json")
_api_key = ""
if os.path.exists(_cfg_path):
    try:
        with open(_cfg_path, "r", encoding="utf-8") as _f:
            _cfg = json.load(_f)
        _api_key = _cfg.get("google_studio", "") or _cfg.get("google", "")
    except Exception:
        pass

if not _api_key:
    raise SystemExit("No Google API key found in whisper_api_keys.json (keys: 'google_studio' or 'google').")

# Configure with the key from the local config
genai.configure(api_key=_api_key)

# List all available models and their supported methods
for m in genai.list_models():
    print(f"Model Name: {m.name}")
    print(f"Supported Methods: {m.supported_generation_methods}\n")