# KATAV - Windows installation for complete beginners

This guide assumes **zero experience**: no Python, no terminal, no Git.
Just follow the steps in order. Total time: about 15-25 minutes.

Other languages: **[Русский](INSTALL_WINDOWS_RU.md)** · **[עברית](INSTALL_WINDOWS_HE.md)**

If something breaks, go to [Problems and fixes](#problems-and-fixes) at the bottom.

## What you will get

- KATAV installed in a folder, for example `C:\KATAV`
- A page in your browser where you drop an audio or video file and get text back
- Everything runs on your own PC: transcription needs **no internet and no API key**

## Before you start

- Windows 10 or 11, 64-bit
- About 10 GB of free disk space
- An NVIDIA graphics card is recommended (without it KATAV still works, only slower)
- You do **not** need to be an administrator for the standard path below

---

## Step 1 - Install Python

1. Open <https://www.python.org/downloads/windows/>
2. Download **Windows installer (64-bit)** for Python 3.12 or newer.
3. Run the downloaded file.
4. **Very important:** on the first screen tick the checkbox **Add python.exe to PATH** (bottom of the window). Without it nothing below will work.
5. Click **Install Now**, wait, then **Close**.
6. Check it: press the **Win** key, type `powershell`, press **Enter**, then type:

```powershell
python --version
```

You should see something like `Python 3.12.6`. If you see an error, see [Problems and fixes](#problems-and-fixes).

---

## Step 2 - Download KATAV

### Option A - without Git (simplest)

1. Open <https://github.com/Flexible78/KATAV>
2. Click the green **Code** button, then **Download ZIP**.
3. In your **Downloads** folder right-click the ZIP file and choose **Extract All...**
4. Move/rename the extracted folder so that the result is `C:\KATAV` and the file `main.py` is **directly inside it**.

Correct:

```
C:\KATAV\main.py
```

Wrong (one folder too deep - move the inner folder up):

```
C:\KATAV\KATAV-main\main.py
```

### Option B - with Git

```powershell
cd C:\
git clone https://github.com/Flexible78/KATAV.git
```

---

## Step 3 - Download the speech engine (Faster-Whisper-XXL)

KATAV itself does not contain the recognition engine. You download it once, separately.

1. Open <https://github.com/Purfview/whisper-faster-XXL>
2. Go to **Releases** and download the Windows archive.
3. Extract it so the folder sits **next to** the KATAV folder:

```
C:\
|-- KATAV\
|   |-- main.py
|-- Faster-Whisper-XXL\
    |-- faster-whisper-xxl.exe
```

KATAV looks for `faster-whisper-xxl.exe` in its own folder and in the parent folder, so with this layout no configuration is needed.
Other ways to point KATAV at the file are described in [SETUP.md](SETUP.md).

---

## Step 4 - Open a terminal inside the KATAV folder

1. Open **File Explorer** and go to `C:\KATAV`.
2. Click once on the **address bar** at the top (where the path is written).
3. Type `powershell` and press **Enter**.

A blue/black window opens and the first line already ends with `C:\KATAV`. All commands below are typed in this window (paste with right-click).

### Other ways to open the terminal

1. Press **Win**, type `powershell`, press **Enter**. Then move into the project folder yourself:

   ```powershell
   cd C:\KATAV
   ```

2. Press **Win + X** and choose **Terminal** or **Windows PowerShell**.
3. In File Explorer hold **Shift**, right-click empty space inside the folder, and choose **Open PowerShell window here** / **Open in Terminal**.

### PowerShell or Command Prompt (cmd)?

All commands in this guide are written for **PowerShell** (the default terminal in Windows 10/11). If you prefer the old **Command Prompt** (`cmd`), everything is the same except activating the environment:

| Terminal | Activation command |
| --- | --- |
| PowerShell | `.venv\Scripts\Activate.ps1` |
| Command Prompt (cmd) | `.venv\Scripts\activate.bat` |

### How to run the terminal as Administrator

**In most cases you do not need this** - see the next section first. If you do need it:

1. Press **Win** and type `powershell` (or `cmd`).
2. On the right of the search result click **Run as administrator**. Keyboard shortcut: **Ctrl + Shift + Enter**.
   - Alternative: **Win + X**, then **Terminal (Admin)** / **Windows PowerShell (Admin)**.
3. Confirm the Windows UAC prompt (**Yes**).
4. An administrator window always opens in `C:\Windows\System32`, so go to the project folder first:

   ```powershell
   cd C:\KATAV
   ```

5. To be sure you really are an administrator, the window title contains **Administrator**, or run:

   ```powershell
   ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
   ```

   `True` means the window is elevated.

### Do you actually need Administrator rights?

| Situation | Administrator needed? |
| --- | --- |
| Normal install into `C:\KATAV` or `C:\Users\<your name>\KATAV` | **No** |
| Creating `.venv`, running `pip install`, running `python main.py` | **No** |
| Transcribing files, translating, using the browser interface | **No** |
| Project placed inside `C:\Program Files` or in the root of the system drive | Yes (better: move the project to `C:\KATAV`) |
| `Access is denied` while creating `.venv` or writing to `Outputs` | Yes, once - or move the project to a normal user folder |
| Installing Python **for all users**, or changing a **system-wide** environment variable | Yes |
| Allowing a port through the firewall (only if you expose the app to your LAN) | Yes |

> **Do not run KATAV as administrator every day.** Files created by an elevated process can later be hard to delete or overwrite from a normal window. If you already created `.venv` as administrator and now hit permission errors, delete the `.venv` folder and repeat Step 5 in a normal (non-elevated) terminal.

---

## Step 5 - Install KATAV dependencies

Type these three commands, one at a time, pressing **Enter** after each:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

- The first command creates a private Python environment inside the project (folder `.venv`).
- After the second command the line starts with `(.venv)`. That is correct and expected.
- The third command downloads the libraries. It can take several minutes. Warnings in yellow are fine; only red `ERROR` lines matter.

If the second command fails with a message about scripts being disabled, run this once and repeat it:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

---

## Step 6 - Start KATAV

```powershell
python main.py
```

Wait for a line similar to:

```
Running on local URL:  http://127.0.0.1:7861
```

Open that address in your browser (usually it opens automatically). That page **is** KATAV.

To stop the app: press **Ctrl + C** in the terminal window, or press **EXIT** in the interface.

---

## Step 7 - Your first transcription

1. Drag an audio or video file into the upload area, or paste a YouTube link.
2. Choose the target options you need (subtitles, plain text, translation).
3. Press the start button.
4. When it finishes, the files appear in the `Outputs` folder inside `C:\KATAV`, and you can download them from the page.

Transcription is fully offline. Only translation and downloading online videos need internet.

---

## Step 8 - How to start it next time

Every next time you only need:

```powershell
cd C:\KATAV
.venv\Scripts\Activate.ps1
python main.py
```

Shortcut: in `C:\KATAV` you can also double-click **`start.bat`**, which performs the same launch for you.

---

## Problems and fixes

| Message you see | What it means | What to do |
| --- | --- | --- |
| `python : The term 'python' is not recognized` | Python is not in PATH | Reinstall Python and tick **Add python.exe to PATH**, then open a new terminal |
| `... Activate.ps1 cannot be loaded because running scripts is disabled` | PowerShell script policy | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`, then activate again |
| `faster-whisper-xxl.exe was not found` | The engine from Step 3 is missing or in the wrong place | Check the folder layout in Step 3, or set `$env:WHISPER_EXE = "C:\Tools\Faster-Whisper-XXL\faster-whisper-xxl.exe"` before `python main.py` |
| `Cannot find empty port in range: 7861-7861` | KATAV is already running in another window | Close the other window, or run `$env:GRADIO_SERVER_PORT='7899'` and start again |
| `pip` fails with red errors | Outdated pip | Run `python -m pip install --upgrade pip` and repeat `pip install -r requirements.txt` |
| Transcription is very slow | No NVIDIA GPU, so it runs on the CPU | Normal behaviour: choose a smaller model, or use a machine with a GPU |
| Browser shows nothing | The page did not open automatically | Copy the `http://127.0.0.1:...` address from the terminal into the browser manually |
| Russian/Hebrew text looks like garbage | Editor does not read UTF-8 | Open the file with VS Code, Word, or Notepad++ instead of old Notepad |
| `Access is denied` when creating `.venv` or writing files | The folder is protected (for example inside `Program Files`) | Move the project to `C:\KATAV`, or open the terminal as Administrator (see Step 4) |
| `.venv\Scripts\activate.bat is not recognized` in PowerShell | Wrong activation command for this terminal | In PowerShell use `.venv\Scripts\Activate.ps1`; `activate.bat` is only for `cmd` |

---

## Do I need API keys?

- **Transcription (speech to text): no.** It is fully local and free.
- **AI translation: yes**, a key for one provider. See [SETUP.md](SETUP.md). Keys go into your own local `whisper_api_keys.json` file, which is never uploaded anywhere.

## How to uninstall

Delete the `C:\KATAV` folder and the `Faster-Whisper-XXL` folder. Nothing is written to the Windows registry.

## Where to go next

- Detailed configuration: [SETUP.md](SETUP.md)
- How to use every feature: [USAGE.md](USAGE.md)
