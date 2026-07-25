# KATAV — Setup Guide

This guide covers everything you need to configure KATAV on your machine. A stranger can follow it from a fresh clone to a working app without ever needing the author's keys.

> **Key fact:** Transcription (speech-to-text) works with **no API keys at all**. Keys are only needed for the optional AI translation module.

---

## Section 1 — Installing Faster-Whisper-XXL

KATAV shells out to `faster-whisper-xxl.exe` from the [Faster-Whisper-XXL](https://github.com/Purfview/whisper-faster-XXL) project. Download the Windows release and extract it somewhere on your machine. Then point KATAV at it using **one of three methods**, in priority order:

### Method 1 — Autodiscovery (easiest)

Place the extracted `Faster-Whisper-XXL` folder (the one containing `faster-whisper-xxl.exe`) **next to the KATAV app folder**, or inside it:

```
C:\projects\
├── KATAV\                      <- the app
│   ├── main.py
│   └── ...
└── Faster-Whisper-XXL\         <- place it here
    └── faster-whisper-xxl.exe
```

On startup KATAV searches the app directory and its parent folder for `faster-whisper-xxl.exe` and uses it automatically. No configuration needed.

### Method 2 — Environment variable

Set the `WHISPER_EXE` environment variable to the full path of the executable:

**Command Prompt:**
```cmd
set WHISPER_EXE=C:\Tools\Faster-Whisper-XXL\faster-whisper-xxl.exe
python main.py
```

**PowerShell:**
```powershell
$env:WHISPER_EXE = "C:\Tools\Faster-Whisper-XXL\faster-whisper-xxl.exe"
python main.py
```

To make it permanent, add it via **System Properties → Environment Variables → User variables**.

### Method 3 — Settings file

Create a `whisper_settings.json` file in the KATAV root directory (copy from `whisper_settings.example.json`) and set the `whisper_exe` key:

```json
{
    "whisper_exe": "C:\\Tools\\Faster-Whisper-XXL\\faster-whisper-xxl.exe"
}
```

Use double backslashes (`\\`) in JSON string values.

### Resolution order

KATAV resolves the executable in this order, using the first non-empty result:

1. `WHISPER_EXE` environment variable
2. `whisper_exe` key in `whisper_settings.json`
3. Autodiscovery (recursive search in the app folder and its parent)

If none of the three succeed, the app starts normally but transcription shows a clear error message with setup instructions instead of crashing.

---

## Section 2 — API keys file

Translation providers need API keys. Keys are stored in a local `whisper_api_keys.json` file that is **gitignored** — it never enters the repository.

1. Copy the template:
   ```cmd
   copy whisper_api_keys.example.json whisper_api_keys.json
   ```
2. Open `whisper_api_keys.json` in a text editor and fill in the keys for the providers you want to use:

```json
{
    "google": "",
    "google_studio": "",
    "groq": "",
    "openrouter": "",
    "omniroute": "",
    "freeway": "",
    "mistral": "",
    "last_models": {},
    "cached_models": {}
}
```

3. Leave keys empty for providers you do not use. A missing or empty key never crashes the app — the translation module simply shows a warning when you try to translate.

> **Transcription works with no API keys at all.** Keys are only needed for the translation module.

You can also enter and save keys directly in the app UI using the **SAVE KEY** button — they are written to the same `whisper_api_keys.json` file.

> The `last_models` and `cached_models` keys are managed automatically by the app (it remembers your last working model and caches fetched model lists). Leave them as empty `{}` when creating the file.

---

## Section 3 — Provider reference

KATAV supports the following translation providers. **All providers remain available in the UI regardless of whether you have a key for them.**

| Provider | Endpoint | Key needed | Notes |
| --- | --- | --- | --- |
| Local Proxy | `http://127.0.0.1:8080/v1` | no (use `dummy`) | Any local OpenAI-compatible server. Commonly a Gemini OAuth proxy. |
| OmniRoute | `http://127.0.0.1:20128/v1` | depends on setup | Local model router/aggregator. Key requirement depends on your OmniRoute configuration. |
| Freeway | `http://127.0.0.1:8787/v1` | placeholder `123` | Local model router/aggregator. The default key `123` is a built-in placeholder, not a secret — it is sent only to your own local server. |
| OpenRouter | `https://openrouter.ai/api/v1` | yes, free tier available | Many models with a `:free` suffix require no payment. |
| Google Studio (Gemma 4) | Google Generative Language API | yes, free tier available | Very large context window. Best for long transcripts. |
| Groq | `https://api.groq.com/openai/v1` | yes, free tier available | Extremely fast inference, but a small context window. |
| Mistral | `https://api.mistral.ai/v1` | yes, free tier available | Large context window. |

> **Note on `FREEWAY_DEFAULT_KEY`:** The value `123` in `config.py` is a placeholder for a local router, not a secret. It is only ever sent to `127.0.0.1:8787` (your own machine). You can override it by entering a different key in the UI.

---

## Section 4 — Free models worth trying

If you have no budget, these options give you working translation without payment. This is guidance, not a guarantee — free tiers change over time.

- **Google Gemini Flash** — very large context window and a generous free quota. The best choice for long transcripts. Get a key from [Google AI Studio](https://aistudio.google.com/).
- **OpenRouter free models** — models with a `:free` suffix (for example `minimax/minimax-m2.5:free`, `google/gemma-4-31b-it:free`) require no credit card. Create an account at [openrouter.ai](https://openrouter.ai/).
- **Mistral free tier** — large context window but a low request rate. Get a key at [console.mistral.ai](https://console.mistral.ai/).
- **Groq** — extremely fast, but the small context window makes it better suited to short files. Get a key at [console.groq.com](https://console.groq.com/).
- **OmniRoute / Freeway** — these are routers, not models. Output quality depends on whichever backend model they route your request to.

> Free-tier rate limits and quotas change over time. Always check the provider's own pricing page for current limits.

---

## Section 5 — Troubleshooting

### `faster-whisper-xxl.exe was not found`

The app could not locate the Whisper executable. Use one of the three methods in [Section 1](#section-1--installing-faster-whisper-xxl) to point KATAV at it:
1. Set the `WHISPER_EXE` environment variable.
2. Add `"whisper_exe"` to `whisper_settings.json`.
3. Place the `Faster-Whisper-XXL` folder next to the app.

### Missing API key

The translation module shows a warning when you try to translate without a key. Add your key to `whisper_api_keys.json` or enter it in the UI and click **SAVE KEY**. Transcription does not need a key and continues to work.

### Provider unreachable

If you see a connection error:
- For **Local Proxy / OmniRoute / Freeway**: make sure the local server is running on the correct port (8080 / 20128 / 8787 respectively).
- For cloud providers: check your internet connection and verify the key is valid.

### Model list is empty

Click the **🔄** (refresh) button next to the model dropdown to fetch the list of available models from the provider. If it stays empty, check your API key and network connection. You can also type a model name manually into the dropdown.

### GPU out of memory

If transcription fails with a CUDA out-of-memory error:
- Switch the **COMPUTE** setting to `int8` (roughly halves VRAM usage with a small quality loss).
- Use a smaller model (`medium` instead of `large-v2`).
- Use `large-v3-turbo` for a balance of speed and quality with lower VRAM.
- On CPU-only machines, use `int8` compute — it is the fastest option without a GPU.
