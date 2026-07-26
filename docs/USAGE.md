# KATAV — Usage Guide

A step-by-step guide to transcribing, translating, and extracting vocabulary with KATAV.

---

## 1. Starting the app

Open a terminal in the KATAV folder and run:

```
python main.py
```

The app starts a local web server and opens your browser automatically. If it does not, copy the local URL shown in the terminal (for example `http://127.0.0.1:7861`) into your browser.

The interface has two columns:
- **Left column** — media files and Whisper transcription settings.
- **Right column** — live log, progress metrics, the AI translator, and a text editor.

---

## 2. Transcribing media

1. **Add files.** Do one or more of the following:
   - Type or paste a file or folder path into the **FILE / FOLDER PATH** field.
   - Click **FILE** to pick files, or **DIR** to pick a folder for batch processing.
   - Drag and drop audio or video files onto the drop zone.
   - Paste media URLs (YouTube, VK, TikTok) into the **URLS** field. Audio is downloaded with yt-dlp before transcription.
2. **Choose language.** Set **LANGUAGE** to the spoken language (`ru`, `en`, `he`) or leave it on `auto` for automatic detection. Specifying the language reduces recognition errors.
3. **Pick a model.** Choose a **MODEL** size (see [section 3](#3-choosing-a-whisper-model)).
4. **Pick compute type.** Set **COMPUTE** to `float16` for NVIDIA GPUs, `int8` for low VRAM or CPU, or `float32` for full precision.
5. **Choose output formats.** Tick the formats you want in the **FORMATS** row: `srt`, `vtt`, `txt`, `json`.
6. **Start.** Click **START (SUBS ONLY)** to transcribe. Use **FULL CYCLE (SUBS+TRANS)** if you also want to translate immediately afterward.
7. **Find results.** Output files are saved next to the source file, or in the output directory you configured. See [section 7](#7-where-files-are-saved).

Watch the **LIVE LOG** and the progress bar for real-time status. Use **STOP** to cancel, or **PAUSE** to suspend between chunks.

---

## 3. Choosing a Whisper model

The **MODEL** dropdown controls the neural network size. Larger models are more accurate but need more VRAM and are slower.

| Model | VRAM (min) | Accuracy | Speed | Best for |
| --- | --- | --- | --- | --- |
| `tiny` | ~1 GB | Low | Very fast | Quick drafts |
| `base` | ~1.5 GB | Low | Fast | Short recordings |
| `small` | ~2.5 GB | Medium | Fast | Interviews, podcasts |
| `medium` | ~5 GB | Good | Medium | Good balance |
| `large-v2` | ~10 GB | Best | Slow | Films, lectures — recommended default |
| `large-v3` | ~10 GB | Best | Slow | Try only if v2 struggles with an accent |
| `large-v3-turbo` | ~6 GB | Good | Fast | Faster than large-v2, lower VRAM |

**Tips:**
- On CPU-only or low-VRAM machines, use `int8` compute with `medium` or `large-v3-turbo`.
- Click **ECO** for a preset that uses `large-v3-turbo`, `int8`, and a small beam size. This reduces heat and GPU load at a small cost to accuracy.
- `large-v2` is the golden standard for films, series, and lectures.

---

## 4. Translating a transcript

1. **Select a provider.** In the **PROVIDER** row, pick one of: Local Proxy, OmniRoute, Freeway, Mistral, Google Studio (Gemma 4), Groq (OSS 120b), OpenRouter.
2. **Enter your API key.** Type it into the **API Key** field and click **SAVE KEY**. The key is stored in your local `whisper_api_keys.json` and remembered the next time you start the app. See [docs/SETUP.md](SETUP.md) for how to get a key.
3. **Pick a model.** Choose a model from the dropdown, or click **🔄** to fetch the live list of available models from the provider. You can also type a model name manually.
4. **Choose target languages.** Tick the languages you want in **TARGET LANGUAGES** (Russian, English, Hebrew).
5. **Choose a mode.** Set **MODE** to **Files** to translate subtitle files, or **Text (from Editor)** to translate the text in the editor panel.
6. **Start.** Click **TRANSLATE**.

The last working model for each provider is remembered automatically. The next time you select that provider, your previous model is pre-selected.

Use **CHECK API** before translating to verify that your key and model work with the selected provider.

---

## 5. Refreshing the model list

The **🔄** button next to the model dropdown fetches the current list of available models directly from the selected provider's API.

Use it when:
- The dropdown is empty or shows only default models.
- You created a new key and want to see which models it can access.
- The provider added new models since your last refresh.

Fetched model lists are cached in `whisper_api_keys.json` so they persist between sessions. If a refresh fails, check your API key and network connection. You can always type a model name manually into the dropdown as a fallback.

---

## 6. Vocabulary extraction (experimental)

The **EXTRACT VOCAB** button reads a transcript and produces a structured vocabulary dictionary in JSON and CSV format.

To use it:
1. Provide a transcript (an SRT file or text in the editor).
2. Click **EXTRACT VOCAB**.
3. The output appears in the **VOCAB STATUS** field and the extracted files are listed in the download area.

> **Quality note:** This feature is **experimental**. The extracted vocabulary is not production-ready. Expect incomplete entries, duplicate terms, and occasional errors. It is a starting point for building a glossary, not a finished dictionary.

---

## 7. Where files are saved

By default, output files are saved **next to the source media file**. For files downloaded from URLs or copied to a temp folder, outputs go to the `Outputs/` folder inside the KATAV directory.

To use a custom output location:
1. Open the **OUTPUT DIRECTORY** accordion.
2. Tick **USE CUSTOM OUTPUT DIR**.
3. Type a path or click **BROWSE** to pick a folder.

Translated files are named with a language suffix, for example `lecture_TRANSLATED_EN.srt`. Partial results from a cancelled run are saved with a `_PARTIAL` suffix.

---

## 8. Performance tips

- **Batch processing.** Put multiple files in one folder and point the **FILE / FOLDER PATH** field at it. KATAV processes them one by one.
- **Cooldown between files.** A pause between batch files lets the GPU cool down. This is controlled by the `WHISPER_COOLDOWN_SEC` setting in `config.py` (0 disables it).
- **Smaller models for long files.** A 2-hour film on `large-v2` with `float16` can take a long time and a lot of VRAM. Switch to `large-v3-turbo` or `medium` with `int8` to go faster and use less memory.
- **GPU temperature.** If your GPU runs hot, use the **ECO** preset, lower the compute type to `int8`, or reduce the beam size. You can also cap the GPU power limit via the `WHISPER_GPU_POWER_LIMIT_W` setting in `config.py`.
- **CPU-only machines.** Use `int8` compute with `medium` or `large-v3-turbo`. The app automatically limits CPU threads to avoid overloading your machine.

---

## 9. EXIT and browser tab

Clicking **EXIT (app + consoles)** stops both console windows and tries to close the browser tab. Because the tab was opened by the operating system, not by JavaScript, most browsers block `window.close()` for security reasons. If the tab stays open, it shows a "KATAV stopped" page so you know it is safe to close it manually.

---

## 10. Plain text output and forced translation

- Tick **PLAIN TEXT (no numbers, no timestamps)** before starting transcription or translation to also write a `*_CLEAN.txt` file next to every SRT or VTT output. The clean file contains the same text with block numbers, timecodes, and HTML/VTT tags removed.
- Tick **TRANSLATE ANYWAY (ignore language auto-detection)** to force translation into every checked target language, even when the filename or the detected source language suggests the file is already in that language.
