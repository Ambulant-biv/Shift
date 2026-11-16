"""File locations used by Shift (bundled resources and per-user data)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Shift"


def resource_path(*parts: str) -> Path:
    """Path to a file shipped with the app (works from source and from the .exe)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def user_data_dir() -> Path:
    """Per-user folder for settings and extra language files."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    folder = base / APP_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return folder
