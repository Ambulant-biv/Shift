"""Remembers the user's choices between sessions (stored as JSON)."""
from __future__ import annotations

import json
import os

from paths import user_data_dir

DEFAULTS: dict = {
    "language": "auto",          # "auto" or a language code such as "en", "nl", "de"
    "theme": "system",           # "system", "light" or "dark"
    "window_size": "1120x840",
    "last_action": None,         # last chosen format ("pdf") or tool ("tool:split")
    "merge": False,
    "a4": True,
    "quality": 85,
    "dpi": 200,
    "resize": "original",
    "custom_size": 1600,
    "max_filesize": "none",
    "output_mode": "same",       # "same" or "other"
    "output_dir": "",
    "split_mode": "single",
    "split_n": 2,
    "split_ranges": "",
    "rotate": 90,
    "rotate_pages": "",
    "extract_pages": "",
    "extract_remove": False,
    "compress": "strong",
    "cad_scale": 1,
    "auto_update": True,
    "last_update_check": 0.0,
}


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = user_data_dir() / "settings.json"
        self.load()

    def load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for key, default in DEFAULTS.items():
            if key not in data:
                continue
            value = data[key]
            if default is None or isinstance(value, type(default)) or (
                    isinstance(default, float) and isinstance(value, int)):
                self[key] = value

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass
