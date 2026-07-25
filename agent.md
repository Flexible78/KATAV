

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
