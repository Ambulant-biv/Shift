"""Automatic updates for Shift via GitHub Releases.

How it works:
1. Shift asks GitHub for the latest release of GITHUB_REPO.
2. If its version is newer, the app shows a banner.
3. "Update now" downloads the update and checks its SHA-256 checksum:
   - installed with ShiftSetup.exe: the new installer runs silently, so Windows
     ("Installed apps", winget) always shows the right version;
   - portable Shift.exe: the new exe is swapped in next to the old one.
   Then Shift restarts.

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
SETUP_NAME = "ShiftSetup.exe"
SETUP_CHECKSUM_NAME = "ShiftSetup.exe.sha256"
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
        "setup": assets.get(SETUP_NAME),
        "setup_sha256": assets.get(SETUP_CHECKSUM_NAME),
        "notes": data.get("body") or "",
    }


def installed_with_setup() -> bool:
    """True when Shift was installed with ShiftSetup.exe (Inno Setup leaves unins000.exe)."""
    return getattr(sys, "frozen", False) and (Path(sys.executable).parent / "unins000.exe").exists()


def _update_files(info: dict) -> tuple[str | None, str | None]:
    if installed_with_setup():
        return info.get("setup"), info.get("setup_sha256")
    return info.get("exe"), info.get("sha256")


def can_self_update(info: dict | None = None) -> bool:
    """True when this is an installed or portable Shift.exe that we may update."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    if not os.access(Path(sys.executable).parent, os.W_OK):
        return False
    if info is None:
        return True
    url, checksum = _update_files(info)
    return bool(url and checksum)


def download(info: dict, progress=None) -> Path:
    """Downloads the installer (or portable exe) and verifies its checksum."""
    url, checksum_url = _update_files(info)
    with _open(checksum_url) as r:
        expected = r.read().decode("ascii", "replace").split()[0].strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("invalid checksum file")

    if installed_with_setup():
        dest = Path(tempfile.gettempdir()) / "ShiftSetup-update.exe"
    else:
        dest = Path(sys.executable).with_name("Shift.update.exe")
    digest = hashlib.sha256()
    with _open(url, timeout=60) as r, open(dest, "wb") as f:
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


def clean_environment() -> dict[str, str]:
    """Environment for starting the new Shift.exe without traces of this one.

    A PyInstaller app passes variables to programs it starts (for example where it
    unpacked itself). The new Shift would then look in our temporary folder, which
    is deleted the moment we close, and fail with "Failed to load Python DLL".
    """
    unpacked = getattr(sys, "_MEIPASS", None)
    env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith("_PYI") or key == "_MEIPASS2":
            continue
        if unpacked and unpacked.lower() in value.lower():
            if key.upper() != "PATH":
                continue  # e.g. TCL_LIBRARY / TK_LIBRARY pointing into our folder
            value = os.pathsep.join(part for part in value.split(os.pathsep)
                                    if unpacked.lower() not in part.lower())
        env[key] = value
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def apply_and_restart(new_file: Path) -> None:
    """Starts a small helper that installs the update once Shift has closed."""
    exe = Path(sys.executable)
    script = Path(tempfile.gettempdir()) / "shift_update.cmd"
    if new_file.name.lower().startswith("shiftsetup"):
        script.write_text(
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "ping -n 4 127.0.0.1 >nul\r\n"
            f'start "" /wait "{new_file}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS /SP-\r\n'
            f'del "{new_file}"\r\n'
            "set PYINSTALLER_RESET_ENVIRONMENT=1\r\n"
            f'start "" "{exe}"\r\n'
            'del "%~f0"\r\n',
            encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(script)], close_fds=True, env=clean_environment(),
                         creationflags=0x08000000 | 0x00000200)
        return
    new_exe = new_file
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
        "set PYINSTALLER_RESET_ENVIRONMENT=1\r\n"
        f'start "" "{exe}"\r\n'
        ":end\r\n"
        'del "%~f0"\r\n',
        encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(script)], close_fds=True, env=clean_environment(),
                     creationflags=0x08000000 | 0x00000200)  # no window, own group
