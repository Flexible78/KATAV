"""BD10: Verify language code migration and that suffix never equals TRANS."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TARGET_LANGUAGES, TARGET_LANGUAGE_CODE_MAP, TARGET_LANGUAGE_MARKERS


def test_target_languages_are_label_value_pairs():
    for pair in TARGET_LANGUAGES:
        assert isinstance(pair, (list, tuple)) and len(pair) >= 2, \
            f"Expected (label, code) pair, got {pair!r}"
        assert pair[1] in ("RU", "EN", "HE"), f"Unexpected code {pair[1]}"
    print("PASS: TARGET_LANGUAGES uses (label, code) pairs.")


def test_markers_keyed_by_code():
    for key in TARGET_LANGUAGE_MARKERS:
        assert key in ("RU", "EN", "HE"), f"Expected code key, got {key!r}"
    print("PASS: TARGET_LANGUAGE_MARKERS keyed by stable codes.")


def test_code_map_resolves_old_values():
    old_labels = [
        "Русский", "русский", "Russian", "ru", "rus",
        "English", "en", "eng",
        "עברית (Hebrew)", "עברית", "Hebrew", "he", "heb", "иврит",
    ]
    for label in old_labels:
        code = TARGET_LANGUAGE_CODE_MAP.get(label, None)
        assert code in ("RU", "EN", "HE"), f"{label!r} -> {code!r} (expected RU/EN/HE)"
    print(f"PASS: CODE_MAP resolves all {len(old_labels)} old labels.")


def test_code_map_self_mapping():
    for code in ("RU", "EN", "HE"):
        assert TARGET_LANGUAGE_CODE_MAP.get(code) == code, \
            f"Self-mapping missing for {code}"
    print("PASS: Stable codes map to themselves.")


def test_suffix_never_trans():
    from ai_translator import lang_code
    variants = TARGET_LANGUAGE_CODE_MAP
    suffixes = set()
    for label in variants:
        s = TARGET_LANGUAGE_CODE_MAP.get(label, lang_code(label).upper())
        suffixes.add(s)
    assert "TRANS" not in suffixes, f"Suffixes contain TRANS: {suffixes}"
    print(f"PASS: Suffixes never TRANS: {sorted(suffixes)}")


def test_ui_migration():
    from ui_manager import _migrate_lang_list

    old_values = ["Русский", "עברית (Hebrew)"]
    migrated = _migrate_lang_list(old_values)
    assert migrated == ["RU", "HE"], f"Migration failed: {migrated}"

    mixed = ["Russian", "EN", "עברית"]
    migrated = _migrate_lang_list(mixed)
    assert set(migrated) == {"RU", "EN", "HE"}, f"Mixed migration: {migrated}"

    garbage = ["Klingon", "English"]
    migrated = _migrate_lang_list(garbage)
    assert migrated == ["EN"], f"Garbage not discarded: {migrated}"

    codes = ["RU", "HE"]
    migrated = _migrate_lang_list(codes)
    assert migrated == ["RU", "HE"], f"Valid codes lost: {migrated}"

    print("PASS: UI migration handles old values, mixed, garbage, and valid codes.")


def test_ui_settings_file_migration():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False,
                                      encoding='utf-8') as f:
        json.dump({"trans_langs": ["Русский", "עברית (Hebrew)", "Klingon"]}, f)
        tmp_path = f.name

    try:
        from ui_manager import UIStateManager
        mgr = UIStateManager(filepath=tmp_path)
        assert mgr.get("trans_langs") == ["RU", "HE"], \
            f"Post-migration: {mgr.get('trans_langs')}"
        with open(tmp_path, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        assert saved["trans_langs"] == ["RU", "HE"], \
            f"File not saved back: {saved['trans_langs']}"
        print("PASS: Settings file auto-migrated and saved back.")
    finally:
        os.unlink(tmp_path)


def test_ai_translator_suffix():
    from ai_translator import lang_code
    from config import TARGET_LANGUAGE_CODE_MAP as MAP

    for key in sorted(set(MAP.keys())):
        suffix = MAP.get(key, lang_code(key).upper())
        assert suffix in ("RU", "EN", "HE"), f"Bad suffix for {key!r}: {suffix!r}"

    for val in ("ru", "RU", "en", "EN", "he", "HE", "RUS", "ENG", "HEB"):
        lc = lang_code(val)
        assert lc in ("ru", "en", "he", "auto"), f"lang_code({val!r}) = {lc!r}"

    print("PASS: ai_translator suffixes are always RU/EN/HE.")


if __name__ == "__main__":
    test_target_languages_are_label_value_pairs()
    test_markers_keyed_by_code()
    test_code_map_resolves_old_values()
    test_code_map_self_mapping()
    test_suffix_never_trans()
    test_ui_migration()
    test_ui_settings_file_migration()
    test_ai_translator_suffix()
    print("\nAll BD10 language code tests passed!")
