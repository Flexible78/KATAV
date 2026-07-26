

> **Purpose**
>
> This document is intended for AI coding agents working on this repository.
>
> Read this file before making any modifications.
>
> The goal is to preserve architecture consistency, avoid duplicated logic, and keep the application maintainable.

***

# Project Overview

This project is a desktop application for:

* audio/video transcription

* subtitle (SRT) processing

* AI-powered translation

* multilingual subtitle generation

* Gradio-based graphical interface

* Whisper/OpenAI/Gemini integration

The application is organized into small modules with clear responsibilities instead of placing everything inside `main.py`.

***

# High Level Architecture

```
                main.py
                   │
        ┌──────────┴──────────┐
        │                     │
    gradio_app.py        ui_manager.py
        │                     │
        └──────────┬──────────┘
                   │
             whisper_core.py
                   │
     ┌─────────────┼──────────────┐
     │             │              │
srt_processor.py ai_translator.py file_operations.py
     │             │              │
     └─────────────┼──────────────┘
                   │
              utils.py
                   │
              config.py
```

***

# Module Responsibilities

## main.py

Application entry point.

Responsibilities:

* initialize application

* start UI

* load configuration

Do NOT implement business logic here.

***

## gradio\_app.py

Responsible only for Gradio interface.

Contains:

* widgets

* layouts

* callbacks

* event wiring

Avoid putting processing logic inside callbacks.

Callbacks should delegate work to dedicated modules.

***

## ui\_manager.py

Coordinates interaction between UI and backend.

Responsible for:

* UI state

* progress updates

* status messages

* communication between Gradio and processing modules

Should not contain Whisper or translation logic.

***

## whisper\_core.py

Core transcription engine.

Responsibilities:

* loading Whisper model

* running transcription

* timestamp generation

* segment creation

Any transcription improvements belong here.

***

## ai\_translator.py

Handles all AI translation.

Responsibilities:

* prompt generation

* API communication

* translation retries

* batching

* model selection

Never duplicate translation logic elsewhere.

***

## srt\_processor.py

Works exclusively with subtitles.

Responsibilities:

* parsing SRT

* merging

* splitting

* cleaning

* formatting

* validation

No API calls should exist here.

***

## file\_operations.py

Handles filesystem operations.

Responsibilities:

* reading files

* writing files

* exporting

* creating output folders

Avoid direct file access elsewhere.

***

## config.py

Single source of configuration.

Contains:

* constants

* paths

* default values

* application settings

Avoid hardcoded values.

***

## utils.py

Shared helper functions only.

Allowed:

* formatting

* validation

* helper utilities

Not allowed:

* business logic

* UI logic

* Whisper logic

***

# Data Flow

```
User

↓

Gradio UI

↓

UI Manager

↓

Whisper

↓

SRT Processor

↓

AI Translator

↓

File Operations

↓

Output Files
```

Always preserve this direction.

Avoid circular dependencies.

***

# Directory Roles

```
Outputs/
    Generated files only

libs/
    Experimental or helper scripts

bkp/
    Historical backups

.vscode/
    IDE settings

.venv/
    Python environment

__pycache__/
    Ignore
```

AI agents should never modify:

* Outputs/

* bkp/

* .venv/

* **pycache**/

unless explicitly requested.

***

# Design Principles

## Single Responsibility

Each module owns one domain.

Do not mix:

* UI

* Translation

* Whisper

* File IO

* Subtitle processing

inside one file.

***

## Reuse Existing Code

Before adding new functions:

1. Search existing modules.

2. Extend existing implementation.

3. Avoid duplicate utilities.

***

## Import Direction

Preferred dependency graph:

```
config

↓

utils

↓

processing modules

↓

UI manager

↓

Gradio

↓

main
```

Never create circular imports.

***

# When Adding New Features

Ask:

Which module owns this responsibility?

Examples:

New translation provider

→ ai\_translator.py

New subtitle cleanup

→ srt\_processor.py

New export format

→ file\_operations.py

New Whisper option

→ whisper\_core.py

New UI control

→ gradio\_app.py

***

# Coding Rules

Prefer:

* small functions

* descriptive names

* type hints

* docstrings

* minimal side effects

Avoid:

* global mutable state

* duplicated constants

* duplicated prompts

* duplicated file logic

***

# Error Handling

Catch exceptions close to the source.

Examples:

Filesystem errors

→ file\_operations.py

API failures

→ ai\_translator.py

Whisper failures

→ whisper\_core.py

UI should only display user-friendly errors.

***

# Performance Guidelines

Large files should be processed incrementally.

Avoid:

* loading huge files repeatedly

* repeated API requests

* unnecessary disk writes

Reuse cached objects when possible.

***

# AI Modification Rules

Before editing:

1. Understand module ownership.

2. Search for existing implementation.

3. Preserve architecture.

4. Keep changes localized.

5. Do not rewrite unrelated code.

If a feature requires changes across multiple modules:

* explain why

* keep interfaces stable

* minimize breaking changes

***

# Testing Checklist

After modifications verify:

* transcription still works

* translation still works

* SRT export is valid

* UI launches

* existing outputs remain compatible

***

# Future Extension Points

Recommended locations for new features:

```
translation providers
    ai_translator.py

subtitle filters
    srt_processor.py

additional exporters
    file_operations.py

new AI prompts
    ai_translator.py

new Whisper engines
    whisper_core.py

UI pages
    gradio_app.py
```

***

# What AI Agents Should Never Do

❌ Move business logic into UI callbacks

❌ Duplicate helper functions

❌ Hardcode API keys

❌ Create circular imports

❌ Modify generated output files

❌ Mix filesystem operations with AI logic

❌ Add unrelated dependencies without justification

***

# Goal

Keep the architecture modular, predictable, and easy for both humans and AI agents to navigate.

When in doubt:

* extend existing modules

* preserve separation of concerns

* keep responsibilities explicit

* favor maintainability over cleverness

---

## Snapshot 2026-07-26 — E1-E6 Batch Enhancement

### Implemented features:
- **E1 (Durations & ETA):** Added batch duration, current file duration, elapsed, and dynamic ETA to progress panel. Uses ffprobe for file durations and yt-dlp for URL metadata. 4-cell metric grid with HH:MM:SS/MM:SS formatting. ETA computes from measured processing speed.
- **E2 (Safe Shutdown):** Checkbox "Shut down Windows after batch completes" with 60-second cancellable countdown via `shutdown /s /t 60` and `shutdown /a`. No /f flag. Only triggers on completed batch with at least one success.
- **E3 (Appendable URL Queue):** Multi-line URL input. ADD URL button normalizes, validates, and deduplicates. File/URL badges in queue panel (blue/purple). URLs and files interleave in insertion order.
- **E4 (Selective Removal):** Per-item status display (Queued/Running/Done/Failed). Running items cannot be removed. Completed/failed items remain in history without deleting output files.
- **E5 (Settings Snapshot):** prepare_start snapshots all Whisper settings at batch start. Each queued item stores its own snapshot for future per-item application.
- **E6 (UI Design):** Refined dark-themed progress panel: overall percentage + bar + completed/total, 4-cell metric row (Elapsed/ETA/Speed/Batch Dur), current-file section with name+duration+bar, queue section with File/URL badges, status colors, truncated names with tooltips.

### New files:
- **queue_manager.py** — QueueManager singleton with QueueItem dataclass, duration extraction (ffprobe/yt-dlp), thread-safe ETA calculation, settings snapshots, shutdown scheduling.
- **test_queue.py** — 25 non-GUI tests verifying: queue append order, duplicate rejection, selective removal with duration recalculation, ETA calculation with zero-duration guard, snapshot semantics isolation, shutdown eligibility.

### Modified files:
- **gradio_app.py** — prepare_start now builds queue in batch_queue with settings snapshots; process_logs parses [BATCH_STATUS] lines and renders enhanced metrics panel; added shutdown checkbox, cancel button, multi-line URL input, ADD URL button.
- **whisper_core.py** — Unchanged (queue integration via process_logs synchronizing [PROGRESS_FILE] lines with batch_queue).

### Important semantics:
- Settings apply to next queued item, not the item already running (snapshotted at prepare_start).
- Shutdown: 60-second cancellable countdown, no /f, requires >=1 success, skips on cancel.
- ETA: excludes items with unknown duration (URLs before metadata). Tooltip explains this.
- batch_queue bridges UI (gradio_app) and processing (whisper_core) via shared global singleton.

### Tests:
- 25/25 non-GUI tests passed (test_queue.py).
- AST check: all .py files parse without syntax errors.
- git diff --check: clean (no whitespace errors).

### Git log:
- Branch: release-clean
- Previous commits: c79c8d2, 3851684, be7cd01, 2600d2b
- New (unstaged): gradio_app.py (+300/-60), queue_manager.py (new), test_queue.py (new)

### ⚠️ Nothing was pushed. Owner GUI verification required for:
- Duration display accuracy with real media files
- ETA convergence during actual batch processing
- Shutdown trigger/cancel behavior on real Windows
- URL add-to-queue during running batch

---

## 2026-07-26 - KATAV follow-up: typing import fix + dead-code cleanup + URL pipeline tests (model: Kimi K2.7)
- Fixed `NameError` in `whisper_core.py`: `Dict` was used in the type hint of
  `_get_playlist_entries` but not imported from `typing`.
- Removed dead `downloaded_audio_files` parameter/list/cleanup loop in
  `_download_url_to_queue` and `run_transcription`; the URL cache in
  `Outputs/_url_cache` is intentionally retained for reuse.
- Updated the docstring of `_download_url_to_queue` to document the cache reuse
  policy.
- Added `test_url_pipeline.py` with 14 non-GUI unit tests for the YouTube/URL
  pipeline: `utils.canonical_media_url`, `whisper_core._get_playlist_entries`,
  and `whisper_core._download_url_to_queue`. Tests use `unittest.mock` for
  `yt-dlp`, `subprocess.Popen`, and filesystem helpers; no real network calls.
- All 25 `test_queue.py` tests + 14 `test_url_pipeline.py` tests pass; all
  `.py` files compile.

## 2026-07-26 - KATAV YouTube pipeline fixes Y1-Y6 (model: Kimi K2.7)
- Y1: URLs are canonicalised to watch?v=<id>; --no-playlist now applied to the
  real download call, not only the metadata probe.
- Y2: audio-only download to Outputs/_url_cache as <id>.mp3 with a verified,
  non-guessed output path and a reuse cache.
- Y3: per-URL failure isolation, ANSI stripping, actionable sign-in message,
  cookies-from-browser actually wired into the download.
- Y4: downloaded audio is handed to the transcription stage; real playlists are
  expanded into separate queue items; duration filled from the downloaded file.
- Y5: ADD URL no longer blocks the Gradio request thread.
- Y6: Whisper subprocess arguments are built as a list, fixing
  "Invalid path -> --threads".

## 2026-07-26 - KATAV fixes K1-K10
- K1 startup: add_file ran a 15s ffprobe per file and add_url ran yt_dlp.extract_info with no
  timeout, both inside prepare_start before any log line. Probes are now non-blocking and the
  startup stages are timestamped.
- K2 ETA: BATCH DUR renamed TOTAL AUDIO; single-item batches hide the batch row; ETA now
  derives from measured throughput.
- K3 exit: replaced taskkill /IM python.exe with per-PID taskkill /T /F using .katav_pids;
  os._exit is now the last statement.
- K4 full cycle: transcription now hands its produced paths to the translation stage.
- K5 languages: the skip test was a substring match, so "he" inside a filename silently
  skipped Hebrew. Replaced with strict token matching plus FORCE ALL LANGUAGES.
- K6 output: added unique_path; results are never overwritten.
- K7 translate progress: per-chunk [PROGRESS_TRANS] and a real ETA.
- K8 URLs: ADD URL now logs and enqueues, the field clears, and a clipboard PASTE was added
  using a new read_clipboard_text that does not filter through os.path.exists.
- K9 yt-dlp: noplaylist added after a radio playlist caused a different video id to be
  downloaded; cookie support and ANSI stripping added.
- K10 brand: renamed to KATAV across UI, launcher and dialogs.
- Commits: b637872, 7ac4b58, 531eb37, 99df2ed, fc6f24c, a36e53d, fdacf8c, 51de1b0, 5bcea68, brand commit.
- Nothing was pushed.
