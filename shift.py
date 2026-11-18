"""Shift - convert any file.

Main window. Run with:  python shift.py [files...]
"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

import engine
import i18n
import updater
from engine import CATEGORIES, PDF_TOOLS, Office, Options, ShiftError, category, targets_for
from i18n import t, tn
from paths import resource_path
from settings import Settings
from version import __version__

try:  # drag and drop
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND = True
except Exception:
    DND = False


# --------------------------------------------------------------------------
# Look and feel: (light, dark) colour pairs, so the theme can switch live
# --------------------------------------------------------------------------
BG = ("#F3F4F8", "#0E1016")
PANEL = ("#FFFFFF", "#151822")
CARD = ("#FFFFFF", "#1C2030")
INPUT = ("#EEF0F6", "#1C2030")
HOVER = ("#E4E7F0", "#252A3E")
BORDER = ("#DCDFE9", "#2C3248")
TEXT = ("#151826", "#ECEEF5")
MUTED = ("#5C6278", "#9097AE")
MUTED2 = ("#8B90A5", "#636A84")
ACCENT = ("#6A4BF5", "#7C5CFF")
ACCENT_HOVER = ("#5B3BE8", "#937AFF")
ACCENT_SOFT = ("#ECE8FF", "#251E45")
ON_ACCENT = ("#FFFFFF", "#FFFFFF")
GREEN = ("#147A3D", "#3FD08A")
GREEN_SOFT = ("#DDF4E6", "#12301F")
RED = ("#C8283F", "#FF5C70")
RED_SOFT = ("#FCE3E7", "#3D1A24")
KNOB = ("#FFFFFF", "#ECEEF5")

CATEGORY_COLOR = {
    "image": "#E0A526",
    "pdf": "#E5484D",
    "document": "#3E7FEA",
    "spreadsheet": "#2F9E55",
    "presentation": "#E5762E",
    "video": "#D0508F",
    "audio": "#18A999",
}

FONT = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"

RESIZE = {"original": None, "large": 2560, "medium": 1920, "small": 1280, "tiny": 640, "custom": None}
FILESIZE = {"none": None, "200kb": 200 * 1024, "500kb": 500 * 1024, "1mb": 1024 ** 2,
            "2mb": 2 * 1024 ** 2, "5mb": 5 * 1024 ** 2}
ROTATIONS = {"right": 90, "half": 180, "left": 270}
CAD_SCALES = [1, 20, 50, 100, 200, 500, 1000]


def F(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def human_size(n: float) -> str:
    sep = t("_decimal")
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}".replace(".", sep)
        n /= 1024
    return ""


def shorten(name: str, limit: int = 44) -> str:
    return name if len(name) <= limit else name[: limit - 16] + "…" + name[-15:]


def color_titlebar(window, mode: str | None = None) -> None:
    """Gives the Windows title bar the light or dark colour of the theme.

    CustomTkinter normally does this by hiding and re-showing every window, which
    can leave a dialog invisible while it still blocks the app. We switch that
    off (see main) and only repaint the frame instead.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if (mode or ctk.get_appearance_mode()).lower() == "dark" else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new, then old Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        # repaint the frame: NOSIZE | NOMOVE | NOZORDER | NOACTIVATE | FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    except Exception:
        pass


BASES = (ctk.CTk, TkinterDnD.DnDWrapper) if DND else (ctk.CTk,)


class Shift(*BASES):
    def __init__(self, settings: Settings, start: list[str]):
        super().__init__()
        self.dnd = False
        if DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd = True
            except Exception:
                pass

        self.settings = settings
        self.items: dict[str, dict] = {}
        self.order: list[str] = []
        self.errors: dict[str, str] = {}
        self.counter = 0
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.total = 1
        self.last_dir: Path | None = None
        self.formats: list[str] = []
        self.tools: list[str] = []
        self.action: str | None = None
        self.update_info: dict | None = None
        self.updating = False
        self.settings_window: SettingsWindow | None = None
        self.pending_language: str | None = None

        self.title("Shift")
        self.geometry(settings["window_size"])
        self.minsize(980, 700)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._quit)
        if sys.platform == "win32":
            self.after(300, self._set_icon)
            self.after(50, lambda: color_titlebar(self))

        self._build()
        self._refresh()
        self.after(100, self._poll)
        if start:
            self.after(300, lambda: self._add(start))
        if (settings["auto_update"] and updater.configured()
                and time.time() - settings["last_update_check"] > 20 * 3600):
            self.after(3000, lambda: self._check_updates(manual=False))

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        self.after(20, lambda: color_titlebar(self, mode_string))

    def _set_icon(self, window=None):
        try:
            (window or self).iconbitmap(str(resource_path("assets", "icon.ico")))
        except Exception:
            pass

    # ================================================================ layout
    def _build(self):
        for child in self.winfo_children():
            child.destroy()
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._build_banner()
        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.grid(row=2, column=0, sticky="nsew", padx=28, pady=(10, 24))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self._build_left(body)
        self._build_right(body)
        self._build_chips()
        if self.dnd:
            for widget in (self, self.zone, self.list, getattr(self.list, "_parent_canvas", None)):
                if widget is not None:
                    self._drop_target(widget)

    def _build_header(self):
        head = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        head.grid(row=0, column=0, sticky="ew", padx=28, pady=(20, 4))
        try:
            img = Image.open(resource_path("assets", "logo.png"))
            self.logo = ctk.CTkImage(light_image=img, dark_image=img, size=(36, 36))
            ctk.CTkLabel(head, image=self.logo, text="").pack(side="left", padx=(0, 12))
        except Exception:
            pass
        name = ctk.CTkFrame(head, fg_color="transparent")
        name.pack(side="left")
        ctk.CTkLabel(name, text="Shift", font=F(20, "bold"), text_color=TEXT,
                     height=22, anchor="w").pack(anchor="w")
        ctk.CTkLabel(name, text=t("app.tagline"), font=F(12), text_color=MUTED,
                     height=16, anchor="w").pack(anchor="w")
        ctk.CTkButton(head, text="⚙", width=38, height=38, corner_radius=10, font=F(18),
                      fg_color="transparent", hover_color=HOVER, text_color=MUTED,
                      command=self._open_settings).pack(side="right")
        ctk.CTkLabel(head, text="●  " + t("header.local"), font=F(12),
                     text_color=MUTED).pack(side="right", padx=(0, 14))

    def _build_banner(self):
        self.banner = ctk.CTkFrame(self, fg_color=ACCENT_SOFT, corner_radius=12)
        self.banner_text = ctk.CTkLabel(self.banner, text="", font=F(13, "bold"), text_color=TEXT)
        self.banner_text.pack(side="left", padx=16, pady=10)
        ctk.CTkButton(self.banner, text=t("update.later"), width=70, height=32, corner_radius=8,
                      fg_color="transparent", hover_color=HOVER, text_color=MUTED, font=F(12),
                      command=self._hide_banner).pack(side="right", padx=(0, 10))
        self.banner_button = ctk.CTkButton(
            self.banner, text=t("update.now"), width=110, height=32, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT, font=F(12, "bold"),
            command=self._install_update)
        self.banner_button.pack(side="right", padx=6)
        ctk.CTkButton(self.banner, text=t("update.notes"), width=70, height=32, corner_radius=8,
                      fg_color="transparent", hover_color=HOVER, text_color=ACCENT, font=F(12),
                      command=lambda: self.update_info and webbrowser.open(self.update_info["page"])
                      ).pack(side="right")
        if self.update_info:
            self._show_banner()

    def _build_left(self, body):
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 20))
        left.grid_columnconfigure(0, weight=1)
        self.left = left

        self.zone = ctk.CTkFrame(left, fg_color=CARD, corner_radius=18, border_width=2,
                                 border_color=BORDER, height=118)
        inner = ctk.CTkFrame(self.zone, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        self.zone_icon = ctk.CTkLabel(inner, text="↓", width=54, height=54, corner_radius=27,
                                      fg_color=ACCENT_SOFT, text_color=ACCENT, font=F(24, "bold"))
        self.zone_icon.pack(pady=(0, 12))
        self.zone_title = ctk.CTkLabel(inner, text=t("drop.title" if self.dnd else "drop.title_click"),
                                       font=F(18, "bold"), text_color=TEXT)
        self.zone_title.pack()
        ctk.CTkLabel(inner, text=t("drop.subtitle" if self.dnd else "drop.subtitle_click"),
                     font=F(13), text_color=MUTED).pack(pady=(2, 0))
        self.zone_types = ctk.CTkLabel(inner, text=t("drop.types"), font=F(12), text_color=MUTED2)
        widgets = [self.zone, inner, self.zone_icon, self.zone_title, self.zone_types]
        widgets += inner.winfo_children()
        for w in set(widgets):
            w.bind("<Button-1>", lambda e: self._choose_files())
            w.bind("<Enter>", lambda e: self._zone_hover(True))
            w.bind("<Leave>", lambda e: self._zone_hover(False))
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

        self.list_head = ctk.CTkFrame(left, fg_color="transparent")
        self.count_label = ctk.CTkLabel(self.list_head, text="", font=F(15, "bold"), text_color=TEXT)
        self.count_label.pack(side="left")
        for text, command in ((t("list.clear"), self._clear), (t("list.sort"), self._sort),
                              (t("list.add_folder"), self._choose_folder),
                              ("+  " + t("list.add_files"), self._choose_files)):
            ctk.CTkButton(self.list_head, text=text, command=command, fg_color="transparent",
                          hover_color=HOVER, text_color=MUTED, width=40, height=30,
                          corner_radius=8, font=F(12)).pack(side="right", padx=(4, 0))
        self.list = ctk.CTkScrollableFrame(left, fg_color="transparent", corner_radius=0,
                                           scrollbar_button_color=BORDER,
                                           scrollbar_button_hover_color=MUTED2)

    def _section(self, parent, key, top=0):
        label = ctk.CTkLabel(parent, text=t(key).upper(), font=F(11, "bold"), text_color=MUTED,
                             anchor="w")
        label.pack(fill="x", pady=(top, 0))
        return label

    def _menu(self, parent, values, command=None):
        return ctk.CTkOptionMenu(parent, values=values, height=34, corner_radius=8,
                                 fg_color=INPUT, button_color=INPUT, button_hover_color=HOVER,
                                 text_color=TEXT, dropdown_fg_color=PANEL,
                                 dropdown_hover_color=HOVER, dropdown_text_color=TEXT,
                                 font=F(12), dropdown_font=F(12), command=command,
                                 dynamic_resizing=False)

    def _segments(self, parent, values, command=None):
        return ctk.CTkSegmentedButton(parent, values=values, height=32, command=command,
                                      selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                                      unselected_color=INPUT, unselected_hover_color=HOVER,
                                      fg_color=INPUT, text_color=TEXT, font=F(12))

    def _entry(self, parent, placeholder):
        return ctk.CTkEntry(parent, placeholder_text=placeholder, height=34, corner_radius=8,
                            fg_color=INPUT, border_color=BORDER, text_color=TEXT,
                            placeholder_text_color=MUTED2, font=F(12))

    def _switch(self, parent, key, command=None):
        return ctk.CTkSwitch(parent, text=t(key), command=command, progress_color=ACCENT,
                             fg_color=BORDER, button_color=KNOB, button_hover_color=KNOB,
                             text_color=TEXT, font=F(13))

    def _label(self, parent, key, muted=False, size=13):
        return ctk.CTkLabel(parent, text=t(key), font=F(size), anchor="w", justify="left",
                            text_color=MUTED2 if muted else TEXT, wraplength=280)

    def _build_right(self, body):
        s = self.settings
        right = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=18, width=370)
        right.grid(row=0, column=1, sticky="ns")
        right.grid_propagate(False)
        right.pack_propagate(False)

        # bottom part first, so it always stays visible
        bottom = ctk.CTkFrame(right, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=24, pady=(8, 22))
        self.progress = ctk.CTkProgressBar(bottom, progress_color=INPUT, fg_color=INPUT,
                                           height=6, corner_radius=3)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(0, 8))
        self.status = ctk.CTkLabel(bottom, text="", font=F(12), text_color=MUTED,
                                   wraplength=300, justify="left", anchor="w")
        self.status.pack(fill="x", pady=(0, 8))
        self.open_button = ctk.CTkButton(bottom, text=t("btn.open_folder"), height=38,
                                         corner_radius=10, fg_color=INPUT, hover_color=HOVER,
                                         text_color=TEXT, text_color_disabled=MUTED2, font=F(12),
                                         command=self._open_folder)
        self.open_button.pack(fill="x", pady=(0, 10))
        self.start_button = ctk.CTkButton(bottom, text="", height=52, corner_radius=12,
                                          fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                          text_color=ON_ACCENT, text_color_disabled=MUTED2,
                                          font=F(15, "bold"), command=self._start)
        self.start_button.pack(fill="x")

        scroll = ctk.CTkScrollableFrame(right, fg_color="transparent", corner_radius=0,
                                        scrollbar_button_color=BORDER,
                                        scrollbar_button_hover_color=MUTED2)
        scroll.pack(fill="both", expand=True, padx=(14, 4), pady=(16, 0))
        p = ctk.CTkFrame(scroll, fg_color="transparent")
        p.pack(fill="x", padx=(10, 6))
        self.controls: list = []

        # --- convert to
        self._section(p, "section.convert_to", top=6)
        self.chips = ctk.CTkFrame(p, fg_color="transparent", height=1)
        self.chips.pack(fill="x", pady=(10, 0))
        for c in range(3):
            self.chips.grid_columnconfigure(c, weight=1, uniform="chip")
        self.action_info = ctk.CTkLabel(p, text="", font=F(12), text_color=MUTED, anchor="w",
                                        wraplength=290, justify="left")
        self.action_info.pack(fill="x", pady=(6, 0))

        # --- PDF tools (only when every file is a PDF)
        self.tools_box = ctk.CTkFrame(p, fg_color="transparent", height=1)
        self._section(self.tools_box, "section.pdf_tools", top=20)
        self.tool_chips = ctk.CTkFrame(self.tools_box, fg_color="transparent", height=1)
        self.tool_chips.pack(fill="x", pady=(10, 0))
        for c in range(2):
            self.tool_chips.grid_columnconfigure(c, weight=1, uniform="tool")

        # --- options
        self.options_title = self._section(p, "section.options", top=22)
        self.options = ctk.CTkFrame(p, fg_color="transparent", height=1)
        self.options.pack(fill="x", pady=(8, 0))
        o = self.options

        self.sw_merge = self._switch(o, "opt.merge", command=self._refresh_options)
        if s["merge"]:
            self.sw_merge.select()
        self.sw_a4 = self._switch(o, "opt.a4")
        if s["a4"]:
            self.sw_a4.select()

        # resize
        self.box_resize = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_resize, "opt.size").pack(fill="x")
        self.resize_labels = {code: t(f"size.{code}") for code in RESIZE}
        self.menu_resize = self._menu(self.box_resize, list(self.resize_labels.values()),
                                      command=lambda v: self._toggle_custom())
        self.menu_resize.set(self.resize_labels.get(s["resize"], self.resize_labels["original"]))
        self.menu_resize.pack(fill="x", pady=(6, 0))
        self.entry_size = self._entry(self.box_resize, t("opt.size_placeholder"))
        self.entry_size.insert(0, str(s["custom_size"]))

        # quality
        self.box_quality = ctk.CTkFrame(o, fg_color="transparent", height=1)
        row = ctk.CTkFrame(self.box_quality, fg_color="transparent", height=1)
        row.pack(fill="x")
        self._label(row, "opt.quality").pack(side="left")
        self.quality_value = ctk.CTkLabel(row, text=str(s["quality"]), font=F(13, "bold"),
                                          text_color=ACCENT)
        self.quality_value.pack(side="right")
        self.slider_quality = ctk.CTkSlider(
            self.box_quality, from_=40, to=100, number_of_steps=60, progress_color=ACCENT,
            button_color=ACCENT, button_hover_color=ACCENT_HOVER, fg_color=BORDER,
            command=lambda v: self.quality_value.configure(text=str(int(v))))
        self.slider_quality.set(s["quality"])
        self.slider_quality.pack(fill="x", pady=(4, 0))

        # max file size
        self.box_filesize = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_filesize, "opt.max_filesize").pack(fill="x")
        self.filesize_labels = {code: t(f"filesize.{code}") for code in FILESIZE}
        self.menu_filesize = self._menu(self.box_filesize, list(self.filesize_labels.values()))
        self.menu_filesize.set(self.filesize_labels.get(s["max_filesize"], self.filesize_labels["none"]))
        self.menu_filesize.pack(fill="x", pady=(6, 0))

        # dpi
        self.box_dpi = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_dpi, "opt.dpi").pack(fill="x")
        self.seg_dpi = self._segments(self.box_dpi, ["150 dpi", "200 dpi", "300 dpi"])
        self.seg_dpi.set(f"{s['dpi']} dpi" if s["dpi"] in (150, 200, 300) else "200 dpi")
        self.seg_dpi.pack(fill="x", pady=(6, 0))

        # split
        self.box_split = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_split, "split.label").pack(fill="x")
        self.split_labels = {code: t(f"split.{code}") for code in ("single", "every", "ranges")}
        self.seg_split = self._segments(self.box_split, list(self.split_labels.values()),
                                        command=lambda v: self._toggle_split())
        self.seg_split.set(self.split_labels.get(s["split_mode"], self.split_labels["single"]))
        self.seg_split.pack(fill="x", pady=(6, 0))
        self.split_extra = ctk.CTkFrame(self.box_split, fg_color="transparent", height=1)
        self.split_extra.pack(fill="x")
        self.entry_split_n = self._entry(self.split_extra, t("split.every_placeholder"))
        self.entry_split_n.insert(0, str(s["split_n"]))
        self.entry_split_ranges = self._entry(self.split_extra, t("pages.placeholder"))
        if s["split_ranges"]:
            self.entry_split_ranges.insert(0, s["split_ranges"])
        self.split_hint = self._label(self.split_extra, "split.ranges_hint", muted=True, size=11)

        # rotate
        self.box_rotate = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_rotate, "rotate.label").pack(fill="x")
        self.rotate_labels = {code: t(f"rotate.{code}") for code in ROTATIONS}
        self.seg_rotate = self._segments(self.box_rotate, list(self.rotate_labels.values()))
        current = next((c for c, deg in ROTATIONS.items() if deg == s["rotate"]), "right")
        self.seg_rotate.set(self.rotate_labels[current])
        self.seg_rotate.pack(fill="x", pady=(6, 10))
        self._label(self.box_rotate, "pages.label").pack(fill="x")
        self.entry_rotate = self._entry(self.box_rotate, t("pages.all_placeholder"))
        if s["rotate_pages"]:
            self.entry_rotate.insert(0, s["rotate_pages"])
        self.entry_rotate.pack(fill="x", pady=(6, 0))
        self._label(self.box_rotate, "pages.hint", muted=True, size=11).pack(fill="x", pady=(4, 0))

        # extract
        self.box_extract = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_extract, "pages.label").pack(fill="x")
        self.entry_extract = self._entry(self.box_extract, t("pages.placeholder"))
        if s["extract_pages"]:
            self.entry_extract.insert(0, s["extract_pages"])
        self.entry_extract.pack(fill="x", pady=(6, 0))
        self._label(self.box_extract, "pages.hint", muted=True, size=11).pack(fill="x", pady=(4, 8))
        self.sw_remove = self._switch(self.box_extract, "extract.remove",
                                      command=self._refresh_options)
        if s["extract_remove"]:
            self.sw_remove.select()
        self.sw_remove.pack(fill="x")

        # compress
        self.box_compress = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_compress, "compress.label").pack(fill="x")
        self.compress_labels = {code: t(f"compress.{code}") for code in ("light", "strong")}
        self.seg_compress = self._segments(self.box_compress, list(self.compress_labels.values()),
                                           command=lambda v: self._compress_hint())
        self.seg_compress.set(self.compress_labels.get(s["compress"], self.compress_labels["strong"]))
        self.seg_compress.pack(fill="x", pady=(6, 0))
        self.compress_hint = self._label(self.box_compress, "compress.strong_hint", muted=True, size=11)
        self.compress_hint.pack(fill="x", pady=(4, 0))
        self._compress_hint()

        # PDF to DXF/DWG
        self.box_cad = ctk.CTkFrame(o, fg_color="transparent", height=1)
        self._label(self.box_cad, "opt.cad_scale").pack(fill="x")
        self.cad_labels = {n: (t("cad.scale_paper") if n == 1 else f"1:{n}") for n in CAD_SCALES}
        self.menu_cad = self._menu(self.box_cad, list(self.cad_labels.values()))
        self.menu_cad.set(self.cad_labels.get(s["cad_scale"], self.cad_labels[1]))
        self.menu_cad.pack(fill="x", pady=(6, 0))
        self._label(self.box_cad, "cad.hint", muted=True, size=11).pack(fill="x", pady=(4, 0))

        self.no_options = self._label(o, "opt.none", muted=True, size=12)

        # --- save to
        self._section(p, "section.save_to", top=22)
        self.output_labels = {"same": t("output.same"), "other": t("output.other")}
        self.seg_output = self._segments(p, list(self.output_labels.values()),
                                         command=self._output_chosen)
        self.seg_output.set(self.output_labels[s["output_mode"] if s["output_mode"] in
                                               self.output_labels else "same"])
        self.seg_output.pack(fill="x", pady=(8, 0))
        self.output_label = ctk.CTkLabel(p, text="", font=F(11), text_color=MUTED, anchor="w",
                                         wraplength=290, justify="left", cursor="hand2")
        self.output_label.pack(fill="x", pady=(4, 10))
        self.output_label.bind("<Button-1>", lambda e: self._choose_output())

        self.controls += [self.sw_merge, self.sw_a4, self.menu_resize, self.entry_size,
                          self.slider_quality, self.menu_filesize, self.seg_dpi, self.seg_split,
                          self.entry_split_n, self.entry_split_ranges, self.seg_rotate,
                          self.entry_rotate, self.entry_extract, self.sw_remove,
                          self.seg_compress, self.seg_output, self.menu_cad]
        self._toggle_custom()
        self._toggle_split()

    # ============================================================== helpers
    def _drop_target(self, widget):
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            widget.dnd_bind("<<DropEnter>>", lambda e: (self._zone_hover(True), e.action)[1])
            widget.dnd_bind("<<DropLeave>>", lambda e: (self._zone_hover(False), e.action)[1])
        except Exception:
            pass

    def _zone_hover(self, on: bool):
        on = on and not self.busy
        self.zone.configure(border_color=ACCENT if on else BORDER, fg_color=HOVER if on else CARD)

    def _layout_left(self):
        if self.order:
            self.zone.grid(row=0, column=0, sticky="ew")
            self.zone.configure(height=118)
            self.left.grid_rowconfigure(0, weight=0)
            self.left.grid_rowconfigure(2, weight=1)
            self.zone_types.pack_forget()
            self.zone_icon.configure(width=40, height=40, corner_radius=20, font=F(18, "bold"))
            self.zone_icon.pack_configure(pady=(0, 6))
            self.zone_title.configure(font=F(15, "bold"))
            self.list_head.grid(row=1, column=0, sticky="ew", pady=(20, 8))
            self.list.grid(row=2, column=0, sticky="nsew")
        else:
            self.zone.grid(row=0, column=0, sticky="nsew")
            self.left.grid_rowconfigure(0, weight=1)
            self.left.grid_rowconfigure(2, weight=0)
            self.zone_icon.configure(width=54, height=54, corner_radius=27, font=F(24, "bold"))
            self.zone_icon.pack_configure(pady=(0, 12))
            self.zone_title.configure(font=F(18, "bold"))
            self.zone_types.pack(pady=(18, 0))
            self.list_head.grid_remove()
            self.list.grid_remove()

    def _toggle_custom(self):
        if self._code(self.resize_labels, self.menu_resize.get()) == "custom":
            self.entry_size.pack(fill="x", pady=(6, 0))
        else:
            self.entry_size.pack_forget()

    def _toggle_split(self):
        mode = self._code(self.split_labels, self.seg_split.get())
        for w in (self.entry_split_n, self.entry_split_ranges, self.split_hint):
            w.pack_forget()
        if mode == "every":
            self.entry_split_n.pack(fill="x", pady=(8, 0))
        elif mode == "ranges":
            self.entry_split_ranges.pack(fill="x", pady=(8, 0))
            self.split_hint.pack(fill="x", pady=(4, 0))

    def _compress_hint(self):
        code = self._code(self.compress_labels, self.seg_compress.get()) or "strong"
        self.compress_hint.configure(text=t(f"compress.{code}_hint"))

    @staticmethod
    def _code(mapping: dict, label: str):
        return next((code for code, text in mapping.items() if text == label), None)

    # ================================================================ files
    def _choose_files(self):
        if self.busy:
            return
        every = sorted({e for inputs, _ in CATEGORIES.values() for e in inputs})
        types = [(t("dialog.all_supported"), " ".join(f"*.{e}" for e in every))]
        for cat, (inputs, _) in CATEGORIES.items():
            types.append((t(f"cat.{cat}"), " ".join(f"*.{e}" for e in sorted(inputs))))
        types.append((t("dialog.all_files"), "*.*"))
        paths = filedialog.askopenfilenames(title=t("dialog.choose_files"), filetypes=types)
        if paths:
            self._add(list(paths))

    def _choose_folder(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(title=t("dialog.choose_folder"))
        if folder:
            self._add([folder])

    def _on_drop(self, event):
        self._zone_hover(False)
        self._add(list(self.tk.splitlist(event.data)))
        return event.action

    def _add(self, paths: list[str]):
        if self.busy:
            return
        known = {str(self.items[k]["path"].resolve()).lower() for k in self.order}
        skipped: list[str] = []
        files: list[Path] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                files += sorted((c for c in path.iterdir() if c.is_file()),
                                key=lambda c: c.name.lower())
            elif path.is_file():
                files.append(path)
        for path in files:
            if category(path) is None:
                skipped.append(path.name)
                continue
            key = str(path.resolve()).lower()
            if key in known:
                continue
            known.add(key)
            self._make_card(path)
        self._update_arrows()
        self._refresh()
        if skipped:
            names = "\n".join(skipped[:12]) + ("\n…" if len(skipped) > 12 else "")
            messagebox.showinfo(t("msg.unsupported_title"), t("msg.unsupported", files=names))

    def _make_card(self, path: Path):
        self.counter += 1
        key = str(self.counter)
        cat = category(path)
        card = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=12, border_width=1,
                            border_color=BORDER)
        card.pack(fill="x", pady=4, padx=(0, 8))
        card.grid_columnconfigure(1, weight=1)
        badge = path.suffix.lstrip(".").upper()[:4]
        ctk.CTkLabel(card, text=badge, width=48, height=38,
                     corner_radius=9, fg_color=CATEGORY_COLOR[cat], text_color="#FFFFFF",
                     font=F(11 if len(badge) <= 3 else 9, "bold")).grid(
            row=0, column=0, rowspan=2, padx=12, pady=11)
        ctk.CTkLabel(card, text=shorten(path.name), font=F(13, "bold"), text_color=TEXT,
                     anchor="w").grid(row=0, column=1, sticky="sw", pady=(9, 0))
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = ""
        ctk.CTkLabel(card, text=f"{t(f'cat.{cat}')}  ·  {size}", font=F(11), text_color=MUTED,
                     anchor="w").grid(row=1, column=1, sticky="nw", pady=(0, 9))
        status = ctk.CTkLabel(card, text="", font=F(11, "bold"), corner_radius=11, height=24,
                              fg_color="transparent", text_color=MUTED)
        status.grid(row=0, column=2, rowspan=2, padx=8)
        status.bind("<Button-1>", lambda e: self._show_error(key))

        def small(text, command):
            return ctk.CTkButton(card, text=text, width=28, height=28, corner_radius=8,
                                 fg_color="transparent", hover_color=HOVER, text_color=MUTED,
                                 text_color_disabled=BORDER, font=F(13), command=command)
        up = small("↑", lambda: self._move(key, -1))
        down = small("↓", lambda: self._move(key, 1))
        remove = small("✕", lambda: self._remove(key))
        up.grid(row=0, column=3, rowspan=2)
        down.grid(row=0, column=4, rowspan=2)
        remove.grid(row=0, column=5, rowspan=2, padx=(4, 10))
        if self.dnd:
            self._drop_target(card)
        self.items[key] = {"path": path, "card": card, "status": status,
                           "up": up, "down": down, "remove": remove}
        self.order.append(key)

    def _repack(self):
        for key in self.order:
            self.items[key]["card"].pack_forget()
        for key in self.order:
            self.items[key]["card"].pack(fill="x", pady=4, padx=(0, 8))
        self._update_arrows()

    def _update_arrows(self):
        last = len(self.order) - 1
        for i, key in enumerate(self.order):
            item = self.items[key]
            free = not self.busy
            item["up"].configure(state="normal" if free and i > 0 else "disabled")
            item["down"].configure(state="normal" if free and i < last else "disabled")
            item["remove"].configure(state="normal" if free else "disabled")

    def _move(self, key: str, step: int):
        if self.busy:
            return
        i = self.order.index(key)
        j = i + step
        if 0 <= j < len(self.order):
            self.order[i], self.order[j] = self.order[j], self.order[i]
            self._repack()

    def _sort(self):
        if self.busy:
            return
        self.order.sort(key=lambda k: self.items[k]["path"].name.lower())
        self._repack()

    def _remove(self, key: str):
        if self.busy:
            return
        item = self.items.pop(key, None)
        if item:
            item["card"].destroy()
            self.order.remove(key)
        self.errors.pop(key, None)
        self._update_arrows()
        self._refresh()

    def _clear(self):
        if self.busy:
            return
        for key in self.order:
            self.items[key]["card"].destroy()
        self.items.clear()
        self.order.clear()
        self.errors.clear()
        self.status.configure(text="")
        self.progress.set(0)
        self.progress.configure(progress_color=INPUT)
        self._refresh()

    def _set_status(self, key: str, kind: str | None, text: str = ""):
        item = self.items.get(key)
        if not item:
            return
        colors = {
            None: ("transparent", MUTED),
            "waiting": ("transparent", MUTED2),
            "working": (ACCENT_SOFT, ACCENT),
            "ok": (GREEN_SOFT, GREEN),
            "error": (RED_SOFT, RED),
        }
        back, front = colors[kind]
        item["status"].configure(text=f"  {text}  " if text else "", fg_color=back,
                                 text_color=front, cursor="hand2" if kind == "error" else "")

    def _show_error(self, key: str):
        if key in self.errors:
            messagebox.showwarning(t("msg.failed_title"),
                                   f"{self.items[key]['path'].name}\n\n{self.errors[key]}")

    # ============================================================== choices
    def _paths(self) -> list[Path]:
        return [self.items[k]["path"] for k in self.order]

    def _refresh(self):
        self._layout_left()
        paths = self._paths()
        self.count_label.configure(text=tn("list.count", len(paths)))

        sets = [targets_for(p) for p in paths]
        formats = [d for d in sets[0] if all(d in s for s in sets[1:])] if sets else []
        tools = list(PDF_TOOLS) if paths and all(category(p) == "pdf" for p in paths) else []
        if (formats, tools) != (self.formats, self.tools):
            self.formats, self.tools = formats, tools
            self._build_chips()
        valid = formats + [f"tool:{x}" for x in tools]
        if self.action not in valid:
            preferred = self.settings["last_action"]
            self.action = preferred if preferred in valid else (valid[0] if valid else None)
            self._color_chips()

        self._update_info()
        if self.seg_output.get() == self.output_labels["other"] and self.settings["output_dir"]:
            self.output_label.configure(text=f"{self.settings['output_dir']}   ·   {t('output.change')}")
        else:
            self.output_label.configure(text="")
        self._refresh_options()

    def _update_info(self):
        a = self.action
        if a and a.startswith("tool:"):
            text = t(f"tool.{a[5:]}.desc")
        elif a:
            text = t(f"fmt.{a}")
        elif self.order:
            text = t("convert.no_common")
        else:
            text = ""
        self.action_info.configure(text=text)

    def _build_chips(self):
        for frame in (self.chips, self.tool_chips):
            for w in frame.winfo_children():
                w.destroy()
        self.chip_buttons: dict[str, ctk.CTkButton] = {}
        if not self.formats and not self.order:
            self._label(self.chips, "convert.add_first", muted=True).grid(
                row=0, column=0, columnspan=3, sticky="w")

        def chip(parent, action, text, i, cols):
            b = ctk.CTkButton(parent, text=text, height=38, corner_radius=10, border_width=1,
                              font=F(12, "bold"), width=60,
                              command=lambda: self._choose_action(action))
            b.grid(row=i // cols, column=i % cols, sticky="ew", pady=4,
                   padx=(0 if i % cols == 0 else 4, 0 if i % cols == cols - 1 else 4))
            self.chip_buttons[action] = b

        for i, code in enumerate(self.formats):
            chip(self.chips, code, code.upper(), i, 3)
        for i, tool in enumerate(self.tools):
            chip(self.tool_chips, f"tool:{tool}", t(f"tool.{tool}"), i, 2)
        if self.tools:
            self.tools_box.pack(fill="x", after=self.action_info)
        else:
            self.tools_box.pack_forget()
        self._color_chips()

    def _color_chips(self):
        for action, b in getattr(self, "chip_buttons", {}).items():
            if action == self.action:
                b.configure(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT,
                            border_color=ACCENT)
            else:
                b.configure(fg_color=INPUT, hover_color=HOVER, text_color=TEXT, border_color=BORDER)

    def _choose_action(self, action: str):
        if self.busy:
            return
        self.action = action
        self._color_chips()
        self._update_info()
        self._refresh_options()

    def _refresh_options(self):
        a = self.action
        cats = {category(p) for p in self._paths()}
        n = len(self.order)
        show = []
        if a and a.startswith("tool:"):
            show = [{"split": self.box_split, "rotate": self.box_rotate,
                     "extract": self.box_extract, "compress": self.box_compress}[a[5:]]]
        elif a:
            images = "image" in cats
            pdfs = "pdf" in cats
            if a == "pdf":
                if n > 1:
                    show.append(self.sw_merge)
                if images:
                    show += [self.sw_a4, self.box_resize]
            elif a in ("jpg", "webp"):
                show += [self.box_resize, self.box_quality, self.box_filesize]
                if pdfs:
                    show.append(self.box_dpi)
            elif a in ("dxf", "dwg"):
                show.append(self.box_cad)
            elif a in ("png", "tiff", "bmp", "gif"):
                if images or pdfs:
                    show.append(self.box_resize)
                if pdfs:
                    show.append(self.box_dpi)
        boxes = [self.sw_merge, self.sw_a4, self.box_resize, self.box_quality, self.box_filesize,
                 self.box_dpi, self.box_split, self.box_rotate, self.box_extract,
                 self.box_compress, self.box_cad, self.no_options]
        for w in boxes:
            w.pack_forget()
        for w in show or [self.no_options]:
            w.pack(fill="x", anchor="w", pady=6)

        free = not self.busy
        state = "normal" if free else "disabled"
        for w in self.controls:
            try:
                w.configure(state=state)
            except Exception:
                pass
        for b in getattr(self, "chip_buttons", {}).values():
            b.configure(state=state)
        self._update_arrows()

        if self.busy:
            text = t("btn.working")
        elif not a:
            text = t("btn.convert_plain")
        elif a.startswith("tool:"):
            tool = a[5:]
            if tool == "extract" and self.sw_remove.get():
                tool = "remove"
            text = t(f"btn.tool.{tool}")
        elif a == "pdf" and n > 1 and self.sw_merge.get():
            text = t("btn.merge")
        else:
            text = t("btn.convert", fmt=a.upper())
        ready = free and a is not None and n > 0
        self.start_button.configure(text=text + ("  →" if ready else ""),
                                    state="normal" if ready else "disabled",
                                    fg_color=ACCENT if ready else ACCENT_SOFT)
        self.open_button.configure(state="normal" if self.last_dir else "disabled")
        if hasattr(self, "banner_button"):
            self.banner_button.configure(state="normal" if free and not self.updating else "disabled")

    def _output_chosen(self, label: str):
        if label == self.output_labels["same"]:
            self.settings["output_mode"] = "same"
            self._refresh()
        else:
            self._choose_output()

    def _choose_output(self):
        if self.busy:
            return
        folder = filedialog.askdirectory(title=t("dialog.output_folder"))
        if folder:
            self.settings["output_dir"] = folder
            self.settings["output_mode"] = "other"
        elif not self.settings["output_dir"]:
            self.seg_output.set(self.output_labels["same"])
            self.settings["output_mode"] = "same"
        self._refresh()

    def _open_folder(self):
        if self.last_dir and self.last_dir.exists():
            if sys.platform == "win32":
                os.startfile(str(self.last_dir))
            else:
                subprocess.Popen(["xdg-open", str(self.last_dir)])

    # ============================================================ settings
    def _read_options(self) -> Options | None:
        """Reads every control, stores it in the settings and returns Options."""
        s = self.settings
        a = self.action or ""
        resize = self._code(self.resize_labels, self.menu_resize.get()) or "original"
        max_side = RESIZE[resize]
        if resize == "custom":
            try:
                max_side = int(self.entry_size.get().strip())
                if not 16 <= max_side <= 30000:
                    raise ValueError
            except ValueError:
                messagebox.showwarning(t("msg.check_title"), t("msg.bad_size"))
                return None
            s["custom_size"] = max_side
        filesize = self._code(self.filesize_labels, self.menu_filesize.get()) or "none"
        split_mode = self._code(self.split_labels, self.seg_split.get()) or "single"
        try:
            split_n = int(self.entry_split_n.get().strip() or "2")
            if split_n < 1:
                raise ValueError
        except ValueError:
            if a == "tool:split" and split_mode == "every":
                messagebox.showwarning(t("msg.check_title"), t("msg.bad_number"))
                return None
            split_n = 2
        rotate = self._code(self.rotate_labels, self.seg_rotate.get()) or "right"
        compress = self._code(self.compress_labels, self.seg_compress.get()) or "strong"
        cad_scale = self._code(self.cad_labels, self.menu_cad.get()) or 1

        # quick syntax check of page numbers before we start
        checks = {"tool:split": self.entry_split_ranges.get() if split_mode == "ranges" else "",
                  "tool:rotate": self.entry_rotate.get(), "tool:extract": self.entry_extract.get()}
        spec = checks.get(a, "")
        if a == "tool:extract" and not spec.strip():
            messagebox.showwarning(t("msg.check_title"), t("err.pages_required"))
            return None
        if a == "tool:split" and split_mode == "ranges" and not spec.strip():
            messagebox.showwarning(t("msg.check_title"), t("err.pages_required"))
            return None
        if spec.strip():
            try:
                engine.parse_pages(spec, 10 ** 6)
            except ShiftError as e:
                messagebox.showwarning(t("msg.check_title"), e.message())
                return None

        s.update({
            "merge": bool(self.sw_merge.get()), "a4": bool(self.sw_a4.get()),
            "quality": int(self.slider_quality.get()),
            "dpi": int(self.seg_dpi.get().split()[0]), "resize": resize,
            "max_filesize": filesize, "split_mode": split_mode, "split_n": split_n,
            "split_ranges": self.entry_split_ranges.get().strip(),
            "rotate": ROTATIONS[rotate], "rotate_pages": self.entry_rotate.get().strip(),
            "extract_pages": self.entry_extract.get().strip(),
            "extract_remove": bool(self.sw_remove.get()), "compress": compress,
            "cad_scale": cad_scale,
            "last_action": self.action,
        })
        s.save()
        n = len(self.order)
        return Options(
            merge=a == "pdf" and n > 1 and s["merge"], a4=s["a4"], quality=s["quality"],
            dpi=s["dpi"], max_side=max_side, max_bytes=FILESIZE[filesize],
            split_mode=split_mode, split_n=split_n, split_ranges=s["split_ranges"],
            rotate=s["rotate"], rotate_pages=s["rotate_pages"],
            extract_pages=s["extract_pages"], extract_remove=s["extract_remove"],
            compress=compress, cad_scale=cad_scale)

    def _open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.focus()
            return
        self.settings_window = SettingsWindow(self)

    def apply_language(self, code: str):
        self.settings["language"] = code
        self.settings.save()
        if self.busy:
            self.pending_language = code
            return
        i18n.setup(code)
        paths = self._paths()
        self.items.clear()
        self.order.clear()
        self.errors.clear()
        self.formats, self.tools = [], []
        self._build()
        for path in paths:
            self._make_card(path)
        self._update_arrows()
        self._refresh()

    # ============================================================ convert
    def _start(self):
        action = self.action
        if self.busy or not action or not self.order:
            return
        opt = self._read_options()
        if opt is None:
            return
        outdir = (Path(self.settings["output_dir"])
                  if self.settings["output_mode"] == "other" and self.settings["output_dir"] else None)
        jobs = [(k, self.items[k]["path"]) for k in self.order]
        self.errors.clear()
        for k, _ in jobs:
            self._set_status(k, "waiting", t("status.waiting"))
        self.busy = True
        self.last_dir = None
        self.total = len(jobs)
        self.progress.set(0)
        self.progress.configure(progress_color=ACCENT)
        self.status.configure(text=t("status.converting"), text_color=MUTED)
        self._refresh_options()
        threading.Thread(target=self._work, args=(jobs, action, opt, outdir), daemon=True).start()

    def _work(self, jobs, action: str, opt: Options, fixed_dir: Path | None):
        office = Office()
        tmp = Path(tempfile.mkdtemp(prefix="shift_"))
        done = failed = 0
        last_dir = None
        merge_paths: list[Path] = []
        merge_keys: list[str] = []
        merged: Path | None = None
        try:
            for i, (key, path) in enumerate(jobs, start=1):
                self.q.put(("status", key, "working", t("status.working")))
                outdir = fixed_dir or path.parent
                try:
                    if opt.merge:
                        if category(path) == "pdf":
                            engine.open_pdf(path).close()  # damaged/protected PDFs drop out here
                            merge_paths.append(path)
                        else:
                            merge_paths += engine.convert(path, "pdf", tmp, opt, office)
                        merge_keys.append(key)
                        self.q.put(("status", key, "working", t("status.ready_to_merge")))
                    else:
                        engine.run(path, action, outdir, opt, office)
                        last_dir = outdir
                        done += 1
                        self.q.put(("status", key, "ok", t("status.done")))
                except Exception as e:
                    failed += 1
                    self.q.put(("error", key, engine.error_message(e)))
                self.q.put(("progress", i))

            if merge_paths:
                first = jobs[0][1]
                outdir = fixed_dir or first.parent
                merged = engine.unique_path(outdir / f"{first.stem} - {t('name.merged')}.pdf")
                try:
                    engine.merge_pdfs(merge_paths, merged)
                    last_dir = outdir
                    done += len(merge_keys)
                    for key in merge_keys:
                        self.q.put(("status", key, "ok", t("status.merged")))
                except Exception as e:
                    merged = None
                    failed += len(merge_keys)
                    for key in merge_keys:
                        self.q.put(("error", key, engine.error_message(e)))
        finally:
            office.close()
            shutil.rmtree(tmp, ignore_errors=True)
            self.q.put(("finished", done, failed, last_dir, merged))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self._set_status(msg[1], msg[2], msg[3])
                elif kind == "error":
                    self.errors[msg[1]] = msg[2]
                    self._set_status(msg[1], "error", t("status.failed"))
                elif kind == "progress":
                    self.progress.set(msg[1] / max(1, self.total))
                elif kind == "finished":
                    self._finished(*msg[1:])
                elif kind == "update":
                    self._update_checked(*msg[1:])
                elif kind == "update_progress":
                    self.banner_button.configure(text=f"{int(msg[1] * 100)}%")
                elif kind == "update_ready":
                    self._restart_with(msg[1])
                elif kind == "update_failed":
                    self.updating = False
                    self.banner_button.configure(text=t("update.now"))
                    self._refresh_options()
                    messagebox.showwarning(t("update.failed_title"), t("update.failed", reason=msg[1]))
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finished(self, done: int, failed: int, last_dir, merged):
        self.busy = False
        self.last_dir = last_dir
        if merged:
            text, color = t("result.merged", name=merged.name), GREEN
        elif failed == 0:
            text, color = tn("result.done", done), GREEN
        else:
            text, color = t("result.partial", done=done, failed=failed), RED
        self.status.configure(text=text, text_color=color)
        self._refresh_options()
        if self.pending_language:
            code, self.pending_language = self.pending_language, None
            self.apply_language(code)

    # ============================================================= updates
    def _check_updates(self, manual: bool):
        if not updater.configured():
            if manual and self.settings_window:
                self.settings_window.set_update_status(t("update.not_configured"))
            return

        def work():
            try:
                self.q.put(("update", updater.check_latest(), manual, None))
            except Exception as e:
                self.q.put(("update", None, manual, e))
        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, info, manual: bool, error):
        self.settings["last_update_check"] = time.time()
        self.settings.save()
        window = self.settings_window if self.settings_window and self.settings_window.winfo_exists() else None
        if error or not info:
            if manual and window:
                window.set_update_status(t("update.check_failed"))
            return
        if updater.is_newer(info["version"]):
            self.update_info = info
            self._show_banner()
            if window:
                window.set_update_status(t("update.available", version=info["version"]))
        elif manual and window:
            window.set_update_status(t("update.latest"))

    def _show_banner(self):
        self.banner_text.configure(text=t("update.available", version=self.update_info["version"]))
        self.banner.grid(row=1, column=0, sticky="ew", padx=28, pady=(10, 0))

    def _hide_banner(self):
        self.banner.grid_remove()

    def _install_update(self):
        info = self.update_info
        if not info or self.busy or self.updating:
            return
        if not updater.can_self_update(info):
            webbrowser.open(info["page"])
            return
        self.updating = True
        self._refresh_options()
        self.banner_button.configure(text="0%")

        def work():
            try:
                path = updater.download(info, progress=lambda f: self.q.put(("update_progress", f)))
                self.q.put(("update_ready", path))
            except Exception as e:
                self.q.put(("update_failed", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _restart_with(self, new_exe: Path):
        self._save_window()
        updater.apply_and_restart(new_exe)
        self.destroy()

    # =============================================================== quit
    def _save_window(self):
        try:
            self.settings["window_size"] = self.geometry().split("+")[0]
        except Exception:
            pass
        self.settings.save()

    def _quit(self):
        if self.busy and not messagebox.askyesno(t("msg.busy_title"), t("msg.busy")):
            return
        try:
            grab = self.grab_current()
            if grab is not None:
                grab.grab_release()
        except Exception:
            pass
        if self.settings_window is not None:
            try:
                self.settings_window.destroy()
            except Exception:
                pass
        self._save_window()
        self.destroy()


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app: Shift):
        super().__init__(app)
        self.app = app
        s = app.settings
        self.title(t("settings.title"))
        self.geometry("440x470")
        self.resizable(False, False)
        self.configure(fg_color=PANEL)
        self.transient(app)
        self.after(150, self._bring_up)
        if sys.platform == "win32":
            self.after(300, lambda: app._set_icon(self))
            self.after(50, lambda: color_titlebar(self))
        self.protocol("WM_DELETE_WINDOW", self._close)

        p = ctk.CTkFrame(self, fg_color="transparent")
        p.pack(fill="both", expand=True, padx=26, pady=22)
        ctk.CTkLabel(p, text=t("settings.title"), font=F(18, "bold"), text_color=TEXT,
                     anchor="w").pack(fill="x", pady=(0, 12))

        # language
        app._section(p, "settings.language", top=6)
        self.languages = {"auto": t("settings.language_auto")}
        self.languages.update(i18n.language_names())
        self.menu_language = app._menu(p, list(self.languages.values()))
        self.menu_language.set(self.languages.get(s["language"], self.languages["auto"]))
        self.menu_language.pack(fill="x", pady=(8, 0))

        # theme
        app._section(p, "settings.theme", top=20)
        self.themes = {code: t(f"theme.{code}") for code in ("system", "light", "dark")}
        self.seg_theme = app._segments(p, list(self.themes.values()), command=self._theme)
        self.seg_theme.set(self.themes.get(s["theme"], self.themes["system"]))
        self.seg_theme.pack(fill="x", pady=(8, 0))

        # updates
        app._section(p, "settings.updates", top=20)
        self.sw_auto = app._switch(p, "settings.auto_update", command=self._auto_update)
        if s["auto_update"]:
            self.sw_auto.select()
        self.sw_auto.pack(fill="x", pady=(10, 8))
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkButton(row, text=t("settings.check_now"), height=34, corner_radius=8,
                      fg_color=INPUT, hover_color=HOVER, text_color=TEXT, font=F(12),
                      command=self._check).pack(side="left")
        self.update_status = ctk.CTkLabel(row, text="", font=F(12), text_color=MUTED,
                                          anchor="w", wraplength=230, justify="left")
        self.update_status.pack(side="left", padx=12)
        ctk.CTkLabel(p, text=t("settings.version", version=__version__), font=F(11),
                     text_color=MUTED2, anchor="w").pack(fill="x", pady=(10, 0))

        ctk.CTkButton(p, text=t("settings.done"), height=40, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ON_ACCENT,
                      font=F(13, "bold"), command=self._close).pack(side="bottom", fill="x")

    def _set_appearance_mode(self, mode_string):
        super()._set_appearance_mode(mode_string)
        self.after(20, lambda: color_titlebar(self, mode_string))

    def _bring_up(self):
        # deliberately no grab_set(): a blocking dialog can lock up the whole app
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _theme(self, label: str):
        code = Shift._code(self.themes, label) or "system"
        self.app.settings["theme"] = code
        self.app.settings.save()
        ctk.set_appearance_mode(code)
        self.after(150, self._bring_up)

    def _auto_update(self):
        self.app.settings["auto_update"] = bool(self.sw_auto.get())
        self.app.settings.save()

    def _check(self):
        self.set_update_status(t("update.checking"))
        self.app._check_updates(manual=True)

    def set_update_status(self, text: str):
        if self.winfo_exists():
            self.update_status.configure(text=text)

    def _close(self):
        code = Shift._code(self.languages, self.menu_language.get()) or "auto"
        changed = code != self.app.settings["language"]
        self.destroy()
        self.app.settings_window = None
        if changed:
            self.app.apply_language(code)


def main():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Shift.FileConverter")
        except Exception:
            pass
    # see color_titlebar(): never hide and re-show windows on a theme change
    ctk.CTk._deactivate_windows_window_header_manipulation = True
    ctk.CTkToplevel._deactivate_windows_window_header_manipulation = True
    settings = Settings()
    i18n.setup(settings["language"])
    ctk.set_appearance_mode(settings["theme"])
    Shift(settings, sys.argv[1:]).mainloop()


if __name__ == "__main__":
    main()
