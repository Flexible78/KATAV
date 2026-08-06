# KATAV

[![CI](https://github.com/Flexible78/KATAV/actions/workflows/ci.yml/badge.svg)](https://github.com/Flexible78/KATAV/actions/workflows/ci.yml)

**Sound becomes text.**

*Alexander Tsyrkin (Flexible78)*

KATAV is a local-first Windows toolkit for speech recognition. Audio and video transcription runs entirely offline through Faster-Whisper-XXL, with no cloud calls for the core speech-to-text pipeline. An optional AI translation module lets you convert transcripts and subtitles into other languages through pluggable providers, and an experimental vocabulary extractor turns transcripts into structured dictionaries.

![KATAV main interface](screenshots/ui_overview.png)

## Modules

| Module | Function | Status |
| --- | --- | --- |
| Katav | Speech-to-text via Faster-Whisper (local, GPU/CPU) | Stable |
| Safa | Transcript and subtitle translation (RU / EN / HE and more) | Stable |
| Mila | Vocabulary extraction from transcripts | Experimental |

## Features

- **Offline transcription** — speech-to-text runs locally through Faster-Whisper-XXL on GPU or CPU, with no network connection required.
- **Multiple output formats** — export transcripts as TXT, SRT, VTT, or JSON.
- **Optional AI translation** — translate transcripts and subtitles through pluggable providers (Local Proxy, OmniRoute, Freeway, OpenRouter, Google Gemini / Studio, Groq, Mistral).
- **Per-provider model memory** — the last working model for each provider is remembered automatically.
- **Dynamic model lists** — fetch the list of available models directly from each provider with the refresh button.
- **Batch processing** — transcribe multiple files in one run, with an optional cooldown pause between files to manage GPU temperature.
- **Google Drive support** — download private Google Drive files after OAuth sign-in; public shared links work without authentication.
- **Browser UI** — a Gradio-based web interface runs locally on your machine.

## UI options

| Control | What it does |
| --- | --- |
| BY SENTENCES | Split Whisper output by sentences instead of by arbitrary chunk size. |
| PLAIN TEXT | Also write a `*_CLEAN.txt` file with block numbers and timestamps removed. |
| PROGRESS BAR | Show a live progress bar in the log while Whisper runs. |
| VAD | Enable voice-activity detection to skip silent sections. |
| NO BEEPS | Suppress the completion beep after each file. |
| SAVE MP3 | Extract the audio track as an MP3 file alongside the transcript. |
| TRANSLATE ANYWAY | Force translation into every checked target language, ignoring auto-detected source language. |
| + PLAYLIST | Add a YouTube playlist URL and expand it into individual videos. |
| JOIN | Merge all translated text files into one document per language. |
| ZIP | Pack produced files into a downloadable ZIP archive. |
| CLEAR | Clear all source fields (URLs, file paths, and file uploads). |
| EXIT | Stop the app and attempt to close the browser tab. |

## Supported sources

- **Local files**: any common audio/video format (`mp3`, `wav`, `mp4`, `mkv`, etc.).
- **YouTube**: single videos, playlists, and Shorts.
- **Google Drive**: public shared links and private files after OAuth sign-in.
- **Spotify**: **not supported**. Spotify audio is DRM-protected and cannot be downloaded. For podcasts, use the RSS feed or the same episode on YouTube.

## Requirements

- **Windows 10/11 64-bit**
- **Python 3.10+**
- **NVIDIA GPU recommended** (CPU-only mode is supported but slower)
- **[Faster-Whisper-XXL](https://github.com/Purfview/whisper-faster-XXL)** downloaded separately — KATAV shells out to `faster-whisper-xxl.exe`

## Quick start

> **Never used Python or a terminal before?** Do not start with the commands below - follow the step-by-step beginner guide instead: **[English](docs/INSTALL_WINDOWS.md)** · **[Русский](docs/INSTALL_WINDOWS_RU.md)** · **[עברית](docs/INSTALL_WINDOWS_HE.md)**. It covers installing Python, downloading Faster-Whisper-XXL, when Administrator rights are (and are not) needed, and the most common error messages.

```bash
git clone https://github.com/Flexible78/KATAV.git
cd KATAV
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Then open the local URL shown in the terminal. Transcription works fully offline with no API keys. API keys are only required for the translation module.

For full setup instructions including how to point KATAV at `faster-whisper-xxl.exe` and how to configure translation providers, see **[docs/SETUP.md](docs/SETUP.md)**.

For a step-by-step guide on transcribing, translating, and extracting vocabulary, see **[docs/USAGE.md](docs/USAGE.md)**.

## Security

This repository contains **no API keys, no personal paths, no media files, and no transcripts**. All credentials are read from a local, gitignored `whisper_api_keys.json` file that you create on your own machine from the provided `whisper_api_keys.example.json` template. The local Whisper executable path is resolved from an environment variable, a local `whisper_settings.json` file, or autodiscovery — never hardcoded.

## Google Drive OAuth

To transcribe private Google Drive files, sign in through the app:

1. Create a Desktop OAuth client in [Google Cloud Console](https://console.cloud.google.com/), enable the Drive API, and download the JSON secret.
2. Rename the downloaded file to `google_client_secret.json` and place it next to `main.py`.
3. Click **SIGN IN TO GOOGLE** in the app and grant read-only access.

See [docs/SETUP.md](docs/SETUP.md) for the full walkthrough.

## Troubleshooting

### `faster-whisper-xxl.exe` was not found

Transcription needs the Faster-Whisper-XXL executable. Point KATAV at it using **one of three methods** (full details in [docs/SETUP.md](docs/SETUP.md)):

1. Set the `WHISPER_EXE` environment variable to the full path of the executable.
2. Add `"whisper_exe"` to `whisper_settings.json`.
3. Place the extracted `Faster-Whisper-XXL` folder next to the app folder (autodiscovery).

### Port already in use

Launching a second instance can fail with `Cannot find empty port in range: 7861-7861` when the default port is busy. Close the other instance, or pick a different port before launching:

```cmd
set GRADIO_SERVER_PORT=7899
python main.py
```

If no port is specified and the default is busy, KATAV automatically falls back to a free port.

## Tested on

Windows 11, Python 3.14, clean virtual environment, fresh clone.

## Related project

**LECTA** is the companion text-to-speech tool. *KATAV writes, LECTA reads.*

## License

All rights reserved. See [LICENSE](LICENSE).

## What is new (2026-08-06)

### Output handling
- `AUTO-OPEN WHEN DONE` checkbox (on by default) next to `OPEN OUTPUT FOLDER`: the results folder opens in Explorer as soon as transcription, translation or a full cycle finishes.
- `RETRY FAILED` requeues every item with the `failed` status; `RELOAD` restarts the whole app process and reloads the browser tab.

### Power actions after a batch
- `POWER ACTION AFTER BATCH` replaces the old shutdown checkbox and now has a `SHUT DOWN / SLEEP` selector plus `CANCEL`.
- `SHUT DOWN` runs `shutdown /s /t 60` (cancellable with `shutdown /a`).
- `SLEEP` waits 60 cancellable seconds and then calls `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`. For real S3 sleep instead of hibernation run `powercfg /h off` once.

### Custom AI providers
- `TRANSLATION -> CUSTOM AI PROVIDER (OpenAI-compatible)` registers any OpenAI-compatible endpoint: LM Studio, Ollama OpenAI shim, vLLM, LiteLLM, corporate gateways.
- Fields: `NAME`, `BASE URL` (for example `http://127.0.0.1:1234/v1`), optional `API KEY`.
- `ADD / UPDATE PROVIDER` saves it to `custom_providers.json`, adds it to the `PROVIDER` radio immediately and tries to pull the model list.
- `DELETE PROVIDER` removes it. Custom providers work with `CHECK API`, model refresh, `SAVE KEY` and translation exactly like the built-in ones.

### UI
- Pastel production palette: one steel-blue accent plus muted sand, brick, teal and rose, no neon.
- `CLEAR` buttons are intentionally highlighted (rose border and ring) because the action is destructive.
- Checkboxes and the power selector are real 48 px controls aligned with the buttons, with modern thin scrollbars.

### Stability
- `main.py` port guard: only LISTEN sockets are probed, stale PIDs are ignored, only KATAV python processes are terminated, foreign owners are reported instead of crashing the launch.
- `main.py` registers its real PIDs in `.katav_pids`; `utils.kill_program()` validates each PID before killing, so `EXIT` no longer kills unrelated apps or leaves port 7861 busy.
