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
- **Browser UI** — a Gradio-based web interface runs locally on your machine.

## Requirements

- **Windows 10/11 64-bit**
- **Python 3.10+**
- **NVIDIA GPU recommended** (CPU-only mode is supported but slower)
- **[Faster-Whisper-XXL](https://github.com/Purfview/whisper-faster-XXL)** downloaded separately — KATAV shells out to `faster-whisper-xxl.exe`

## Quick start

> **Never used Python or a terminal before?** Do not start with the commands below - follow the step-by-step beginner guide instead: **[docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md)** (Russian: **[docs/INSTALL_WINDOWS_RU.md](docs/INSTALL_WINDOWS_RU.md)**). It covers installing Python, downloading Faster-Whisper-XXL, and the most common error messages.

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
