

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

---

## Snapshot 2026-07-26 — AA1-AA7 Bug-fix release (KATAV)

### Summary
Batch of fixes for translation duplication, queue lifecycle, honest ETA, single weighted progress bar, source-language skip, safe tests, and release hygiene.

### What changed
- **AA1** — `ai_translator.py`: deduplicated the translation source list, dropped files with `_TRANSLATED_` in the name, added a module-level singleton guard to prevent concurrent `translate_content` runs, and added per-run `(path, language)` duplicate skipping with a single batch-finish log line.
- **AA2** — `queue_manager.py`, `whisper_core.py`, `gradio_app.py`: moved queue item lifecycle management from the log parser into the batch loop; `mark_started`, `mark_item_running`, `mark_item_done`, `mark_item_failed`, and per-line `update_item_progress` are now called from `whisper_core.py`. Fixed `[PROGRESS_FILE]` format to four fields so the parser accepts it. Removed duplicate queue debug rendering from the UI.
- **AA3** — `utils.py`, `whisper_core.py`, `gradio_app.py`: added `parse_whisper_progress` in `utils.py`, computed honest remaining time from Whisper’s own `elapsed<<remaining` field, and fed it into batch ETA. Replaced hardcoded "API" speed with real `x` during transcription and chunk/min during translation.
- **AA4** — `gradio_app.py`: replaced separate transcription/translation bars with one weighted 70/30 bar, added phase labels (`TRANSCRIBE - file X/Y - XX%` / `TRANSLATE - file X/Y - LANG - chunk A/B`), removed `single_item_mode` bar hiding and the dead second progress widget.
- **AA5** — `ai_translator.py`, `whisper_core.py`, `queue_manager.py`, `gradio_app.py`: added `lang_code` helper, stored faster-whisper detected language in queue item metadata, and skipped target languages identical to the source language unless `FORCE ALL LANGUAGES` is enabled.
- **AA6** — `test_queue.py`: fixed private attribute names (`_items`, `_next_idx`, `_cancelled`) and mocked `subprocess.run` so the test never calls a real `shutdown /s`.
- **AA7** — `.gitignore`: verified and ensured all required ignore rules are present; confirmed no tracked secrets, no live keys, and no user-specific absolute paths in README/docs.

### Files changed
- `ai_translator.py` — deduplication, singleton guard, source-language detection, same-language skip.
- `whisper_core.py` — queue lifecycle hooks, detected-language metadata, progress line parsing for ETA.
- `queue_manager.py` — lifecycle methods, progress updates, detected-language helpers.
- `gradio_app.py` — progress panel rewrite, queue status rendering, language dropdown passed to translator.
- `utils.py` — `WHISPER_PROGRESS_RE`, `parse_whisper_progress`.
- `test_queue.py` — attribute fixes, shutdown mocking.
- `.gitignore` — verified/added release-hygiene ignore rules.

### Commits
- `ec68fda` fix(translate): deduplicate the translation source list and never re-translate outputs
- `c1ea3ed` fix(queue): start the item lifecycle from the batch loop, not from the log parser
- `64cc9a9` feat(eta): honest remaining time from Whisper progress and measured speed
- `ba19b36` feat(ui): one weighted progress bar for transcription and translation
- `f44bcae` fix(translate): skip target languages identical to the source language
- `8e797a5` test(queue): fix attribute names and never trigger a real shutdown
- `1888344` chore(release): verify the public tree carries no secrets

### Verification results
- AST check: all `.py` files parse without syntax errors — `AST OK`.
- `test_queue.py`: 29/29 passed.
- `test_url_pipeline.py`: 14/14 passed.
- No leftover `check_aa*.py` scripts.
- `git ls-files | findstr /i "key secret token" | findstr /v /i ".example."` — no matches.
- `git ls-files | findstr /i ".env .bundle .katav_pids"` — no matches.
- Live key/absolute-path scan of tracked files — no matches.
- `git diff --check` — clean (no whitespace errors).
- `README.md`, `docs/USAGE.md`, `docs/SETUP.md` contain no user-specific local paths.
- Example files `whisper_api_keys.example.json` and `whisper_settings.example.json` contain only empty/placeholder values.

### What was not done
- GUI runtime verification (requires manual owner testing with real media).
- Full transcription + translation end-to-end smoke test (requires Faster-Whisper-XXL and API keys).
- Pushed to `origin/main`; full bundle backup created at `..\\KATAV_full_backup.bundle`.

## 2026-07-26 — BB1-BB3 hotfix (model: Kimi K2.7)
- **BB1** — `ai_translator.py`: removed two local assignments that shadowed the module-level `lang_code` helper inside `translate_content`. The shadowing caused `UnboundLocalError` and prevented EN/HE translations from starting.
- **BB2** — `start.bat`, `utils.py`: fixed EXIT so it closes both console windows. `start.bat` now writes `.katav_pids` in ASCII, uses `cmd /c` so consoles close automatically, and records both `cmd.exe` and child `python.exe` PIDs. `kill_program` now reads the PID file in binary (tolerant of UTF-16LE/UTF-8/ANSI), falls back to ports 8080 and 7861 with parent `cmd.exe` resolution, kills by window title as a last resort, and logs `[EXIT] killed pids: ... | by title: ...` before exit.
- **BB3** — `main.py`: added a targeted `warnings.filterwarnings("ignore", category=FutureWarning, module="google.generativeai")` so the deprecation notice does not clutter logs. Migration to `google.genai` is recorded as tech debt.

### Verification
- AST check: all `.py` files parse without syntax errors — `AST OK`.
- `ai_translator.py` AST shadow check: `SHADOWS: []`.
- `lang_code` helper returns `ru en he` for the three supported languages.

### Commits
- `b0b01e9` fix(translate): stop shadowing the lang_code helper inside translate_content
- `3a0effc` fix(exit): close both console hosts and record PIDs in a readable encoding
- `e608ba2` chore(deps): silence the google.generativeai deprecation notice and record the migration debt

### What was not done
- GUI runtime verification (requires manual owner testing with real media).
- Migration from `google.generativeai` to `google.genai` — this is a separate task; only the Google Gemini provider is affected, and the current provider code is intentionally left unchanged to avoid introducing new failures.

## 2026-07-26 — BC1-BC4 (KATAV run 1, model: Kimi K2.7)
- **BC1** — `gradio_app.py`, `docs/USAGE.md`: EXIT button label changed to `EXIT (app + consoles)` and a client-side JS handler paints a "KATAV stopped" page and tries `window.close()` before the server-side `kill_program` runs. Documented that browser security may block automatic tab closure.
- **BC2** — `config.py`, `gradio_app.py`, `ai_translator.py`, `file_operations.py`, `dialogs.py`, `srt_processor.py`: translated system prompts and user-facing/log strings from Russian to English; centralized target-language labels/constants in `config.py` (`TARGET_LANGUAGES`, `TARGET_LANGUAGE_DEFAULTS`, `TARGET_LANGUAGE_MARKERS`, `TARGET_LANGUAGE_CODE_MAP`); UI target languages are now `Russian/English/Hebrew` with default `["English", "Hebrew"]`; removed dead duplicate `libs/ai_translator.py`.
- **BC3** — `gradio_app.py`, `ai_translator.py`, `docs/USAGE.md`: renamed the `FORCE ALL LANGUAGES` checkbox to `TRANSLATE ANYWAY (ignore language auto-detection)` with an `info=` tooltip; log strings now reference the new label.
- **BC4** — `gradio_app.py`, `utils.py`, `whisper_core.py`, `ai_translator.py`, `srt_processor.py`: added a visible `PLAIN TEXT (no numbers, no timestamps)` checkbox; added robust `clean_srt_text` helper in `utils.py`; wired `plain_text_output` through transcription and translation so every produced/translated SRT/VTT also writes a `*_CLEAN.txt` sidecar.

### Verification
- AST check: all `.py` files parse without syntax errors — `AST OK`.
- `check_bc4.py` (temporary) passed for Russian, English, and Hebrew RTL samples; no `-->` or standalone numbers leaked; words not glued.
- `test_queue.py`: 29/29 passed.
- `test_url_pipeline.py`: 14/14 passed.
- `libs/ai_translator.py` was removed after confirming no imports.

### Commits
- (planned) `feat(exit): tell the browser tab the app is gone and try to close it`
- (planned) `chore(ui): make every interface and log string English`
- (planned) `feat(ui): explain the force-translation checkbox in plain words`
- (planned) `feat(output): PLAIN TEXT option that strips SRT numbers and timestamps`

### What was not done
- GUI runtime verification.
- BC5-BC8 implemented in a second run (see below).

### Risks
- `clean_srt_text` relies on SRT-block separation (`\n\n`); unusual single-newline subtitles may need extra handling.
- `_CLEAN.txt` sidecars are excluded from the translation-ready list, but other `.txt` outputs may still be picked up if produced.

---

## 2026-07-26 — BC5-BC8 (KATAV run 2, model: Kimi K2.7)
- **BC5** — `gradio_app.py`, `whisper_core.py`, `queue_manager.py`, `test_url_pipeline.py`: added `➕ ADD PLAYLIST` button next to `➕ ADD URL`; `expand_playlist` uses `yt_dlp.YoutubeDL` with `extract_flat="in_playlist"`, `skip_download=True`, and `socket_timeout=10`; auto-generated lists (`RD`/`UL`) are rejected; duplicates are removed; capped at 50 items with a log message; each video becomes a canonical `watch?v=<id>` queue item with `playlist_index` and `playlist_title` metadata; filenames are prefixed with `001_`, `002_`, etc.
- **BC6** — `gradio_app.py`, `batch_results.py`, `queue_manager.py`: added `BATCH RESULTS` UI with `JOIN INTO ONE FILE`, `ZIP RESULTS`, and a download component; `join_batch_results` groups produced text/subtitle files by inferred language and writes one `batch_JOINED_<LANG>.txt` per language with `## 001 — <name>` headers; `zip_batch_results` creates a `batch_<YYYYMMDD_HHMM>.zip` with `ZIP_DEFLATED`, UTF-8 arcnames, excludes `_url_cache` and audio unless `include audio` is checked.
- **BC7** — `gradio_app.py`, `config.py`, `ui_manager.py`: introduced CSS custom properties (`--katav-bg`, `--katav-panel`, `----katav-text`, `--katav-accent`, `--katav-border`) and a `🌓 Toggle Theme` button; a client-side JS toggles the `katav-light` class on `document.body`, persists the choice in `localStorage`, and restores it on page load; the setting is also saved in `ui_state`.
- **BC8** — `whisper_core.py`, `requirements.txt`, `docs/USAGE.md`: added public Google Drive shared-link support using lazy `gdown==5.2.0`; files are downloaded to `Outputs/_url_cache`; private/restricted links produce a clear error message; explicitly did not implement authorized Drive access or Spotify (documented in `docs/USAGE.md`).

### New files
- `batch_results.py` — `join_batch_results` and `zip_batch_results` helpers.

### Modified files
- `whisper_core.py` — playlist expansion, Google Drive download, produced-files tracking, URL processing refactor.
- `queue_manager.py` — `produced_files` field and helpers, playlist metadata propagation.
- `gradio_app.py` — ADD PLAYLIST button, BATCH RESULTS UI (JOIN/ZIP), theme toggle.
- `config.py` — CSS variables for light/dark theme.
- `requirements.txt` — added `gdown==5.2.0`.
- `docs/USAGE.md` — documented Google Drive limitations and Spotify workaround.
- `test_url_pipeline.py` — added tests for playlist expansion (dedup, cap, RD/UL rejection, Google Drive, batch results).

### Verification
- AST check: all `.py` files parse without syntax errors — `AST OK`.
- `test_queue.py`: 29/29 passed.
- `test_url_pipeline.py`: 21/21 passed.

---

### Risks
- The `cmd /c` change means launcher windows close automatically when Python exits; users must rely on `app.log` and the LIVE LOG for diagnostic messages.
- Title-based fallback uses `taskkill /F /T /FI "WINDOWTITLE eq KATAV*"`, which could affect other windows with matching titles if any exist.

### Tech debt
- Migrate the Google Gemini provider from `google.generativeai` to `google.genai`. This is a standalone provider-only change and should be tackled separately to limit regression risk.

- The 70/30 progress split assumes every full-cycle run passes through both phases. A standalone translation run is detected and falls back to 0-100% translation-only progress.
- Same-language skip relies on the `LANGUAGE` setting or detected-language metadata; if both are `auto` and filename tokens are ambiguous, the skip may not trigger.
- Queue lifecycle hooks are now in `whisper_core.py`; any future direct callers of the transcription function that do not use the queue path will bypass progress updates.
