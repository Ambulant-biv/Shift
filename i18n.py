"""Translations for Shift.

Every language is a JSON file in the "lang" folder (en.json, nl.json, de.json, ...).
To add a language, copy en.json, translate the values and save it as <code>.json,
either in the "lang" folder of the source code or in %APPDATA%\\Shift\\lang.
English is the fallback for any missing text.
"""
from __future__ import annotations

import json
import locale
import os
import sys
from pathlib import Path

from paths import resource_path, user_data_dir

_strings: dict = {}
_fallback: dict = {}
current = "en"


def _load_folder(folder: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if folder.is_dir():
        for file in sorted(folder.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    out[file.stem.lower()] = data
            except (OSError, ValueError):
                pass
    return out


def all_languages() -> dict[str, dict]:
    languages = _load_folder(resource_path("lang"))
    for code, data in _load_folder(user_data_dir() / "lang").items():
        languages.setdefault(code, {}).update(data)
    return languages


def language_names() -> dict[str, str]:
    """{code: native name}, e.g. {"nl": "Nederlands"}."""
    return {code: data.get("_language", code) for code, data in sorted(all_languages().items())}


def system_language() -> str:
    candidates: list[str] = []
    if sys.platform == "win32":
        try:
            import ctypes
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            candidates.append(locale.windows_locale.get(lcid, ""))
        except Exception:
            pass
    try:
        candidates.append(locale.getlocale()[0] or "")
    except Exception:
        pass
    candidates += [os.environ.get("LC_ALL", ""), os.environ.get("LANG", "")]
    for name in candidates:
        code = name.replace("-", "_").split("_")[0].split(".")[0].lower()
        if len(code) == 2:
            return code
    return "en"


def setup(choice: str = "auto") -> str:
    """Activate a language ("auto" follows Windows). Returns the code in use."""
    global _strings, _fallback, current
    languages = all_languages()
    _fallback = languages.get("en", {})
    code = system_language() if choice == "auto" else choice
    if code not in languages:
        code = "en"
    current = code
    _strings = languages.get(code, {})
    return code


def t(key: str, **values) -> str:
    text = _strings.get(key) or _fallback.get(key) or key
    try:
        return text.format(**values) if values else text
    except (KeyError, IndexError, ValueError):
        return text


def tn(key: str, n: int, **values) -> str:
    """Plural-aware text: uses <key>.one or <key>.other."""
    return t(f"{key}.{'one' if n == 1 else 'other'}", n=n, **values)
