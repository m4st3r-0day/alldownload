"""Dopo il download: nome a modello, data giusta, didascalia, controllo che il file sia intero.

Tutto senza librerie in più: i controlli leggono solo la fine (o la struttura) del file.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

# ---------------------------------------------------------------- date e didascalie nei JSON
DATE_KEYS = ("postedAt", "createdAt", "created_at", "publishedAt", "published_at", "uploadedAt", "uploaded_at",
             "date", "timestamp", "created", "posted_at", "upload_date")
CAPTION_KEYS = ("rawText", "text", "caption", "description", "content", "body")
LINK_KEYS = ("link", "url", "download", "downloadUrl", "download_url", "src", "file", "directLink", "source")


def parse_date(v) -> float | None:
    """Epoch (secondi o millisecondi), ISO 8601 o data HTTP → secondi. None se non si capisce."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
        if x > 1e12:                     # millisecondi
            x /= 1000
        return x if 9.4e8 < x < 4.1e9 else None      # 2000 … 2100
    s = str(v).strip()
    if not s:
        return None
    if re.fullmatch(r"\d{9,13}(\.\d+)?", s):
        return parse_date(float(s))
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return parse_date(d.timestamp())
    except ValueError:
        pass
    try:
        return parse_date(parsedate_to_datetime(s).timestamp())
    except (TypeError, ValueError, IndexError):
        return None


def _clean_caption(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    return s.strip()


def json_meta(text: str) -> dict[str, dict]:
    """In un JSON: {link del file: {"date": secondi, "caption": testo}}.
    Data e didascalia passano dal «post» ai file che contiene (es. post → media → files → full → url)."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    out: dict[str, dict] = {}

    def walk(o, ctx: dict, depth=0):
        if depth > 14:
            return
        if isinstance(o, dict):
            ctx = dict(ctx)
            for k in DATE_KEYS:
                d = parse_date(o.get(k))
                if d:
                    ctx["date"] = d
                    break
            for k in CAPTION_KEYS:
                c = o.get(k)
                if isinstance(c, str) and c.strip() and not c.startswith("http"):
                    ctx["caption"] = _clean_caption(c)[:5000]
                    break
            if ctx:
                for k in LINK_KEYS:
                    u = o.get(k)
                    if isinstance(u, str) and u.startswith("http"):
                        out.setdefault(u, dict(ctx))
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v, ctx, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, ctx, depth + 1)
    walk(data, {})
    return out


# ---------------------------------------------------------------- nome a modello
TOKENS = ("{nome}", "{ext}", "{sito}", "{profilo}", "{data}", "{ora}", "{n}", "{id}")
EXAMPLE_PATTERN = "{profilo}_{data}_{n}"


def render_name(pattern: str, original: str, url: str, counter: int, owner: str = "",
                when: float | None = None) -> str:
    """«{profilo}_{data}_{n}» → «mario_2026-03-14_0007.jpg». L'estensione resta sempre quella vera."""
    stem, dot, ext = original.rpartition(".")
    if not dot:
        stem, ext = original, ""
    t = time.localtime(when if when else time.time())
    host = (urlsplit(url).hostname or "").lower()
    parts = host.split(".")
    site = parts[-2] if len(parts) >= 2 else host
    vals = {
        "nome": stem, "ext": ext, "sito": site, "profilo": owner or site,
        "data": time.strftime("%Y-%m-%d", t), "ora": time.strftime("%H-%M-%S", t),
        "n": f"{counter:04d}", "id": hashlib.sha1(url.encode()).hexdigest()[:8],
    }
    name = pattern
    for k, v in vals.items():
        name = name.replace("{" + k + "}", v)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name).strip(" .") or stem
    if ext and not name.lower().endswith("." + ext.lower()):
        name += "." + ext
    return name[:200]


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suf = p.stem, p.suffix
    for i in range(2, 10000):
        q = p.with_name(f"{stem} ({i}){suf}")
        if not q.exists():
            return q
    return p


def finalize(path: Path, url: str, meta: dict, *, pattern: str = "", counter: int = 0, owner: str = "",
             set_dates: bool = True, captions: bool = False) -> Path:
    """Rinomina col modello, mette la data del post (o quella del server) e salva la didascalia."""
    when = meta.get("date") or parse_date(meta.get("last_modified"))
    if pattern.strip():
        new = path.with_name(render_name(pattern, path.name, url, counter, owner, when))
        if new != path:
            new = unique_path(new)
            path.replace(new)
            path = new
    if set_dates and when:
        try:
            os.utime(path, (when, when))
        except OSError:
            pass
    if captions and meta.get("caption"):
        cap = path.with_suffix(path.suffix + ".txt")
        try:
            cap.write_text(meta["caption"] + "\n", encoding="utf-8")
            if set_dates and when:
                os.utime(cap, (when, when))
        except OSError:
            pass
    return path


# ---------------------------------------------------------------- file interi?
MEDIA_EXT = {".jpg", ".jpeg", ".jfif", ".png", ".gif", ".webp", ".avif", ".mp4", ".m4v", ".mov", ".webm",
             ".mkv", ".avi", ".zip", ".rar", ".7z", ".mp3", ".m4a"}


def _tail(f, n: int) -> bytes:
    f.seek(0, os.SEEK_END)
    size = f.tell()
    f.seek(max(0, size - n))
    return f.read()


def check_file(path: Path, ext: str | None = None) -> tuple[bool, str]:
    """(True, "") se il file sembra intero. Controlla JPEG, PNG, GIF, WebP, MP4/MOV/M4V. Gli altri: ok.
    ext: estensione vera (utile se il file si chiama ancora «.part»)."""
    try:
        size = path.stat().st_size
        if size == 0:
            return False, "file vuoto"
        ext = (ext or path.suffix).lower()
        with open(path, "rb") as f:
            head = f.read(512)
            # si decide dal contenuto, non dal nome: molti siti mandano WebP chiamati .jpg
            if head[:3] == b"\xff\xd8\xff":
                if b"\xff\xd9" not in _tail(f, 4096):
                    return False, "JPEG troncato (manca la fine)"
            elif head[:8] == b"\x89PNG\r\n\x1a\n":
                if b"IEND" not in _tail(f, 64):
                    return False, "PNG troncato (manca la fine)"
            elif head[:4] == b"GIF8":
                if not _tail(f, 16).rstrip(b"\x00").endswith(b";"):
                    return False, "GIF troncata"
            elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                if int.from_bytes(head[4:8], "little") + 8 > size:
                    return False, "WebP troncato"
            elif head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide", b"skip"):
                return _check_mp4(f, size)
            elif ext in MEDIA_EXT and re.match(rb"\s*(<!doctype html|<html|<head|<!--)", head, re.I):
                return False, "il server ha mandato una pagina web invece del file"
    except OSError as e:
        return False, f"non si legge: {e}"
    return True, ""


def _check_mp4(f, size: int) -> tuple[bool, str]:
    pos, boxes = 0, []
    f.seek(0)
    while pos < size and len(boxes) < 10000:
        f.seek(pos)
        h = f.read(16)
        if len(h) < 8:
            break
        n = int.from_bytes(h[:4], "big")
        kind = h[4:8]
        if n == 1 and len(h) >= 16:
            n = int.from_bytes(h[8:16], "big")
        elif n == 0:
            n = size - pos
        if n < 8 or not re.fullmatch(rb"[A-Za-z0-9 \xa9_-]{4}", kind):
            return False, "video rovinato (struttura MP4 non valida)"
        boxes.append(kind)
        pos += n
    if pos > size:
        return False, "video troncato (manca la fine)"
    if b"moov" not in boxes:
        return False, "video incompleto (manca l'indice «moov»)"
    return True, ""


# ---------------------------------------------------------------- spazio su disco
def free_bytes(folder: Path) -> int | None:
    p = Path(folder)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None
