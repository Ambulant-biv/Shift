"""Automatic updates for Shift via GitHub Releases.

How it works:
1. Shift asks GitHub for the latest release of GITHUB_REPO.
2. If its version is newer, the app shows a banner.
3. "Update now" downloads Shift.exe, checks it against Shift.exe.sha256,
   swaps it in next to the running program and restarts Shift.

Set GITHUB_REPO below before the first release. While it is empty, Shift
never contacts the internet for updates.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from version import __version__

GITHUB_REPO = "Ambulant-biv/Shift"
ASSET_NAME = "Shift.exe"
CHECKSUM_NAME = "Shift.exe.sha256"
USER_AGENT = f"Shift/{__version__} (+update-check)"
API_URL = "https://api.github.com/repos/{repo}/releases/latest"


def configured() -> bool:
    return bool(GITHUB_REPO.strip())


def parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for piece in v.strip().lstrip("vV").split("-")[0].split("."):
        digits = re.match(r"\d*", piece).group()
        parts.append(int(digits or 0))
    return tuple(parts)


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _open(url: str, timeout: float = 15):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=timeout)


def check_latest() -> dict:
    """Latest release as {'version', 'page', 'exe', 'sha256', 'notes'}."""
    with _open(API_URL.format(repo=GITHUB_REPO)) as r:
        data = json.load(r)
    assets = {a.get("name"): a.get("browser_download_url") for a in data.get("assets", [])}
    return {
        "version": str(data.get("tag_name", "")).lstrip("vV"),
        "page": data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases",
        "exe": assets.get(ASSET_NAME),
        "sha256": assets.get(CHECKSUM_NAME),
        "notes": data.get("body") or "",
    }


def can_self_update(info: dict | None = None) -> bool:
    """True when this is the installed Shift.exe and we may replace it."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    if not os.access(Path(sys.executable).parent, os.W_OK):
        return False
    return info is None or bool(info.get("exe") and info.get("sha256"))


def download(info: dict, progress=None) -> Path:
    """Downloads the new Shift.exe next to the current one and verifies its checksum."""
    with _open(info["sha256"]) as r:
        expected = r.read().decode("ascii", "replace").split()[0].strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("invalid checksum file")

    dest = Path(sys.executable).with_name("Shift.update.exe")
    digest = hashlib.sha256()
    with _open(info["exe"], timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    if digest.hexdigest() != expected:
        dest.unlink(missing_ok=True)
        raise ValueError("checksum mismatch")
    return dest


def apply_and_restart(new_exe: Path) -> None:
    """Starts a small helper that swaps in the new exe once Shift has closed."""
    exe = Path(sys.executable)
    script = Path(tempfile.gettempdir()) / "shift_update.cmd"
    script.write_text(
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "set n=0\r\n"
        ":retry\r\n"
        f'move /y "{new_exe}" "{exe}" >nul 2>nul\r\n'
        "if not errorlevel 1 goto ok\r\n"
        "set /a n+=1\r\n"
        "if %n% geq 60 goto end\r\n"
        "ping -n 2 127.0.0.1 >nul\r\n"
        "goto retry\r\n"
        ":ok\r\n"
        f'start "" "{exe}"\r\n'
        ":end\r\n"
        'del "%~f0"\r\n',
        encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], close_fds=True,
                     creationflags=0x08000000 | 0x00000200)  # no window, own group
