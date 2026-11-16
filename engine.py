"""Conversion engine for Shift: images, PDF, Office documents, video and audio.

Nothing in here touches the user interface. Every function takes a source file
and an output folder, writes new files and returns their paths. Errors meant
for the user are raised as ShiftError with a translation key.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

try:
    import pymupdf as fitz
except ImportError:  # older PyMuPDF
    import fitz

try:  # iPhone photos (HEIC)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

from i18n import t

NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class ShiftError(Exception):
    """An error with a translated, user-friendly message."""

    def __init__(self, key: str, **values):
        super().__init__(key)
        self.key = key
        self.values = values

    def message(self) -> str:
        return t(self.key, **self.values)


def error_message(e: Exception) -> str:
    if isinstance(e, ShiftError):
        return e.message()
    info = getattr(e, "excepinfo", None)  # Office/COM errors
    text = str(info[2]) if info and len(info) > 2 and info[2] else (str(e) or e.__class__.__name__)
    return " ".join(text.split())[:400]


# --------------------------------------------------------------------------
# File types
# --------------------------------------------------------------------------
# category: (input extensions, possible output formats)
CATEGORIES: dict[str, tuple[set[str], list[str]]] = {
    "image": ({"jpg", "jpeg", "png", "bmp", "gif", "tif", "tiff", "webp", "heic", "heif", "ico"},
              ["pdf", "jpg", "png", "webp", "tiff", "bmp", "gif", "ico"]),
    "pdf": ({"pdf"},
            ["pdf", "docx", "jpg", "png", "tiff", "txt", "dxf", "dwg"]),
    "document": ({"doc", "docx", "rtf", "odt", "txt", "htm", "html"},
                 ["pdf", "docx", "doc", "rtf", "odt", "txt", "html"]),
    "spreadsheet": ({"xls", "xlsx", "xlsm", "csv", "ods"},
                    ["pdf", "xlsx", "xls", "csv", "ods"]),
    "presentation": ({"ppt", "pptx", "odp"},
                     ["pdf", "pptx", "ppt", "odp", "jpg", "png"]),
    "video": ({"mp4", "mov", "avi", "mkv", "wmv", "webm", "m4v", "mpg", "mpeg", "3gp"},
              ["mp4", "mov", "avi", "mkv", "webm", "gif", "mp3", "wav"]),
    "audio": ({"mp3", "wav", "m4a", "aac", "flac", "ogg", "wma", "opus"},
              ["mp3", "wav", "m4a", "aac", "flac", "ogg"]),
}

PDF_TOOLS = ["split", "rotate", "extract", "compress"]

ALIASES = {"jpeg": "jpg", "tif": "tiff", "htm": "html", "heif": "heic"}


def ext_of(path: Path) -> str:
    e = path.suffix.lower().lstrip(".")
    return ALIASES.get(e, e)


def category(path: Path) -> str | None:
    e = path.suffix.lower().lstrip(".")
    for name, (inputs, _) in CATEGORIES.items():
        if e in inputs:
            return name
    return None


def targets_for(path: Path) -> list[str]:
    cat = category(path)
    if not cat:
        return []
    if cat == "image":  # same format = resize / recompress
        return list(CATEGORIES[cat][1])
    own = ext_of(path)
    return [d for d in CATEGORIES[cat][1] if d != own or d == "pdf"]


@dataclass
class Options:
    merge: bool = False
    a4: bool = True
    quality: int = 85
    dpi: int = 200
    max_side: int | None = None        # resize: longest side in pixels
    max_bytes: int | None = None       # JPG/WebP: target file size
    split_mode: str = "single"         # single | every | ranges
    split_n: int = 2
    split_ranges: str = ""
    rotate: int = 90                   # 90, 180 or 270 (clockwise)
    rotate_pages: str = ""
    extract_pages: str = ""
    extract_remove: bool = False
    compress: str = "strong"           # light | strong
    cad_scale: int = 1                 # DXF/DWG: drawing scale 1:N (1 = paper size in mm)


def unique_path(p: Path) -> Path:
    """Never overwrite: returns 'name (2).ext', 'name (3).ext', ..."""
    if not p.exists():
        return p
    i = 2
    while True:
        candidate = p.with_name(f"{p.stem} ({i}){p.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def unique_dir(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while True:
        candidate = p.parent / f"{p.name} ({i})"
        if not candidate.exists():
            return candidate
        i += 1


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
def open_image(path: Path) -> Image.Image:
    img = Image.open(path)
    try:
        img = ImageOps.exif_transpose(img)  # phone photos the right way up
    except Exception:
        pass
    return img


def has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def on_white(img: Image.Image) -> Image.Image:
    if has_alpha(img):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.split()[3])
        return background
    return img.convert("RGB")


def normalize(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "RGBA", "L", "LA", "P", "1"):
        return img
    return img.convert("RGBA" if has_alpha(img) else "RGB")


def shrink(img: Image.Image, max_side: int | None) -> Image.Image:
    """Scale down so the longest side is at most max_side (never enlarges)."""
    if not max_side or max(img.size) <= max_side:
        return img
    if img.mode in ("P", "1"):
        img = img.convert("RGBA" if has_alpha(img) else "RGB")
    img = img.copy()
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img


def _icc(img: Image.Image) -> dict:
    profile = img.info.get("icc_profile")
    if profile and img.mode in ("RGB", "RGBA", "L", "LA", "P"):
        return {"icc_profile": profile}
    return {}


def _encode(img: Image.Image, ext: str, quality: int, icc: dict) -> bytes:
    buf = io.BytesIO()
    if ext == "jpg":
        on_white(img).save(buf, "JPEG", quality=quality, optimize=True, progressive=True,
                           subsampling=0 if quality >= 90 else 2, **icc)
    else:
        normalize(img).save(buf, "WEBP", quality=quality, method=5, **icc)
    return buf.getvalue()


def _encode_to_size(img: Image.Image, ext: str, max_bytes: int, icc: dict) -> bytes:
    """Highest quality that fits max_bytes; scales the image down if needed."""
    current = img
    for _ in range(10):
        low, high, best = 30, 95, None
        while low <= high:
            q = (low + high) // 2
            data = _encode(current, ext, q, icc)
            if len(data) <= max_bytes:
                best, low = data, q + 1
            else:
                high = q - 1
        if best is not None:
            return best
        w, h = current.size
        if max(w, h) <= 64:
            break
        current = current.resize((max(1, int(w * 0.8)), max(1, int(h * 0.8))), Image.LANCZOS)
    raise ShiftError("err.target_size")


def save_image(img: Image.Image, dest: Path, ext: str, opt: Options) -> None:
    icc = _icc(img)
    img = shrink(img, opt.max_side)
    if ext in ("jpg", "webp"):
        data = (_encode_to_size(img, ext, opt.max_bytes, icc) if opt.max_bytes
                else _encode(img, ext, opt.quality, icc))
        dest.write_bytes(data)
    elif ext == "png":
        normalize(img).save(dest, "PNG", optimize=True, **icc)
    elif ext == "bmp":
        on_white(img).save(dest, "BMP")
    elif ext == "gif":
        normalize(img).save(dest, "GIF")
    elif ext == "tiff":
        normalize(img).save(dest, "TIFF", compression="tiff_lzw", **icc)
    elif ext == "ico":
        im = normalize(img).convert("RGBA")
        side = max(im.size)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
        sizes = [s for s in (16, 24, 32, 48, 64, 128, 256) if s <= side] or [16]
        square.save(dest, "ICO", sizes=[(s, s) for s in sizes])
    else:
        raise ShiftError("err.unknown_conversion")


A4 = (595.28, 841.89)  # points


def images_to_pdf(sources: list[Path], dest: Path, opt: Options) -> None:
    doc = fitz.open()
    try:
        for src in sources:
            img = shrink(open_image(src), opt.max_side)
            buf = io.BytesIO()
            if ext_of(src) in ("jpg", "heic", "webp"):
                on_white(img).save(buf, "JPEG", quality=max(opt.quality, 80))
            else:  # scans and screenshots: keep them sharp
                on_white(img).save(buf, "PNG")
            w, h = img.size
            nat_w, nat_h = w * 72 / 150, h * 72 / 150  # natural size at 150 dpi
            if opt.a4:
                pw, ph = A4 if h >= w else (A4[1], A4[0])
                margin = 28.35  # 1 cm
                scale = min(1.0, (pw - 2 * margin) / nat_w, (ph - 2 * margin) / nat_h)
                bw, bh = nat_w * scale, nat_h * scale
                x0, y0 = (pw - bw) / 2, (ph - bh) / 2
                rect = fitz.Rect(x0, y0, x0 + bw, y0 + bh)
            else:
                pw, ph = nat_w, nat_h
                rect = fitz.Rect(0, 0, pw, ph)
            page = doc.new_page(width=pw, height=ph)
            page.insert_image(rect, stream=buf.getvalue(), keep_proportion=True)
        doc.save(str(dest), garbage=3, deflate=True)
    finally:
        doc.close()


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def open_pdf(src: Path):
    try:
        doc = fitz.open(str(src))
    except Exception:
        raise ShiftError("err.pdf_damaged")
    if doc.needs_pass:
        doc.close()
        raise ShiftError("err.pdf_password")
    if doc.page_count == 0:
        doc.close()
        raise ShiftError("err.pdf_empty")
    return doc


def _save_pdf(doc, dest: Path) -> None:
    doc.save(str(dest), garbage=3, deflate=True)


def parse_pages(spec: str, count: int) -> list[int]:
    """'1-3, 5, 8-' -> zero-based page numbers in the given order (no duplicates).

    An empty spec means all pages. 'N-' runs to the last page, '-N' from the first.
    """
    spec = spec.strip()
    if not spec:
        return list(range(count))
    result: list[int] = []
    for part in spec.replace(";", ",").split(","):
        part = part.strip().replace(" ", "")
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                start = int(a) if a else 1
                end = int(b) if b else count
            else:
                start = end = int(part)
        except ValueError:
            raise ShiftError("err.pages_invalid", part=part)
        if start < 1 or end < 1:
            raise ShiftError("err.pages_invalid", part=part)
        for n in (start, end):
            if n > count:
                raise ShiftError("err.pages_range", page=n, count=count)
        step = 1 if end >= start else -1
        for n in range(start, end + step, step):
            if n - 1 not in result:
                result.append(n - 1)
    if not result:
        raise ShiftError("err.pages_required")
    return result


def parse_groups(spec: str, count: int) -> list[list[int]]:
    """'1-3, 4-6' -> one group of pages per comma-separated part (used for splitting)."""
    groups = [parse_pages(part, count) for part in spec.replace(";", ",").split(",") if part.strip()]
    if not groups:
        raise ShiftError("err.pages_required")
    return groups


def _label(pages: list[int]) -> str:
    """[0,1,2] -> '1-3', [4] -> '5'."""
    if len(pages) > 1 and pages == list(range(pages[0], pages[-1] + 1)):
        return f"{pages[0] + 1}-{pages[-1] + 1}"
    if len(pages) == 1:
        return str(pages[0] + 1)
    return ",".join(str(p + 1) for p in pages)


def _pages_name(pages: list[int]) -> str:
    word = t("name.page") if len(pages) == 1 else t("name.pages")
    return f"{word} {_label(pages)}"


def pdf_split(src: Path, outdir: Path, opt: Options) -> list[Path]:
    doc = open_pdf(src)
    try:
        n = doc.page_count
        if opt.split_mode == "every":
            size = max(1, opt.split_n)
            groups = [list(range(i, min(i + size, n))) for i in range(0, n, size)]
        elif opt.split_mode == "ranges":
            groups = parse_groups(opt.split_ranges, n)
        else:
            groups = [[i] for i in range(n)]
        folder = unique_dir(outdir / f"{src.stem} - {t('name.split')}")
        folder.mkdir(parents=True)
        for pages in groups:
            part = fitz.open()
            for p in pages:
                part.insert_pdf(doc, from_page=p, to_page=p)
            _save_pdf(part, unique_path(folder / f"{src.stem} - {_pages_name(pages)}.pdf"))
            part.close()
        return [folder]
    finally:
        doc.close()


def pdf_rotate(src: Path, outdir: Path, opt: Options) -> list[Path]:
    doc = open_pdf(src)
    try:
        for p in parse_pages(opt.rotate_pages, doc.page_count):
            page = doc[p]
            page.set_rotation((page.rotation + opt.rotate) % 360)
        dest = unique_path(outdir / f"{src.stem} - {t('name.rotated')}.pdf")
        _save_pdf(doc, dest)
        return [dest]
    finally:
        doc.close()


def pdf_extract(src: Path, outdir: Path, opt: Options) -> list[Path]:
    if not opt.extract_pages.strip():
        raise ShiftError("err.pages_required")
    doc = open_pdf(src)
    try:
        chosen = parse_pages(opt.extract_pages, doc.page_count)
        if opt.extract_remove:
            keep = [p for p in range(doc.page_count) if p not in chosen]
            if not keep:
                raise ShiftError("err.remove_all")
            name = t("name.pages_removed")
        else:
            keep = chosen
            name = _pages_name(chosen)
        doc.select(keep)
        dest = unique_path(outdir / f"{src.stem} - {name}.pdf")
        _save_pdf(doc, dest)
        return [dest]
    finally:
        doc.close()


def pdf_compress(src: Path, outdir: Path, opt: Options) -> list[Path]:
    doc = open_pdf(src)
    dest = unique_path(outdir / f"{src.stem} - {t('name.compressed')}.pdf")
    try:
        if opt.compress == "strong" and hasattr(doc, "rewrite_images"):
            try:
                doc.rewrite_images(dpi_threshold=180, dpi_target=150, quality=70)
            except Exception:
                pass
        doc.save(str(dest), garbage=4, deflate=True, deflate_images=True,
                 deflate_fonts=True, clean=True)
    finally:
        doc.close()
    # never hand back a bigger file than we started with
    if dest.stat().st_size >= src.stat().st_size and opt.compress == "strong":
        light = Options(**{**opt.__dict__, "compress": "light"})
        dest.unlink()
        return pdf_compress(src, outdir, light)
    return [dest]


def pdf_to_images(src: Path, ext: str, outdir: Path, opt: Options) -> list[Path]:
    doc = open_pdf(src)
    try:
        n = doc.page_count

        def render(page) -> Image.Image:
            pix = page.get_pixmap(dpi=opt.dpi)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        if ext == "tiff":  # all pages in one TIFF
            frames = [shrink(render(p), opt.max_side) for p in doc]
            dest = unique_path(outdir / f"{src.stem}.tiff")
            frames[0].save(dest, "TIFF", save_all=True, append_images=frames[1:],
                           compression="tiff_lzw")
            return [dest]
        if n == 1:
            dest = unique_path(outdir / f"{src.stem}.{ext}")
            save_image(render(doc[0]), dest, ext, opt)
            return [dest]
        folder = unique_dir(outdir / f"{src.stem} - {t('name.pages')}")
        folder.mkdir(parents=True)
        digits = len(str(n))
        word = t("name.page")
        for i, page in enumerate(doc, start=1):
            save_image(render(page), folder / f"{src.stem} - {word} {i:0{digits}d}.{ext}", ext, opt)
        return [folder]
    finally:
        doc.close()


def pdf_to_text(src: Path, dest: Path) -> None:
    doc = open_pdf(src)
    try:
        text = "\n\n".join(p.get_text() for p in doc)
    finally:
        doc.close()
    if not text.strip():
        raise ShiftError("err.pdf_no_text")
    dest.write_text(text, encoding="utf-8-sig")


def pdf_to_word_without_office(src: Path, dest: Path) -> None:
    try:
        from pdf2docx import Converter
    except ImportError:
        raise ShiftError("err.needs_word")
    conv = Converter(str(src))
    try:
        conv.convert(str(dest))
    finally:
        conv.close()


def merge_pdfs(paths: list[Path], dest: Path) -> None:
    out = fitz.open()
    try:
        for p in paths:
            with fitz.open(str(p)) as d:
                if d.needs_pass:
                    raise ShiftError("err.pdf_password")
                out.insert_pdf(d)
        out.save(str(dest), garbage=3, deflate=True)
    finally:
        out.close()


# --------------------------------------------------------------------------
# PDF to CAD (DXF, and DWG through the free ODA File Converter)
# --------------------------------------------------------------------------
PT_TO_MM = 25.4 / 72
LINEWEIGHTS = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100,
               106, 120, 140, 158, 200, 211]  # valid DXF lineweights (1/100 mm)
ODA_DOWNLOAD = "https://www.opendesign.com/guestfiles/oda_file_converter"


def _true_color(rgb) -> int | None:
    if not rgb:
        return None
    r, g, b = (max(0, min(255, round(c * 255))) for c in rgb[:3])
    return (r << 16) | (g << 8) | b


def _lineweight(width_pt: float | None) -> int:
    if not width_pt:
        return 0
    target = width_pt * PT_TO_MM * 100
    return min(LINEWEIGHTS, key=lambda w: abs(w - target))


def _bezier_points(p0, p1, p2, p3, steps: int = 12):
    for i in range(1, steps + 1):
        t = i / steps
        mt = 1 - t
        yield (mt ** 3 * p0[0] + 3 * mt ** 2 * t * p1[0] + 3 * mt * t ** 2 * p2[0] + t ** 3 * p3[0],
               mt ** 3 * p0[1] + 3 * mt ** 2 * t * p1[1] + 3 * mt * t ** 2 * p2[1] + t ** 3 * p3[1])


def _path_runs(items, to_xy) -> list[list[tuple[float, float]]]:
    """Turns PyMuPDF drawing items into connected point lists (in CAD coordinates)."""
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    def start(point):
        nonlocal current
        if current and abs(current[-1][0] - point[0]) < 1e-6 and abs(current[-1][1] - point[1]) < 1e-6:
            return
        if len(current) > 1:
            runs.append(current)
        current = [point]

    for item in items:
        kind = item[0]
        if kind == "l":
            a, b = to_xy(item[1]), to_xy(item[2])
            start(a)
            current.append(b)
        elif kind == "c":
            pts = [to_xy(p) for p in item[1:5]]
            start(pts[0])
            current.extend(_bezier_points(*pts))
        elif kind == "re":
            r = item[1]
            corners = [to_xy(fitz.Point(r.x0, r.y0)), to_xy(fitz.Point(r.x1, r.y0)),
                       to_xy(fitz.Point(r.x1, r.y1)), to_xy(fitz.Point(r.x0, r.y1))]
            if len(current) > 1:
                runs.append(current)
            runs.append(corners + [corners[0]])
            current = []
        elif kind == "qu":
            q = item[1]
            corners = [to_xy(q.ul), to_xy(q.ur), to_xy(q.lr), to_xy(q.ll)]
            if len(current) > 1:
                runs.append(current)
            runs.append(corners + [corners[0]])
            current = []
    if len(current) > 1:
        runs.append(current)
    return runs


def _page_to_dxf(page, dest: Path, opt: Options) -> None:
    import ezdxf
    from math import atan2, degrees

    k = PT_TO_MM * max(1, opt.cad_scale)
    rotate = page.rotation_matrix
    height = page.rect.height

    def to_xy(p) -> tuple[float, float]:
        q = fitz.Point(p) * rotate
        return q.x * k, (height - q.y) * k

    drawings = page.get_drawings()
    text = page.get_text("dict")
    spans = [(line, span) for block in text.get("blocks", []) if block.get("type") == 0
             for line in block.get("lines", []) for span in line.get("spans", [])
             if span.get("text", "").strip()]
    if not drawings and not spans:
        raise ShiftError("err.pdf_no_vectors")

    doc = ezdxf.new("R2018", setup=True)
    doc.units = ezdxf.units.MM
    for name, color in (("PDF_LINES", 7), ("PDF_FILLS", 8), ("PDF_TEXT", 7)):
        doc.layers.add(name, color=color)
    msp = doc.modelspace()

    for d in drawings:
        runs = _path_runs(d.get("items", []), to_xy)
        if not runs:
            continue
        kind = d.get("type") or "s"
        closed = bool(d.get("closePath"))
        if "f" in kind and d.get("fill"):
            hatch = msp.add_hatch(dxfattribs={"layer": "PDF_FILLS"})
            hatch.set_solid_fill(rgb=None)
            hatch.dxf.true_color = _true_color(d["fill"])
            for run in runs:
                hatch.paths.add_polyline_path(run, is_closed=True)
        if "s" in kind and d.get("color") is not None:
            attribs = {"layer": "PDF_LINES", "lineweight": _lineweight(d.get("width"))}
            color = _true_color(d.get("color"))
            for run in runs:
                is_closed = closed or (len(run) > 2 and run[0] == run[-1])
                points = run[:-1] if is_closed and run[0] == run[-1] else run
                pl = msp.add_lwpolyline(points, close=is_closed, dxfattribs=attribs)
                if color is not None:
                    pl.dxf.true_color = color

    for line, span in spans:
        direction = fitz.Point(line.get("dir", (1, 0))) * fitz.Matrix(rotate.a, rotate.b, rotate.c, rotate.d, 0, 0)
        entity = msp.add_text(span["text"], dxfattribs={
            "layer": "PDF_TEXT",
            "height": max(0.01, span.get("size", 10) * 0.7 * k),
            "rotation": degrees(atan2(-direction.y, direction.x)),
        })
        entity.set_placement(to_xy(span["origin"]))
        color = span.get("color")
        if isinstance(color, int) and color:
            entity.dxf.true_color = color

    doc.saveas(dest)


def find_oda_converter() -> str | None:
    import glob
    found = shutil.which("ODAFileConverter")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            hits = sorted(glob.glob(os.path.join(base, "ODA", "ODAFileConverter*", "ODAFileConverter.exe")))
            if hits:
                return hits[-1]  # newest version
    return None


def dxf_to_dwg(dxf_files: list[Path]) -> list[Path]:
    """Converts DXF files to DWG (AutoCAD 2018) next to them, then removes the DXF."""
    oda = find_oda_converter()
    if not oda:
        raise ShiftError("err.needs_oda", url=ODA_DOWNLOAD)
    results = []
    with tempfile.TemporaryDirectory(prefix="shift_oda_") as tmp:
        src_dir, out_dir = Path(tmp, "in"), Path(tmp, "out")
        src_dir.mkdir()
        out_dir.mkdir()
        for f in dxf_files:
            shutil.copy2(f, src_dir / f.name)
        subprocess.run([oda, str(src_dir), str(out_dir), "ACAD2018", "DWG", "0", "1", "*.DXF"],
                       capture_output=True, timeout=900, creationflags=NO_WINDOW)
        for f in dxf_files:
            made = out_dir / (f.stem + ".dwg")
            if not made.exists():
                raise ShiftError("err.oda_failed")
            dest = unique_path(f.with_suffix(".dwg"))
            shutil.move(str(made), str(dest))
            f.unlink()
            results.append(dest)
    return results


def pdf_to_cad(src: Path, ext: str, outdir: Path, opt: Options) -> list[Path]:
    if ext == "dwg" and not find_oda_converter():
        raise ShiftError("err.needs_oda", url=ODA_DOWNLOAD)
    doc = open_pdf(src)
    try:
        n = doc.page_count
        if n == 1:
            folder = outdir
            names = [src.stem]
        else:
            folder = unique_dir(outdir / f"{src.stem} - {t('name.pages')}")
            folder.mkdir(parents=True)
            digits = len(str(n))
            names = [f"{src.stem} - {t('name.page')} {i:0{digits}d}" for i in range(1, n + 1)]
        made: list[Path] = []
        skipped = 0
        for page, name in zip(doc, names):
            dest = unique_path(folder / f"{name}.dxf")
            try:
                _page_to_dxf(page, dest, opt)
                made.append(dest)
            except ShiftError:
                if n == 1:
                    raise
                skipped += 1
        if not made:
            raise ShiftError("err.pdf_no_vectors")
    finally:
        doc.close()
    if ext == "dwg":
        made = dxf_to_dwg(made)
    return [folder] if n > 1 else made


# --------------------------------------------------------------------------
# Video and audio (ffmpeg)
# --------------------------------------------------------------------------
def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        path = shutil.which("ffmpeg")
        if path:
            return path
    raise ShiftError("err.ffmpeg_missing")


AUDIO_CODECS = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "flac": ["-c:a", "flac"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
}


def convert_media(src: Path, dest: Path, ext: str) -> None:
    args = [ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    if ext == "gif":
        args += ["-vf", "fps=12,scale='min(720,iw)':-2:flags=lanczos,"
                        "split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0"]
    elif ext in AUDIO_CODECS:
        args += ["-vn"] + AUDIO_CODECS[ext]
    elif ext in ("mp4", "mov", "mkv"):
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "160k"]
        if ext in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]
    elif ext == "webm":
        args += ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1",
                 "-c:a", "libopus", "-b:a", "128k"]
    elif ext == "avi":
        args += ["-c:v", "mpeg4", "-q:v", "3", "-c:a", "libmp3lame", "-q:a", "3"]
    args.append(str(dest))
    res = subprocess.run(args, capture_output=True, text=True, errors="replace",
                         creationflags=NO_WINDOW)
    if res.returncode != 0:
        if dest.exists():
            dest.unlink()
        lines = [line for line in res.stderr.strip().splitlines() if line.strip()]
        if lines:
            raise RuntimeError(lines[-1])
        raise ShiftError("err.media_failed")


# --------------------------------------------------------------------------
# Office documents (Microsoft Office, or LibreOffice as fallback)
# --------------------------------------------------------------------------
WORD_FORMATS = {"docx": 16, "doc": 0, "rtf": 6, "odt": 23, "html": 10}
EXCEL_FORMATS = {"xlsx": 51, "xls": 56, "ods": 60}
PPT_FORMATS = {"pdf": 32, "pptx": 24, "ppt": 1, "odp": 35, "jpg": 17, "png": 18}
LIBREOFFICE_FILTERS = {
    "txt": "txt:Text (encoded):UTF8",
    "csv": "csv:Text - txt - csv (StarCalc):59,34,76",
}


def find_soffice() -> str | None:
    candidates = [shutil.which("soffice"), shutil.which("soffice.exe")]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(os.path.join(base, "LibreOffice", "program", "soffice.exe"))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


class Office:
    """Keeps Word/Excel/PowerPoint open during a batch and closes them afterwards."""

    def __init__(self):
        self._apps: dict[str, object] = {}
        self._com = False

    def _app(self, name: str):
        if name in self._apps:
            return self._apps[name]
        import pythoncom
        import win32com.client
        if not self._com:
            pythoncom.CoInitialize()
            self._com = True
        app = win32com.client.DispatchEx(name)  # own instance: leaves open documents alone
        if name == "Word.Application":
            app.Visible = False
            app.DisplayAlerts = 0
        elif name == "Excel.Application":
            app.Visible = False
            app.DisplayAlerts = False
            app.ScreenUpdating = False
        elif name == "PowerPoint.Application":
            app.DisplayAlerts = 1  # ppAlertsNone
        self._apps[name] = app
        return app

    def close(self):
        for name, app in self._apps.items():
            try:
                if name == "PowerPoint.Application" and app.Presentations.Count > 0:
                    continue  # the user has presentations open
                app.Quit()
            except Exception:
                pass
        self._apps.clear()
        if self._com:
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:
                pass
            self._com = False

    def _document(self, src: Path, dest: Path, ext: str):
        app = self._app("Word.Application")
        d = app.Documents.Open(FileName=str(src), ConfirmConversions=False, ReadOnly=True,
                               AddToRecentFiles=False, Visible=False)
        try:
            if ext == "pdf":
                d.ExportAsFixedFormat(OutputFileName=str(dest), ExportFormat=17)
            elif ext == "txt":
                d.SaveAs2(FileName=str(dest), FileFormat=2, Encoding=65001)
            else:
                d.SaveAs2(FileName=str(dest), FileFormat=WORD_FORMATS[ext])
        finally:
            d.Close(SaveChanges=0)

    def _spreadsheet(self, src: Path, dest: Path, ext: str):
        app = self._app("Excel.Application")
        wb = app.Workbooks.Open(str(src), ReadOnly=True, Local=True)
        try:
            if ext == "pdf":
                wb.ExportAsFixedFormat(0, str(dest))
            elif ext == "csv":
                try:
                    wb.SaveAs(str(dest), FileFormat=62, Local=True)  # CSV UTF-8
                except Exception:
                    wb.SaveAs(str(dest), FileFormat=6, Local=True)
            else:
                wb.SaveAs(str(dest), FileFormat=EXCEL_FORMATS[ext], Local=True)
        finally:
            wb.Close(SaveChanges=False)

    def _presentation(self, src: Path, dest: Path, ext: str):
        app = self._app("PowerPoint.Application")
        p = app.Presentations.Open(str(src), ReadOnly=True, Untitled=False, WithWindow=False)
        try:
            p.SaveAs(str(dest), PPT_FORMATS[ext])  # jpg/png: PowerPoint creates a folder
        finally:
            p.Close()

    @staticmethod
    def _libreoffice(soffice: str, src: Path, dest: Path, ext: str):
        with tempfile.TemporaryDirectory(prefix="shift_lo_") as tmp:
            profile = Path(tmp, "profile").as_uri()
            out = Path(tmp, "out")
            out.mkdir()
            res = subprocess.run(
                [soffice, f"-env:UserInstallation={profile}", "--headless", "--norestore",
                 "--convert-to", LIBREOFFICE_FILTERS.get(ext, ext), "--outdir", str(out), str(src)],
                capture_output=True, text=True, errors="replace", timeout=600,
                creationflags=NO_WINDOW)
            result = list(out.glob("*"))
            if res.returncode != 0 or not result:
                raise ShiftError("err.libreoffice_failed")
            shutil.move(str(result[0]), str(dest))

    def convert(self, cat: str, src: Path, ext: str, outdir: Path) -> list[Path]:
        as_folder = cat == "presentation" and ext in ("jpg", "png")
        dest = (unique_dir(outdir / f"{src.stem} - {t('name.slides')}") if as_folder
                else unique_path(outdir / f"{src.stem}.{ext}"))
        error: Exception | None = None
        if sys.platform == "win32":
            try:
                getattr(self, "_" + cat)(src.resolve(), dest.resolve(), ext)
                return [dest]
            except Exception as e:
                error = e
        soffice = find_soffice()
        if soffice and not as_folder:
            self._libreoffice(soffice, src, dest, ext)
            return [dest]
        if error and not isinstance(error, ImportError) and "Invalid class string" not in str(error):
            raise ShiftError("err.office_failed", reason=error_message(error))
        raise ShiftError("err.needs_office")

    def pdf_to_word(self, src: Path, dest: Path):
        if sys.platform == "win32":
            try:
                self._document(src.resolve(), dest.resolve(), "docx")
                return
            except Exception:
                if dest.exists():
                    dest.unlink()
        pdf_to_word_without_office(src, dest)


# --------------------------------------------------------------------------
# One file
# --------------------------------------------------------------------------
def convert(src: Path, ext: str, outdir: Path, opt: Options, office: Office) -> list[Path]:
    cat = category(src)
    if cat is None:
        raise ShiftError("err.unsupported")
    if ext not in targets_for(src):
        raise ShiftError("err.not_available", fmt=ext.upper())
    outdir.mkdir(parents=True, exist_ok=True)

    if cat == "image":
        if ext == "pdf":
            dest = unique_path(outdir / f"{src.stem}.pdf")
            images_to_pdf([src], dest, opt)
        else:
            name = f"{src.stem} - {t('name.optimized')}" if ext == ext_of(src) else src.stem
            dest = unique_path(outdir / f"{name}.{ext}")
            save_image(open_image(src), dest, ext, opt)
        return [dest]

    if cat == "pdf":
        if ext in ("jpg", "png", "tiff"):
            return pdf_to_images(src, ext, outdir, opt)
        if ext == "pdf":
            return pdf_compress(src, outdir, Options(**{**opt.__dict__, "compress": "light"}))
        if ext in ("dxf", "dwg"):
            return pdf_to_cad(src, ext, outdir, opt)
        dest = unique_path(outdir / f"{src.stem}.{ext}")
        if ext == "txt":
            pdf_to_text(src, dest)
        else:
            office.pdf_to_word(src, dest)
        return [dest]

    if cat in ("document", "spreadsheet", "presentation"):
        return office.convert(cat, src, ext, outdir)

    if cat in ("video", "audio"):
        dest = unique_path(outdir / f"{src.stem}.{ext}")
        convert_media(src, dest, ext)
        return [dest]

    raise ShiftError("err.unknown_conversion")


def run(src: Path, action: str, outdir: Path, opt: Options, office: Office) -> list[Path]:
    """action is an output format ('pdf', 'jpg', ...) or a PDF tool ('tool:split', ...)."""
    if action.startswith("tool:"):
        if category(src) != "pdf":
            raise ShiftError("err.unsupported")
        outdir.mkdir(parents=True, exist_ok=True)
        tool = action[5:]
        return {"split": pdf_split, "rotate": pdf_rotate,
                "extract": pdf_extract, "compress": pdf_compress}[tool](src, outdir, opt)
    return convert(src, action, outdir, opt, office)
