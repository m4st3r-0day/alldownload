"""Lista di proxy (tuoi): prova, ordine per velocità, cambio automatico quando un proxy non risponde.

Il cambio scatta solo per problemi del PROXY (spento, irraggiungibile, rifiuta la connessione).
Se è il SITO a rispondere 403/429, non si cambia proxy: il Downloader rallenta e rispetta il limite.
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable

import httpx
from urllib.parse import quote

from .logs import log
from .settings import ProxyEntry

Tester = Callable[[str, str, float], Awaitable[float]]   # (proxy, url, timeout) -> millisecondi


async def default_tester(proxy: str, url: str, timeout: float) -> float:
    t0 = time.monotonic()
    async with httpx.AsyncClient(proxy=proxy, timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url)
        if r.status_code >= 500:
            raise httpx.HTTPStatusError(f"risposta {r.status_code}", request=r.request, response=r)
    return (time.monotonic() - t0) * 1000


def mask(url: str) -> str:
    """Nasconde la password del proxy nel registro."""
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        creds, host = rest.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return url


LIST_NAME = "da lista"


def parse_proxy_line(line: str, scheme: str = "http") -> str | None:
    """Una riga di lista → indirizzo proxy. Capisce:
    ip:porta · ip:porta:utente:password (Webshare e simili) · utente:password@ip:porta · schema://..."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        return line
    parts = line.split(":")
    if len(parts) >= 4 and parts[1].isdigit():
        host, port, user = parts[0], parts[1], parts[2]
        pwd = ":".join(parts[3:])
        return f"{scheme}://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:{port}"
    if "@" in line:
        return f"{scheme}://{line}"
    if len(parts) == 2:
        return f"{scheme}://{parts[0]}:{parts[1]}"
    if len(parts) >= 4:
        host, port, user = parts[0], parts[1], parts[2]
        pwd = ":".join(parts[3:])
        return f"{scheme}://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:{port}"
    return None


def mask_link(url: str) -> str:
    """Il link della lista contiene una chiave segreta: nel registro solo il sito."""
    from urllib.parse import urlsplit
    return f"{urlsplit(url).scheme}://{urlsplit(url).hostname}/…"


def fetch_list(url: str, timeout: float = 20.0) -> list[str]:
    """Scarica una lista di proxy (es. il link «download» di Webshare): un proxy per riga."""
    from .core import USER_AGENT
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT, "Accept": "text/plain,*/*"})
    except httpx.HTTPError as e:                      # il messaggio di httpx contiene il link con la chiave
        raise RuntimeError(f"{e.__class__.__name__} su {mask_link(url)}") from None
    if r.status_code >= 400:
        raise RuntimeError(f"risposta {r.status_code} da {mask_link(url)}: {r.text.strip()[:120]}")
    out: list[str] = []
    for line in r.text.splitlines():
        p = parse_proxy_line(line)
        if p and p not in out:
            out.append(p)
    log.info("Lista proxy %s: %d proxy", mask_link(url), len(out))
    return out


def apply_list(entries: list[ProxyEntry], urls: list[str]) -> list[ProxyEntry]:
    """Sostituisce i proxy presi dalla lista; quelli aggiunti a mano restano."""
    keep = [e for e in entries if e.name != LIST_NAME]
    have = {e.url for e in keep}
    return keep + [ProxyEntry(u, name=LIST_NAME) for u in urls if u not in have]


class ProxyPool:
    def __init__(self, entries: list[ProxyEntry], mode: str = "fastest",
                 test_url: str = "https://www.gstatic.com/generate_204", tester: Tester | None = None):
        self.entries = [e for e in entries if e.enabled and e.url.strip()]
        self.mode = mode
        self.test_url = test_url
        self.tester = tester or default_tester
        self.dead: set[str] = set()
        self.current: str | None = None
        self.tested = False

    def __bool__(self):
        return bool(self.entries) and self.mode != "off"

    async def test_all(self, timeout: float = 6.0) -> list[ProxyEntry]:
        async def one(e: ProxyEntry):
            try:
                e.latency_ms = round(await self.tester(e.url, self.test_url, timeout), 1)
                e.ok, e.last_error = True, ""
                log.info("Proxy %s: ok, %.0f ms", mask(e.url), e.latency_ms)
            except Exception as ex:  # noqa: BLE001
                e.ok, e.latency_ms, e.last_error = False, None, str(ex) or ex.__class__.__name__
                log.warning("Proxy %s: non risponde (%s)", mask(e.url), e.last_error)
        await asyncio.gather(*(one(e) for e in self.entries))
        self.tested = True
        return self.entries

    def ordered(self) -> list[str]:
        alive = [e for e in self.entries if e.url not in self.dead and e.ok is not False]
        if self.mode == "fastest":
            alive.sort(key=lambda e: (e.latency_ms is None, e.latency_ms or 0))
        return [e.url for e in alive]

    async def choose(self) -> str | None:
        """Sceglie il proxy da usare (prova tutti la prima volta)."""
        if not self:
            return None
        if not self.tested:
            await self.test_all()
        order = self.ordered()
        self.current = order[0] if order else None
        if self.current:
            e = next(x for x in self.entries if x.url == self.current)
            log.info("Uso il proxy %s%s", mask(self.current),
                     f" ({e.latency_ms:.0f} ms, il più veloce)" if self.mode == "fastest" and e.latency_ms else "")
        else:
            log.error("Nessun proxy della lista risponde: continuo SENZA proxy")
        return self.current

    def mark_dead(self, url: str | None, reason: str = "") -> str | None:
        """Il proxy `url` non risponde: passa al prossimo. Restituisce il nuovo proxy (o None)."""
        if url:
            self.dead.add(url)
            for e in self.entries:
                if e.url == url:
                    e.ok, e.last_error = False, reason
            log.warning("Proxy %s non risponde (%s): passo al prossimo", mask(url), reason)
        order = self.ordered()
        self.current = order[0] if order else None
        if self.current:
            log.info("Ora uso il proxy %s", mask(self.current))
        else:
            log.error("Nessun altro proxy disponibile: continuo SENZA proxy")
        return self.current


def is_proxy_failure(e: BaseException) -> bool:
    """Errore del proxy (non del sito)."""
    return isinstance(e, (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout))
