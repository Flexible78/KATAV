"""study_deck.py — Build a frequency-based study deck from transcripts (BD7).

Called after transcription + clean text is ready. Produces:
  *_DECK.csv        — UTF-8 BOM, semicolon-separated, for Excel
  *_DECK_anki.txt   — tab-separated front/back, for Anki/Quizlet
  *_DECK.md         — human-readable, grouped by frequency bands

All logic uses only the standard library.  None of the existing output
files are renamed or reformatted.  Errors are caught and logged but
never kill the transcription pipeline.
"""

import csv
import logging
import os
import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger("study_deck")


# ---------------------------------------------------------------------------
# Language-specific stopword lists and lemma rules
# ---------------------------------------------------------------------------
_STOPWORDS: Dict[str, Set[str]] = {
    "ru": {
        "и", "в", "не", "на", "я", "что", "он", "с", "а", "как", "это", "то",
        "по", "но", "все", "она", "так", "его", "мы", "у", "к", "же", "ты",
        "за", "от", "о", "из", "ее", "бы", "был", "быть", "еще", "или", "да",
        "мне", "их", "вы", "если", "чем", "без", "для", "ни", "когда", "была",
        "очень", "мне", "быть", "там", "уже", "под", "при", "об", "чтобы",
        "может", "будет", "до", "было", "себя", "которые", "который",
        "которых", "которая", "которое", "про", "только", "во", "со",
        "этого", "этой", "этом", "эту", "меня", "ему",
    },
    "en": {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "out", "off", "over",
        "under", "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "all", "both", "each", "few", "more", "most",
        "other", "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "just", "about", "up", "it", "its", "me",
        "my", "we", "our", "you", "your", "he", "she", "they", "them", "his",
        "her", "him", "i", "am", "that", "this", "these", "those", "what",
        "who", "whom", "which", "and", "but", "or", "if", "while", "because",
    },
    "he": {
        "את", "של", "על", "לא", "זה", "עם", "הוא", "היא", "אני", "אתה", "אנחנו",
        "הם", "הן", "מה", "מי", "איך", "למה", "איפה", "מתי", "כי", "אבל", "או",
        "גם", "רק", "כל", "הרבה", "קצת", "שוב", "עוד", "בין", "אחרי", "לפני",
        "אז", "כן", "יש", "אין", "אם", "כמו", "אותה", "אותו", "להם", "להן",
        "לי", "לך", "לו", "לה", "בשביל", "בגלל", "כדי", "יכול", "צריך", "עושה",
    },
}


def _lemma_he(word: str) -> str:
    """Simple Hebrew lemmatiser: strip common prefixes/suffixes."""
    prefixes = ("ו", "ה", "ש", "ב", "ל", "מ", "כ")
    suffixes = ("ים", "ות", "ה", "י", "ך", "נו", "כן", "הן")
    stem = word
    while stem and stem[0] in prefixes and len(stem) > 2:
        stem = stem[1:]
    for sfx in sorted(suffixes, key=len, reverse=True):
        if stem.endswith(sfx) and len(stem) - len(sfx) >= 2:
            stem = stem[: -len(sfx)]
            break
    return stem


def _lemma_ru(word: str) -> str:
    """Simple Russian lemmatiser: strip common endings."""
    endings = ("ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими",
               "ой", "ей", "ая", "яя", "ое", "ее", "ые", "ие",
               "ом", "ем", "ую", "юю", "ых", "их", "ым", "им",
               "а", "я", "ы", "и", "у", "ю", "е", "о", "ам", "ям")
    for end in sorted(endings, key=len, reverse=True):
        if word.endswith(end) and len(word) - len(end) >= 2:
            return word[: -len(end)]
    return word


def _lemma_en(word: str) -> str:
    """Simple English lemmatiser: strip common suffixes."""
    if word.endswith("ing") and len(word) > 4:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        return word[:-1]
    return word


_LEMMATISERS = {
    "he": _lemma_he,
    "ru": _lemma_ru,
    "en": _lemma_en,
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def build_study_deck(
    clean_text: str,
    translated_text: str,
    srt_text: str,
    base_name: str,
    output_dir: str,
    source_lang_code: str = "auto",
    min_count: int = 2,
    max_terms: int = 300,
    known_terms_file: str = "",
) -> List[str]:
    """Build a frequency-based study deck from a transcript.

    Args:
        clean_text: Clean plain text (from *_CLEAN.txt) in the source language.
        translated_text: Translated clean text paired by subtitle block.
        srt_text: Original SRT content (to extract timestamps from).
        base_name: Base filename for output files (no extension).
        output_dir: Directory to write output files.
        source_lang_code: Two-letter language code for the source text.
        min_count: Minimum occurrences for a word/phrase to be included.
        max_terms: Maximum number of terms in the deck.
        known_terms_file: Path to 'known_terms.txt' for accumulation.

    Returns:
        List of paths to generated files.
    """
    if not clean_text or not clean_text.strip():
        return []

    lang = source_lang_code if source_lang_code in ("ru", "en", "he") else "en"
    stopwords = _STOPWORDS.get(lang, set())
    lemmatise = _LEMMATISERS.get(lang, lambda w: w)

    # ── Parse sentences and timestamps from SRT ──
    sentences, timestamps = _parse_sentences_from_srt(srt_text)

    # ── Tokenize source text ──
    tokens = _tokenize(clean_text)
    word_counts = Counter(t for t in tokens if t not in stopwords and not t.isdigit() and len(t) > 1)

    # ── N-gram phrases (2–4 words) ──
    phrase_counts = _ngram_counts(tokens, stopwords)

    # ── Filter by min_count, limit by max_terms ──
    all_items = []
    for term, count in word_counts.most_common():
        all_items.append((term, count))
    for phrase, count in phrase_counts.most_common():
        all_items.append((phrase, count))

    all_items.sort(key=lambda x: -x[1])

    # Load known terms to exclude
    known_terms = _load_known_terms(known_terms_file)

    deck_rows = []
    seen_terms: Set[str] = set()
    for term, count in all_items:
        if len(deck_rows) >= max_terms:
            break
        if count < min_count:
            continue
        norm_term = term.lower().strip()
        if norm_term in known_terms or norm_term in seen_terms:
            continue
        seen_terms.add(norm_term)

        lemma = lemmatise(term)
        sentence, translation, first_ts = _find_example(
            term, sentences, translated_text, timestamps
        )
        deck_rows.append({
            "term": term,
            "lemma": lemma,
            "count": count,
            "first_timestamp": first_ts,
            "sentence": sentence,
            "translation": translation,
        })

    if not deck_rows:
        return []

    # ── Write output files ──
    written = []
    os.makedirs(output_dir, exist_ok=True)

    # CSV (UTF-8 with BOM, semicolon-separated)
    csv_path = os.path.join(output_dir, f"{base_name}_DECK.csv")
    written.extend(_write_csv(csv_path, deck_rows))

    # Anki tab-separated
    anki_path = os.path.join(output_dir, f"{base_name}_DECK_anki.txt")
    written.extend(_write_anki(anki_path, deck_rows))

    # Human-readable Markdown
    md_path = os.path.join(output_dir, f"{base_name}_DECK.md")
    written.extend(_write_markdown(md_path, deck_rows))

    # Accumulate known terms
    if known_terms_file:
        _append_known_terms(known_terms_file, [r["term"] for r in deck_rows])

    return written


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Extract lowercase word tokens, stripping punctuation."""
    return re.findall(r"[а-яёא-תa-z]{2,}", text.lower())


def _ngram_counts(tokens: List[str], stopwords: Set[str]) -> Counter:
    """Build n-gram counts for 2-4 word phrases (skip stopword-only phrases)."""
    counts: Counter = Counter()
    for n in (2, 3, 4):
        for i in range(len(tokens) - n + 1):
            ngram = tokens[i : i + n]
            # Require at least one non-stopword
            if all(w in stopwords for w in ngram):
                continue
            phrase = " ".join(ngram)
            counts[phrase] += 1
    return counts


def _parse_sentences_from_srt(srt_text: str) -> Tuple[List[str], Dict[int, str]]:
    """Parse SRT blocks and return (sentence list, {block_index: timestamp})."""
    if not srt_text:
        return [], {}
    # Normalize line endings
    srt_text = srt_text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    sentences: List[str] = []
    timestamps: Dict[int, str] = {}
    for idx, block in enumerate(blocks):
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        # Look for timestamp line
        ts_line = ""
        text_lines = []
        for line in lines:
            if re.match(r"\d{2}:\d{2}:\d{2}[,\.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,\.]\d{3}", line):
                ts_line = line.split("-->")[0].strip().replace(",", ".")
            elif not line.isdigit():
                text_lines.append(line)
        if text_lines:
            sentence = " ".join(text_lines)
            sentences.append(sentence)
            if ts_line:
                timestamps[len(sentences) - 1] = ts_line
    return sentences, timestamps


def _find_example(
    term: str,
    sentences: List[str],
    translated_text: str,
    timestamps: Dict[int, str],
) -> Tuple[str, str, str]:
    """Find the first sentence containing *term* and its translation."""
    term_lower = term.lower()
    for idx, sentence in enumerate(sentences):
        if term_lower in sentence.lower():
            ts = timestamps.get(idx, "")
            # Try to find corresponding translation (same block index)
            trans_sentences = translated_text.split("\n\n") if translated_text else []
            translation = trans_sentences[idx] if idx < len(trans_sentences) else ""
            return sentence, translation, ts
    return "", "", ""


def _load_known_terms(path: str) -> Set[str]:
    """Load the set of already-known terms from a file (one per line)."""
    if not path or not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {line.strip().lower() for line in f if line.strip()}
    except Exception:
        return set()


def _append_known_terms(path: str, new_terms: List[str]):
    """Append new terms to the known-terms file."""
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for term in new_terms:
                f.write(term.lower().strip() + "\n")
    except Exception as e:
        log.warning("Failed to write known_terms.txt: %s", e)


def _write_csv(path: str, rows: List[Dict]) -> List[str]:
    """Write DECK.csv (UTF-8 BOM, semicolons)."""
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["term", "lemma", "count", "first_timestamp", "sentence", "translation"],
                delimiter=";",
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writeheader()
            writer.writerows(rows)
        return [path]
    except Exception as e:
        log.warning("Failed to write %s: %s", path, e)
        return []


def _write_anki(path: str, rows: List[Dict]) -> List[str]:
    """Write DECK_anki.txt (tab-separated front/back)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            for row in rows:
                front = f"{row['term']} ({row['lemma']})"
                back = row.get("translation", "") or row.get("sentence", "")
                f.write(f"{front}\t{back}\n")
        return [path]
    except Exception as e:
        log.warning("Failed to write %s: %s", path, e)
        return []


def _write_markdown(path: str, rows: List[Dict]) -> List[str]:
    """Write DECK.md grouped by frequency bands."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Study Deck ({len(rows)} terms)\\n\\n")
            bands = [
                ("High frequency (10+)", [r for r in rows if r["count"] >= 10]),
                ("Medium frequency (5–9)", [r for r in rows if 5 <= r["count"] < 10]),
                ("Low frequency (<5)", [r for r in rows if r["count"] < 5]),
            ]
            for label, band in bands:
                if not band:
                    continue
                f.write(f"## {label}\\n\\n")
                for row in band:
                    f.write(f"- **{row['term']}** ({row['lemma']}) — {row['count']}×\\n")
                    if row.get("first_timestamp"):
                        f.write(f"  ⏱ `{row['first_timestamp']}`\\n")
                    if row.get("sentence"):
                        f.write(f"  > {row['sentence']}\\n")
                    if row.get("translation"):
                        f.write(f"  > {row['translation']}\\n")
                    f.write("\\n")
        return [path]
    except Exception as e:
        log.warning("Failed to write %s: %s", path, e)
        return []


def build_course_deck(output_dir: str, known_terms_file: str = "") -> Optional[str]:
    """Collect all per-file *_DECK.csv files in output_dir and merge into COURSE_DECK.csv."""
    if not output_dir or not os.path.isdir(output_dir):
        return None
    deck_files = sorted([
        f for f in os.listdir(output_dir)
        if f.endswith("_DECK.csv") and f != "COURSE_DECK.csv"
    ])
    if not deck_files:
        return None

    all_rows: List[Dict] = []
    seen: Set[str] = set()
    for df in deck_files:
        try:
            with open(os.path.join(output_dir, df), "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f, delimiter=";")
                for row in reader:
                    key = (row.get("term", "") + row.get("sentence", "")).lower()
                    if key not in seen:
                        seen.add(key)
                        all_rows.append(row)
        except Exception:
            continue

    if not all_rows:
        return None

    out_path = os.path.join(output_dir, "COURSE_DECK.csv")
    _write_csv(out_path, all_rows)
    return out_path
