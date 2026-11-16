# Shift — convert any file

Shift is a Windows desktop app that converts files locally, without uploading
anything: images, PDF, Word, Excel, PowerPoint, video and audio.

## Features

- **Convert** between dozens of formats (JPG → PDF, Word → PDF, PDF → Word, video → MP3, …)
- **Merge** several files into one PDF, in the order you choose (↑ ↓ or *Sort A–Z*)
- **Resize and compress images**: preset sizes, custom size, quality, or a maximum file size
- **PDF tools**: split, rotate, select or remove pages, compress
- **PDF → DXF / DWG** for drawings exported from CAD programs, with a choice of scale
  (DWG uses the free [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter), which users install themselves)
- **Languages**: English, Nederlands, Deutsch — follows the Windows language automatically
- **Light and dark theme**, or follow Windows
- **Remembers your choices** between sessions
- **Automatic updates** via GitHub Releases

## Project layout

| File | Purpose |
|---|---|
| `shift.py` | Main window (start here) |
| `engine.py` | All conversions and PDF tools, no UI code |
| `i18n.py` + `lang/*.json` | Translations |
| `settings.py` | Remembered choices (`%APPDATA%\Shift\settings.json`) |
| `updater.py` | Update check, download and install |
| `version.py` | Version number |
| `shift.spec` | PyInstaller build recipe |
| `.github/workflows/release.yml` | Builds and publishes a release automatically |

## Run from source

```
pip install -r requirements.txt
python shift.py
```

## Build and install on your own PC

Double-click `build_and_install.bat`. It builds `dist\Shift.exe`, installs it to
`%LOCALAPPDATA%\Programs\Shift` and adds shortcuts (desktop, Start menu, Send to).

## Publishing releases with automatic updates

One-time setup:

1. Create a GitHub repository (it can be public or private, but the **releases** must be
   reachable without logging in, so use a public repository for distribution).
2. In `updater.py`, set `GITHUB_REPO = "your-name/your-repo"`.
3. Push the code to GitHub.

For every new version:

1. Change `__version__` in `version.py`, e.g. to `1.2.0`.
2. Commit, then tag and push:
   ```
   git tag v1.2.0
   git push && git push --tags
   ```
3. GitHub Actions builds `Shift.exe`, creates `Shift.exe.sha256` and publishes the release.

Running copies of Shift check once a day. Users see a banner, click **Update now**,
and Shift downloads the new version, verifies its SHA-256 checksum, replaces itself
and restarts. No admin rights are needed.

## Adding a language

Copy `lang/en.json` to `lang/<code>.json` (for example `fr.json`), translate the values
and keep the `{placeholders}` intact. Users can also drop extra language files into
`%APPDATA%\Shift\lang`. Missing texts fall back to English.

## Before distributing widely

- **Code signing.** Unsigned programs trigger a Windows SmartScreen warning
  ("Windows protected your PC"). A code-signing certificate removes this.
- **Name check.** Make sure the name "Shift" is free to use for your purpose.
- **Licences.** Shift bundles FFmpeg (GPL/LGPL) and PyMuPDF (AGPL). For free or
  open-source distribution that is fine; for a closed-source or paid product, check the
  licence terms or buy a commercial PyMuPDF licence.
