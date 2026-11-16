# PyInstaller build recipe for Shift.  Build with:  python -m PyInstaller shift.spec
from PyInstaller.utils.hooks import collect_all

datas = [("assets", "assets"), ("lang", "lang")]
binaries = []
# PIL.ImageTk is loaded lazily by CustomTkinter; without these the logo and images stay blank
hiddenimports = ["PIL.ImageTk", "PIL._tkinter_finder", "PIL._imagingtk"]
for package in ("customtkinter", "tkinterdnd2", "imageio_ffmpeg", "pillow_heif"):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["shift.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Shift",
    icon="assets/icon.ico",
    console=False,
    upx=False,
)
