"""Regole di rete "gentili": memoria dei limiti per sito, orari, batteria, quota di banda, scadenza dei link.

Tutto serve a scaricare veloce restando dentro i limiti che ogni sito accetta.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .logs import log


def data_dir() -> Path:
    from .plugins import user_templates_dir
    return user_templates_dir().parent


def site_of(url_or_host: str) -> str:
    host = (urlsplit(url_or_host).hostname if "://" in url_or_host else url_or_host) or ""
    parts = host.lower().split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# ---------------------------------------------------------------- 3 + 11: memoria dei limiti per server
class SiteMemory:
    """Quante connessioni ogni server ha accettato l'ultima volta (file JSON nella cartella dati)."""

    def __init__(self, path: Path | None = None):
        self.path = path or (data_dir() / "limiti_siti.json")
        try:
            self.data: dict = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, host: str) -> int | None:
        v = self.data.get(host)
        return int(v["limit"]) if isinstance(v, dict) and v.get("limit") else None

    def set(self, host: str, limit: int, throttled: bool = False):
        cur = self.data.get(host) or {}
        cur.update({"limit": int(limit), "ts": time.time()})
        if throttled:
            cur["throttled"] = cur.get("throttled", 0) + 1
            cur["last_throttle"] = time.time()
        self.data[host] = cur

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as e:
            log.debug("limiti dei siti non salvati: %s", e)


# ---------------------------------------------------------------- 9: orari e batteria
def on_battery() -> bool:
    """True se il computer va a batteria (Mac e Linux; su Windows sempre False)."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
            return "Battery Power" in out
        if sys.platform.startswith("linux"):
            for p in Path("/sys/class/power_supply").glob("*"):
                t = (p / "type").read_text().strip() if (p / "type").exists() else ""
                if t == "Mains" and (p / "online").exists():
                    return (p / "online").read_text().strip() == "0"
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def _minutes(hhmm: str) -> int:
    try:
        h, m = (hhmm or "0:0").split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return 0


class Schedule:
    """Quando si può scaricare: fascia oraria (anche a cavallo della mezzanotte) e niente batteria."""

    def __init__(self, enabled: bool = False, start: str = "01:00", end: str = "07:00",
                 pause_on_battery: bool = False):
        self.enabled, self.start, self.end = enabled, start, end
        self.pause_on_battery = pause_on_battery
        self._batt = (0.0, False)

    def _battery(self) -> bool:
        t, v = self._batt
        if time.monotonic() - t > 30:
            v = on_battery()
            self._batt = (time.monotonic(), v)
        return v

    def blocked(self, now: time.struct_time | None = None) -> str | None:
        """Motivo per cui ora non si scarica, oppure None."""
        if self.enabled:
            now = now or time.localtime()
            m = now.tm_hour * 60 + now.tm_min
            a, b = _minutes(self.start), _minutes(self.end)
            inside = (a <= m < b) if a < b else (m >= a or m < b)
            if a != b and not inside:
                return f"fuori dall'orario dei download ({self.start}–{self.end})"
        if self.pause_on_battery and self._battery():
            return "il computer va a batteria"
        return None


# ---------------------------------------------------------------- 14: link firmati che scadono
def link_expiry(url: str) -> float | None:
    """Quando scade un link firmato (secondi epoch), se lo dice il link stesso."""
    q = {k.lower(): v[0] for k, v in parse_qs(urlsplit(url).query).items() if v}
    pol = q.get("policy")
    if pol:
        import base64
        raw = pol.replace("-", "+").replace("_", "=").replace("~", "/")
        try:
            data = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
            for st in data.get("Statement", []):
                t = ((st.get("Condition") or {}).get("DateLessThan") or {}).get("AWS:EpochTime")
                if t:
                    return float(t)
        except (ValueError, TypeError, AttributeError):
            pass
    if "x-amz-date" in q and "x-amz-expires" in q:
        try:
            import calendar
            start = calendar.timegm(time.strptime(q["x-amz-date"], "%Y%m%dT%H%M%SZ"))
            return start + float(q["x-amz-expires"])
        except (ValueError, OverflowError):
            pass
    for k in ("expires", "exp", "e"):
        v = q.get(k)
        if v and v.isdigit() and 1_000_000_000 < int(v) < 10_000_000_000:
            return float(v)
    return None


def expired(url: str, margin: float = 60) -> bool:
    t = link_expiry(url)
    return t is not None and t < time.time() + margin


# ---------------------------------------------------------------- 15: impronta delle immagini
def image_hash(path: str | os.PathLike) -> int | None:
    """dHash a 64 bit: due foto uguali (anche ridimensionate o ricompresse) hanno impronte vicine."""
    try:
        from PySide6.QtGui import QImage
        from PySide6.QtCore import Qt
    except ImportError:
        return None
    img = QImage(str(path))
    if img.isNull():
        return None
    small = img.convertToFormat(QImage.Format_Grayscale8).scaled(9, 8, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if small.pixelColor(x, y).value() > small.pixelColor(x + 1, y).value() else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------- 6: copia delle pagine (ETag / Last-Modified)
class PageCache:
    """Con «Aggiorna» una pagina non cambiata costa una risposta 304 vuota invece della pagina intera."""

    MAX_BODY = 3 * 1024 * 1024
    MAX_ROWS = 3000

    def __init__(self, path: Path | None = None):
        import sqlite3
        import threading
        self.path = path or (data_dir() / "pagine.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.execute("CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, etag TEXT, lastmod TEXT, "
                        "ctype TEXT, body TEXT, ts REAL)")
        self.lock = threading.Lock()

    def get(self, url: str):
        with self.lock:
            return self.db.execute("SELECT etag, lastmod, ctype, body FROM pages WHERE url = ?", (url,)).fetchone()

    def validators(self, url: str) -> dict:
        row = self.get(url)
        if not row:
            return {}
        etag, lastmod = row[0], row[1]
        out = {}
        if etag:
            out["If-None-Match"] = etag
        if lastmod:
            out["If-Modified-Since"] = lastmod
        return out

    def put(self, url: str, etag: str | None, lastmod: str | None, ctype: str, body: str):
        if not (etag or lastmod) or len(body) > self.MAX_BODY:
            return
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?,?,?)",
                            (url, etag, lastmod, ctype, body, time.time()))
            n = self.db.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            if n > self.MAX_ROWS:
                self.db.execute("DELETE FROM pages WHERE url IN (SELECT url FROM pages ORDER BY ts LIMIT ?)",
                                (n - self.MAX_ROWS,))


_PAGE_CACHE: PageCache | None = None


def page_cache() -> PageCache | None:
    global _PAGE_CACHE
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    if _PAGE_CACHE is None:
        try:
            _PAGE_CACHE = PageCache()
        except Exception as e:  # noqa: BLE001
            log.debug("copia delle pagine non disponibile: %s", e)
            return None
    return _PAGE_CACHE
