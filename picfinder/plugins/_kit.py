"""Attrezzi comuni ai plugin Python dei siti (codice nostro, niente template di EPF).

- `Crawl`: richieste con pausa per server, risposte già pronte dal browser interno, registro.
- intestazioni copiate dalle richieste del browser (token, firme) come «CopyFromParent» dei template.
- piccoli aiuti: nome pulito, titolo della pagina, nome del file dall'indirizzo.

Un plugin è un modulo con:
    NAME, match(url) -> bool, async list_files(client, url, password=None[, session=None])
e, se servono:
    PREFERRED = True        passa davanti ai template .etmpl dello stesso sito
    ACCEPTS_SESSION = True  riceve la sessione del browser interno
    NEEDS_BROWSER = True    apre il browser interno prima di cercare
    BROWSER_MESSAGE = "…"   testo mostrato sopra il browser
    BROWSER_USEFUL = r"…"   quali richieste del browser servono (regex)
    TESTED = "2026-11"      provato davvero sul sito
    DELAY = (min, max)      pausa tra due pagine dello stesso server, in secondi
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import random
import re
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import httpx

from ..core import PluginError
from ..logs import log, short


def clean_name(name: str, limit: int = 120) -> str:
    """Nome usabile come cartella o file su Mac e Windows."""
    name = _html.unescape(name or "")
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name)
    return re.sub(r"\s+", " ", name).strip(" .-")[:limit]


def name_from_url(url: str) -> str:
    q = re.search(r"[?&]n=([^&#]+)", url)
    if q:
        n = unquote(q.group(1))
        if "." in n and "/" not in n:
            return clean_name(n, 200)
    return clean_name(unquote(urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]), 200) or "file"


def page_title(html: str, url: str) -> str:
    from ..etmpl import page_title as _pt
    return _pt(html, url)


@dataclass
class Page:
    url: str
    status: int
    text: str
    ctype: str = ""
    from_browser: bool = False

    def json(self):
        try:
            return json.loads(self.text)
        except ValueError as e:
            raise PluginError(f"Risposta non valida da {short(self.url)}") from e


class Crawl:
    """Fa le richieste di un plugin come le farebbe il browser, con calma e senza ripetersi."""

    def __init__(self, client: httpx.AsyncClient, session=None, delay: tuple[float, float] = (0.0, 0.0),
                 pause_scale: float = 1.0):
        self.client = client
        self.session = session
        lo, hi = delay
        if pause_scale != 1.0 and (lo or hi):
            lo, hi = max(0.3, lo * pause_scale), max(0.6, hi * pause_scale)
        self.delay = (lo, hi)
        self.cache = session.cached() if session is not None else {}
        self.last: dict[str, float] = {}
        self.pages = 0

    # ---------------- intestazioni dal browser
    def captured(self, url_regex: str) -> list:
        rx = re.compile(url_regex, re.I)
        return [r for r in (getattr(self.session, "requests", None) or []) if rx.search(r.url)]

    def copy_headers(self, url_regex: str, names: tuple[str, ...]) -> dict:
        """Intestazioni (token, firme) dell'ultima richiesta del browser che corrisponde."""
        out = {}
        if self.session is None:
            return out
        for n in names:
            v = self.session.header_for(url_regex, n)
            if v:
                out[n] = v
        return out

    # ---------------- richieste
    async def _wait(self, host: str):
        lo, hi = self.delay
        if hi <= 0 or host not in self.last:
            return
        wait = random.uniform(lo, hi) - (time.monotonic() - self.last[host])
        if wait > 0.05:
            log.debug("  attesa %.1f s (pausa per %s)", wait, host)
            await asyncio.sleep(wait)

    async def fetch(self, url: str, method: str = "GET", *, json_body=None, data: str | None = None,
                    headers: dict | None = None, referer: str | None = None, ok=(200,)) -> Page:
        body = json.dumps(json_body, separators=(",", ":")) if json_body is not None else data
        hit = self.cache.get((method, url, body if method != "GET" else None))
        if hit is not None:
            self.pages += 1
            log.info("Pagina %s → %s, %s (dal browser)", short(url), hit.status or 200, hit.ctype or "?")
            return Page(url, hit.status or 200, hit.text or "", hit.ctype, True)
        host = (urlsplit(url).hostname or "").lower()
        await self._wait(host)
        h = dict(headers or {})
        if referer:
            h.setdefault("Referer", referer)
        if json_body is not None:
            h.setdefault("Content-Type", "application/json")
        t0 = time.monotonic()
        log.debug("→ %s %s%s", method, short(url), f"  dati: {body[:120]}" if body else "")
        try:
            r = await self.client.request(method, url, content=body.encode() if body else None, headers=h)
        except httpx.HTTPError as e:
            raise PluginError(f"{short(url)}: {type(e).__name__}") from e
        finally:
            self.last[host] = time.monotonic()
        self.pages += 1
        ctype = r.headers.get("content-type", "").split(";")[0]
        log.info("Pagina %s → %d, %s, %.1f KB, %d ms", short(url), r.status_code, ctype or "?",
                 len(r.content) / 1024, (time.monotonic() - t0) * 1000)
        if r.status_code not in ok:
            if r.status_code in (401, 403):
                raise PluginError(f"{short(url)}: accesso negato ({r.status_code}). Serve il login o il link è privato.")
            if r.status_code == 404:
                raise PluginError(f"{short(url)}: non trovato (404). Il link è scaduto o sbagliato.")
            if r.status_code == 429:
                raise PluginError(f"{short(url)}: troppe richieste (429). Riprova tra poco o allunga le pause.")
            raise PluginError(f"{short(url)}: il sito risponde {r.status_code}")
        return Page(str(r.url), r.status_code, r.text, ctype)


def kit_for(plugin_module, client, session=None) -> Crawl:
    """Crawl con la pausa del plugin e la scala scelta nelle Impostazioni («Pause tra un file e l'altro»)."""
    return Crawl(client, session, getattr(plugin_module, "DELAY", (0.0, 0.0)),
                 float(getattr(plugin_module, "pause_scale", 1.0) or 1.0))
