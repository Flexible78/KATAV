"""Classify source input without downloading, executing, or persisting it."""
import os
import re
from urllib.parse import unquote, urlsplit

MEDIA_EXTENSIONS = frozenset({'.mp4', '.mkv', '.avi', '.mp3', '.wav', '.m4a', '.flac', '.ogg'})
DOCUMENT_EXTENSIONS = frozenset({'.srt', '.txt', '.csv', '.json', '.pdf', '.md'})


def path_identity(path):
    return os.path.normcase(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))


def merge_paths(existing, incoming):
    result, seen = [], set()
    for path in [*(existing or '').split('|'), *incoming]:
        path = str(path).strip().strip('\"').strip("'")
        if path and path_identity(path) not in seen:
            seen.add(path_identity(path))
            result.append(path)
    return ' | '.join(result)


def classify_sources(text='', files=None):
    """Return URL/media/document lists and actionable rejects; directories are shallow."""
    result = {'urls': [], 'media': [], 'documents': [], 'errors': []}
    entries = [item.strip().strip('\"').strip("'")
               for item in re.split(r'[\r\n|]+', text or '') if item.strip()]
    entries.extend(str(getattr(item, 'name', item)) for item in (files or []))
    seen = set()

    def add_file(path):
        suffix = os.path.splitext(path)[1].lower()
        kind = 'media' if suffix in MEDIA_EXTENSIONS else 'documents' if suffix in DOCUMENT_EXTENSIONS else None
        if kind:
            identity = path_identity(path)
            if identity not in seen:
                seen.add(identity)
                result[kind].append(os.path.abspath(path))
            return True
        return False

    for entry in entries:
        try:
            parsed = urlsplit(entry) if re.match(r'^[a-zA-Z]+://', entry) else None
            if parsed:
                parsed.port
        except ValueError:
            result['errors'].append('Malformed URL: ' + entry[:100])
            continue
        if parsed and parsed.scheme.lower() in ('http', 'https'):
            if not parsed.hostname or parsed.username or parsed.password:
                result['errors'].append('Invalid URL (use an http(s) link without embedded credentials).')
            elif parsed.hostname.lower() in ('open.spotify.com', 'spotify.com'):
                result['errors'].append('Spotify is DRM-protected; use an audio file or a supported media link.')
            elif entry not in result['urls']:
                result['urls'].append(entry)
            continue
        if parsed and parsed.scheme.lower() == 'file':
            entry = unquote(parsed.path)
            if parsed.netloc and parsed.netloc.lower() != 'localhost':
                entry = '//' + parsed.netloc + entry
            elif re.match(r'^/[A-Za-z]:', entry):
                entry = entry[1:]
        path = os.path.expandvars(os.path.expanduser(entry))
        if os.path.isdir(path):
            try:
                count = 0
                with os.scandir(path) as children:
                    for child in sorted(children, key=lambda item: item.name.casefold()):
                        if child.is_file() and add_file(child.path):
                            count += 1
                if not count:
                    result['errors'].append('Folder contains no supported media or documents: ' + os.path.basename(path))
            except OSError:
                result['errors'].append('Cannot read folder: ' + os.path.basename(path))
        elif os.path.isfile(path):
            if not add_file(path):
                result['errors'].append('Unsupported file type: ' + os.path.basename(path))
        else:
            result['errors'].append('Not a readable file, folder, or http(s) link: ' + entry[:100])
    return result
