"""
google_drive.py — OAuth Installed App flow for private Google Drive files.

Public shared links are still tried first via gdown. If the file is not
public and the user has signed in, the Drive API v3 is used with a
read-only scope.
"""

import os
import re
import json
from typing import Optional, Tuple

from config import DEFAULT_OUTPUT_DIR
from utils import log_queue

CLIENT_SECRET_FILE = "google_client_secret.json"
TOKEN_FILE = "google_drive_token.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

_DRIVE_RE = re.compile(r"^https?://(?:www\.)?drive\.google\.com/file/d/([^/]+)/")
_DRIVE_RE_ALT = re.compile(r"[?&]id=([^&]+)")


def _url_cache_dir() -> str:
    cache = os.path.join(DEFAULT_OUTPUT_DIR, "_url_cache")
    os.makedirs(cache, exist_ok=True)
    return cache


def _extract_drive_file_id(url: str) -> str:
    """Extract the Google Drive file id from a shared link."""
    m = _DRIVE_RE.search(url)
    if m:
        return m.group(1)
    m = _DRIVE_RE_ALT.search(url)
    if m:
        return m.group(1)
    return ""


def _is_google_drive_url(url: str) -> bool:
    return "drive.google.com" in url


def _client_secret_exists() -> bool:
    return os.path.exists(CLIENT_SECRET_FILE)


def _load_credentials():
    """Return saved credentials or None."""
    try:
        from google.oauth2.credentials import Credentials
        if not os.path.exists(TOKEN_FILE):
            return None
        return Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    except Exception:
        return None


def _save_credentials(creds):
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    except Exception:
        pass


def get_drive_status() -> str:
    """Return a short status string for the UI."""
    if not _client_secret_exists():
        return "Google Drive: set up OAuth (see docs/SETUP.md)"
    creds = _load_credentials()
    if creds and creds.valid:
        try:
            from googleapiclient.discovery import build
            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            profile = service.about().get(fields="user(emailAddress)").execute()
            email = profile.get("user", {}).get("emailAddress", "unknown")
            return f"Google Drive: signed in as {email}"
        except Exception:
            pass
    return "Google Drive: not signed in"


def sign_in_to_google_drive() -> str:
    """Run the OAuth installed-app flow and return a status message."""
    if not _client_secret_exists():
        return (
            "Google Drive OAuth is not configured. "
            "Create a Desktop OAuth client in Google Cloud, download the JSON, "
            "and save it as google_client_secret.json next to main.py. "
            "See docs/SETUP.md for instructions."
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError as e:
        return f"Missing google-auth-oauthlib: {e}"

    creds = _load_credentials()
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        try:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        except Exception as e:
            return f"Google Drive sign-in failed: {e}"

    _save_credentials(creds)

    try:
        from googleapiclient.discovery import build
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        profile = service.about().get(fields="user(emailAddress)").execute()
        email = profile.get("user", {}).get("emailAddress", "unknown")
        return f"Google Drive: signed in as {email}"
    except Exception as e:
        return f"Signed in, but could not fetch profile: {e}"


def _download_public(url: str, file_id: str, output_dir: str) -> Optional[str]:
    """Try to download a public Google Drive file with gdown."""
    try:
        import gdown
    except ImportError:
        log_queue.put("[DRIVE] gdown is not installed. Run: pip install gdown==5.2.0\n")
        return None

    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"drive_{file_id}")
    try:
        downloaded = gdown.download(id=file_id, output=output_path, quiet=True)
        if downloaded and os.path.isfile(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            log_queue.put(f"[DRIVE] Downloaded: {output_path} ({size_mb:.2f} MB)\n")
            return output_path
    except Exception:
        pass
    return None


def _download_oauth(file_id: str, output_dir: str) -> Optional[str]:
    """Download a private Google Drive file via the Drive API."""
    creds = _load_credentials()
    if not creds or not creds.valid:
        return None
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"drive_{file_id}")
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        request = service.files().get(fileId=file_id, alt="media")
        with open(output_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    log_queue.put(f"[DRIVE] Download {int(status.progress() * 100)}%\n")
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        log_queue.put(f"[DRIVE] Downloaded via OAuth: {output_path} ({size_mb:.2f} MB)\n")
        return output_path
    except Exception as e:
        log_queue.put(f"[DRIVE] OAuth download failed: {e}\n")
        return None


def download_google_drive_file(url: str, output_dir: str) -> Optional[str]:
    """
    Download a Google Drive file. Public links are tried first; if that fails,
    an authenticated OAuth download is attempted if the user is signed in.
    """
    file_id = _extract_drive_file_id(url)
    if not file_id:
        log_queue.put(f"[DRIVE] Could not extract file id from link: {url}\n")
        return None

    public_path = _download_public(url, file_id, output_dir)
    if public_path:
        return public_path

    log_queue.put("[DRIVE] Public download failed. Trying OAuth...\n")
    if not _client_secret_exists():
        log_queue.put(
            "[DRIVE] Private file: sign in with Google Drive or make the link public. "
            "See docs/SETUP.md for OAuth setup.\n"
        )
        return None

    oauth_path = _download_oauth(file_id, output_dir)
    if oauth_path:
        return oauth_path

    log_queue.put(
        "[DRIVE] Could not download the file. Make the link public or sign in to Google Drive.\n"
    )
    return None


def is_google_drive_url(url: str) -> bool:
    return _is_google_drive_url(url)
