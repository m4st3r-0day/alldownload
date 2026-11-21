"""Motore di download: trova il plugin giusto, elenca i file, li scarica in parallelo."""
from __future__ import annotations

import asyncio
import fnmatch
from contextlib import asynccontextmanager
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

import httpx

from .logs import log, short
from .postproc import check_file, finalize, free_bytes

# Stessi filtri del template EPF (sezione [TargetFiles])
DEFAULT_PATTERNS = [
    "*.jp*", "*.pn*", "*.gif", "*.webp", "*.heic",
    "*.mp4", "*.avi", "*.m4v", "*.mpg", "*.mpeg", "*.mov",
]

import sys as _sys

# Ci presentiamo come un normale Chrome: molti siti bloccano i programmi con nomi strani.
_UA_OS = {"darwin": "Macintosh; Intel Mac OS X 10_15_7", "win32": "Windows NT 10.0; Win64; x64"}.get(
    _sys.platform, "X11; Linux x86_64")
USER_AGENT = (f"Mozilla/5.0 ({_UA_OS}) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/142.0.0.0 Safari/537.36")
BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
}


SEGMENT_MIN = 40 * 1024 * 1024        # sotto questa grandezza un pezzo solo

try:
    import h2  # noqa: F401
    HAS_H2 = True
except ImportError:
    HAS_H2 = False


@dataclass
class RemoteFile:
    url: str
    name: str
    subdir: str = ""          # sottocartella relativa (es. "Vacanze/2024")
    size: int | None = None
    headers: dict = field(default_factory=dict)
    fixed_name: bool = False  # nome deciso dal template: non usare Content-Disposition
    opts: dict | None = None  # opzioni del template che l'ha trovato (ritardi, conflitti, ...)
    thumb: str = ""           # indirizzo di una miniatura offerta dal sito (per l'anteprima)
    meta: dict = field(default_factory=dict)   # data del post, didascalia, Last-Modified del server


class PluginError(Exception):
    """Errore leggibile da mostrare all'utente (password errata, link scaduto...)."""


Event = Callable[[str, dict], None]


def matches(name: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    low = name.lower()
    return any(fnmatch.fnmatch(low, p.lower()) for p in patterns)


def safe_part(part: str) -> str:
    """Nome valido su Windows, Mac e Linux."""
    bad = '<>:"\\|?*'
    cleaned = "".join("_" if c in bad or ord(c) < 32 else c for c in part).strip(" .")
    return cleaned or "_"


class Downloader:
    def __init__(
        self,
        dest: str | Path,
        patterns: list[str] | None = DEFAULT_PATTERNS,
        concurrency: int = 4,
        retries: int = 3,
        on_event: Event | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        proxy: str | None = None,
        per_host: int = 2,
        timeout: float = 30,
        speed_limit_kbps: int = 0,
        default_conflicts: str = "same_size",
        proxy_pool=None,
        user_agent: str | None = None,
        preview_max_mb: int = 15,
        ffmpeg_path: str | None = None,
        folder_per_link: bool = False,
        split_by_type: bool = False,
        pause_scale: float = 1.0,
        history=None,
        adaptive: bool = True,
        site_memory=None,
        segments: int = 4,
        schedule=None,
        bandwidth_share: int = 0,
        warn_requests: int = 0,
        dup_images: str = "off",
        http2: bool = True,
        skip_known: bool = True,
    ):
        self.dest = Path(dest)
        self.patterns = patterns
        self.concurrency = concurrency
        self.retries = retries
        self.on_event = on_event or (lambda kind, data: None)
        self.transport = transport  # usato nei test per simulare i siti
        self.sync_transport = transport if isinstance(transport, httpx.BaseTransport) else None
        self.opts: dict = {}
        self.proxy = (proxy or "").strip() or None
        self.per_host = per_host
        self.timeout = timeout
        self.default_conflicts = default_conflicts
        self.pool = proxy_pool
        self._custom_ua = bool((user_agent or "").strip())
        self.user_agent = (user_agent or "").strip() or USER_AGENT
        self.preview_max = preview_max_mb * 1024 * 1024
        self.ffmpeg_path = ffmpeg_path or None
        self.folder_per_link = folder_per_link
        self.split_by_type = split_by_type
        self.pause_scale = pause_scale
        self.history = history          # file già scaricati in passato (chiave → percorso)
        self.name_pattern = ""          # 9: es. «{profilo}_{data}_{n}» (vuoto = nome originale)
        self.file_dates = True          # 10: data del post (o del server) sul file
        self.save_captions = False      # 10: didascalia in «file.jpg.txt»
        self.verify_files = True        # 12: controlla che immagini e video siano interi
        self.reserve_mb = 500           # 11: sotto questo spazio libero ci si ferma
        self._name_counter = 0
        self.adaptive = adaptive        # connessioni per server che crescono piano e scendono ai 429
        self.site_memory = site_memory  # limiti ricordati per ogni server
        self.segments = max(1, segments)  # pezzi in parallelo per i file grandi
        self.schedule = schedule        # orari / batteria
        self.warn_requests = warn_requests  # avviso dopo N richieste al giorno verso lo stesso sito
        self.dup_images = dup_images    # off | mark | move: foto uguali già scaricate
        self.http2 = http2
        self.skip_known = skip_known    # con history: salta i file già scaricati in passato
        self._limiter = SpeedLimiter(speed_limit_kbps, bandwidth_share)
        self._req_counts: dict[str, int] = {}
        self._req_warned: set[str] = set()
        self._req_base: dict[str, int] = {}
        self._pausing = False
        self._client_obj: httpx.AsyncClient | None = None
        self._direct_obj: httpx.AsyncClient | None = None
        self.ip_failed: list = []
        self.sessions: dict = {}   # link -> BrowserSession (cookie del browser interno)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._found_offset = 0
        self._stop = False

    def stop(self) -> None:
        """Ferma subito ricerca o download, anche durante un'attesa o una richiesta lenta."""
        self._stop = True
        loop, task = self._loop, self._task
        if loop and task and not task.done():
            log.info("Interruzione richiesta")
            loop.call_soon_threadsafe(task.cancel)

    def _arm(self):
        """Ricorda il task in corso, così stop() lo può cancellare da un altro thread."""
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()

    def _check_proxy(self):
        if self.proxy and self.proxy.lower().startswith("socks"):
            try:
                import socksio  # noqa: F401
            except ImportError:
                raise PluginError("Per i proxy SOCKS serve il pacchetto socksio: pip install \"httpx[socks]\"") from None

    def _cookies(self) -> httpx.Cookies:
        jar = httpx.Cookies()
        for s in self.sessions.values():
            for c in s.cookies:
                jar.set(c.name, c.value, domain=c.domain.lstrip(".") if c.domain else "", path=c.path or "/")
        return jar

    def cookie_header(self, url: str) -> str:
        """Cookie del browser interno validi per questo indirizzo (per ffmpeg)."""
        host = (urlsplit(url).hostname or "").lower()
        out = {}
        for s in self.sessions.values():
            for c in s.cookies:
                d = (c.domain or "").lstrip(".").lower()
                if d and (host == d or host.endswith("." + d)):
                    out[c.name] = c.value
        return "; ".join(f"{k}={v}" for k, v in out.items())

    def _client(self, direct: bool = False) -> httpx.AsyncClient:
        self._check_proxy()
        return httpx.AsyncClient(
            cookies=self._cookies(),
            transport=self.transport,
            http2=bool(self.http2 and HAS_H2 and not self.transport),
            event_hooks={"request": [self._count_request]},
            proxy=None if self.transport else ((None if direct else self.proxy) or self._sys_proxy()),
            trust_env=False,
            headers={**BROWSER_HEADERS, "User-Agent": self.user_agent},
            follow_redirects=True,
            timeout=httpx.Timeout(float(self.timeout), read=max(120.0, float(self.timeout))),
        )

    async def _count_request(self, request: httpx.Request):
        """12: conta le richieste per sito e avvisa prima di arrivare a un limite."""
        from .netpolicy import site_of
        site = site_of(request.url.host or "")
        self._req_counts[site] = self._req_counts.get(site, 0) + 1
        if not self.warn_requests or site in self._req_warned:
            return
        if site not in self._req_base:
            self._req_base[site] = self.history.requests_today(site) if self.history is not None else 0
        total = self._req_base[site] + self._req_counts[site]
        if total >= self.warn_requests:
            self._req_warned.add(site)
            msg = (f"Oggi hai già fatto {total} richieste a {site}: molti siti hanno un limite giornaliero. "
                   "Forse è meglio continuare domani.")
            log.warning(msg)
            self.on_event("warning", {"message": msg})

    def flush_counters(self):
        if self.history is not None and self._req_counts:
            for site, n in self._req_counts.items():
                self.history.add_requests(site, n)
                self._req_base[site] = self._req_base.get(site, 0) + n
        self._req_counts = {}

    def pause(self) -> None:
        """7: come stop(), ma tiene i pezzi già scaricati (.part) per riprendere dopo."""
        self._pausing = True
        self.stop()

    def _sys_proxy(self) -> str | None:
        if not hasattr(self, "_sysp"):
            self._sysp = system_proxy()
            if self._sysp:
                from .proxies import mask
                log.info("Proxy di sistema attivo (come il browser interno): %s", mask(self._sysp))
        return self._sysp

    async def _my_ip(self, client) -> str | None:
        if not hasattr(self, "_ip_seen"):
            self._ip_seen = None
            for u in ("https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me/ip"):
                try:
                    r = await client.get(u, timeout=8)
                    if r.status_code == 200 and r.text.strip():
                        self._ip_seen = r.text.strip()[:45]
                        break
                except httpx.HTTPError:
                    continue
        return self._ip_seen

    async def _use_pool(self):
        """Se c'è una lista di proxy, sceglie il più veloce che funziona."""
        if self.pool:
            self.proxy = await self.pool.choose()

    async def _switch_proxy(self, err: BaseException) -> bool:
        """Il proxy attuale non risponde: passa al prossimo e ricrea la connessione."""
        if not self.pool or not self.proxy:
            return False
        from .proxies import is_proxy_failure
        if not is_proxy_failure(err):
            return False
        old_proxy, old_client = self.proxy, self._client_obj
        self.proxy = self.pool.mark_dead(old_proxy, str(err) or err.__class__.__name__)
        if self.proxy == old_proxy:
            return False
        self._client_obj = self._client()
        if old_client is not None:
            asyncio.get_running_loop().create_task(old_client.aclose())
        return True

    async def scan(self, url: str, password: str | None = None, plugin=None, session=None) -> list[RemoteFile]:
        """Fase 1: trova i file senza scaricarli."""
        from .plugins import find_plugin

        plugin = plugin or find_plugin(url)
        if plugin is None:
            raise PluginError(f"Nessun template riconosce questo link: {url}")
        self.on_event("plugin", {"name": plugin.NAME})
        log.info("Cerco in %s con «%s»", short(url), plugin.NAME)
        if hasattr(plugin, "on_event"):
            plugin.on_event = self.on_event
        self.opts = dict(getattr(plugin, "options", {}) or {})

        # I template .etmpl hanno già il loro filtro ([TargetFiles])
        patterns = None if getattr(plugin, "OWN_FILTER", False) else self.patterns
        files: list[RemoteFile] = []
        mirrors: set[str] = set()
        if self._task is not asyncio.current_task():
            self._arm()
        if self.proxy:
            from .proxies import mask
            log.info("Uso il proxy %s", mask(self.proxy))
        if session is not None:
            self.sessions[url] = session
            added = session.add_token_cookies()
            if added:
                log.info("Cookie di accesso ricavati dal browser: %s", ", ".join(added))
            if session.user_agent and not self._custom_ua:
                self.user_agent = session.user_agent      # stesso «nome» del browser: i cookie anti-bot valgono
        owner = chat_owner(session, url)
        if CHAT_LINK.search(url):
            log.info("Chat di %s: i file vanno in %s/Chat", owner or "?", owner or "<id>")
        async with self._client() as client:
            try:
                plugin.pause_scale = self.pause_scale     # «Pause tra un file e l'altro» vale anche per le pagine
                gen = plugin.list_files(client, url, password, session=session) \
                    if getattr(plugin, "ACCEPTS_SESSION", False) else plugin.list_files(client, url, password)
                if session is not None and not getattr(plugin, "ACCEPTS_SESSION", False):
                    log.info("Il plugin %s non usa la sessione del browser (uso solo i cookie)", plugin.NAME)
                async for f in gen:
                    if self._stop:
                        break
                    if not matches(f.name, patterns):
                        log.debug("  - %s escluso dal filtro dei tipi di file", f.name)
                        continue
                    key = mirror_key(f.url)
                    if key in mirrors:
                        log.debug("  = doppione (stesso file su un altro server): %s", short(f.url))
                        continue
                    mirrors.add(key)
                    f.subdir = organize(f.subdir, url, f.name,
                                        self.folder_per_link and not f.meta.get("folder_from_title"),
                                        self.split_by_type, owner=owner, album=f.meta.get("album"))
                    f.opts = self.opts
                    files.append(f)
                    self.on_event("found", {"file": f, "total": self._found_offset + len(files)})
            except asyncio.CancelledError:
                log.info("Ricerca interrotta: %d file trovati fin qui", len(files))
        self.flush_counters()
        self.on_event("scanned", {"files": files})
        log.info("Trovati %d file%s", len(files),
                 f" (filtro tipi: {', '.join(patterns)})" if patterns else "")
        return files

    async def scan_many(self, urls: list[str], password: str | None = None,
                        sessions: dict | None = None) -> list[RemoteFile]:
        """Cerca su più link (un progetto può averne tanti). Un link rotto non ferma gli altri."""
        urls = [u.strip() for u in urls if u.strip()]
        self._arm()
        await self._use_pool()
        out: list[RemoteFile] = []
        seen: set[str] = set()
        for i, url in enumerate(urls):
            if self._stop:
                break
            if len(urls) > 1:
                self.on_event("link", {"url": url, "index": i + 1, "total": len(urls)})
            self._found_offset = len(out)
            try:
                found = await self.scan(url, password, session=(sessions or {}).get(url))
            except PluginError as e:
                if len(urls) == 1:
                    raise
                log.warning("Link saltato (%s): %s", url, e)
                self.on_event("warning", {"message": f"Link saltato ({url}): {e}"})
                continue
            finally:
                self._found_offset = 0
            for f in found:
                if f.url not in seen:
                    seen.add(f.url)
                    out.append(f)
        return out

    def _start_download_session(self, files: list[RemoteFile]):
        limits = [f.opts["connections"] for f in files if f.opts and f.opts.get("connections")]
        per_host = min(limits) if limits else self.per_host
        if self.adaptive and self.site_memory is None and self.transport is None:
            try:
                from .netpolicy import SiteMemory
                self.site_memory = SiteMemory()
            except Exception:  # noqa: BLE001
                self.site_memory = None
        self._gate = HostGate(per_host, self.pause_scale, adaptive=self.adaptive, memory=self.site_memory)
        self._gsem = asyncio.Semaphore(max(1, self.concurrency))
        self._client_obj = self._client()
        return per_host

    async def _end_download_session(self):
        try:
            self._gate.remember()
        except Exception:  # noqa: BLE001
            pass
        self.flush_counters()
        if self._client_obj is not None:
            await self._client_obj.aclose()
            self._client_obj = None
        if self._direct_obj is not None:
            await self._direct_obj.aclose()
            self._direct_obj = None

    async def _wait_schedule(self):
        """9: fuori orario o a batteria aspetta (si può sempre interrompere)."""
        said = None
        while self.schedule is not None and not self._stop:
            why = self.schedule.blocked()
            if not why:
                if said:
                    log.info("Si riparte: %s non vale più", said)
                    self.on_event("resumed", {})
                return
            if why != said:
                log.info("In pausa: %s", why)
                self.on_event("waiting", {"reason": why})
                said = why
            await asyncio.sleep(30)

    async def _worker(self, f: RemoteFile, stats: dict):
        opts = f.opts if f.opts is not None else self.opts
        if self._stop:
            return
        await self._wait_schedule()
        if self._stop:
            return
        result = await self._download(self._client_obj, f, opts)
        stats[result] = stats.get(result, 0) + 1

    async def download(self, files: list[RemoteFile]) -> dict:
        """Fase 2: scarica i file scelti.

        Più file insieme, ma con cortesia verso ogni server:
          - al massimo `per_host` connessioni per server (quelle del template, o 2), che crescono
            piano se il server risponde bene e scendono se si lamenta
          - la pausa del template vale per ogni connessione
          - se un server risponde 429/503 rallenta solo quel server, per il tempo che chiede
          - prima i file piccoli, e i server si alternano (uno lento non blocca gli altri)
        """
        stats = {"found": len(files), "skipped": 0, "done": 0, "failed": 0}
        self.ip_failed = []          # (file, percorso, pausa): si possono riprovare col browser interno
        self._pausing = False
        self._arm()
        await self._use_pool()
        files = order_for_download(files)
        per_host = self._start_download_session(files)
        hosts = {urlsplit(f.url).hostname for f in files}
        log.info("Download di %d file in %s — fino a %d insieme, max %d per server (%d server diversi)%s",
                 len(files), self.dest, self.concurrency, per_host, len(hosts),
                 ", connessioni adattive" if self.adaptive else "")
        t0 = time.monotonic()
        try:
            try:
                await asyncio.gather(*(self._worker(f, stats) for f in files))
            except asyncio.CancelledError:
                log.info("Download %s", "in pausa" if self._pausing else "interrotto")
        finally:
            await self._end_download_session()
        log.info("Download finito in %.1f s: %d scaricati, %d già presenti, %d errori",
                 time.monotonic() - t0, stats["done"], stats["skipped"], stats["failed"])
        self.on_event("finished", {**stats, "paused": self._pausing})
        return stats

    async def scan_and_download(self, urls: list[str], password: str | None = None,
                                sessions: dict | None = None) -> dict:
        """5: cerca e scarica insieme: ogni file parte appena viene trovato."""
        self._arm()
        await self._use_pool()
        self._pausing = False
        self.ip_failed = []
        stats = {"found": 0, "skipped": 0, "done": 0, "failed": 0}
        queue: asyncio.Queue = asyncio.Queue()
        outer = self.on_event

        def tap(kind, data):
            outer(kind, data)
            if kind == "found":
                queue.put_nowait(data["file"])
        self.on_event = tap
        self._start_download_session([])
        tasks: list[asyncio.Task] = []
        t0 = time.monotonic()
        log.info("Cerco e scarico insieme (i file partono appena trovati)")

        async def feeder():
            while True:
                f = await queue.get()
                if f is None:
                    return
                if f.opts and f.opts.get("connections") and f.opts["connections"] < self._gate.per_host:
                    self._gate.per_host = f.opts["connections"]
                stats["found"] += 1
                tasks.append(asyncio.ensure_future(self._worker(f, stats)))

        feed = asyncio.ensure_future(feeder())
        try:
            try:
                await self.scan_many(urls, password, sessions)
                queue.put_nowait(None)
                await feed
                if tasks:
                    await asyncio.gather(*tasks)
            except asyncio.CancelledError:
                for t in tasks:
                    t.cancel()
                feed.cancel()
                log.info("Interrotto")
        finally:
            self.on_event = outer
            await self._end_download_session()
        log.info("Finito in %.1f s: %d scaricati, %d già presenti, %d errori",
                 time.monotonic() - t0, stats["done"], stats["skipped"], stats["failed"])
        self.on_event("finished", {**stats, "paused": self._pausing})
        return stats

    async def run(self, url: str, password: str | None = None, plugin=None) -> dict:
        """Tutto insieme: cerca e scarica."""
        self._arm()
        await self._use_pool()
        files = await self.scan(url, password, plugin)
        if self._stop:
            stats = {"found": len(files), "skipped": 0, "done": 0, "failed": 0}
            self.on_event("finished", stats)
            return stats
        return await self.download(files)

    def _get_bytes(self, url: str, headers: dict, max_bytes: int) -> bytes:
        self._check_proxy()
        with httpx.Client(transport=self.sync_transport, headers={**BROWSER_HEADERS, "User-Agent": self.user_agent},
                          cookies=self._cookies(),
                          proxy=None if self.sync_transport else self.proxy,
                          follow_redirects=True, timeout=httpx.Timeout(30.0)) as c:
            with c.stream("GET", url, headers=headers) as r:
                r.raise_for_status()
                data = bytearray()
                for chunk in r.iter_bytes(128 * 1024):
                    data += chunk
                    if len(data) > max_bytes:
                        raise ValueError("file troppo grande per l'anteprima")
                return bytes(data)

    def preview_bytes(self, f: RemoteFile, local: str | None = None,
                      max_bytes: int | None = None) -> tuple[bytes, str]:
        """Immagine per l'anteprima (sincrono, da usare in un thread). Restituisce (dati, fonte)."""
        max_bytes = max_bytes or self.preview_max
        kind = kind_of(f.name)
        if local and Path(local).exists():
            if kind == "image":
                return Path(local).read_bytes(), "file sul disco"
            if kind == "video":
                return video_frame(local, ffmpeg=self.ffmpeg_path), "fotogramma dal file sul disco"
        if f.thumb:
            log.debug("anteprima: miniatura del sito %s", short(f.thumb))
            return self._get_bytes(f.thumb, f.headers, max_bytes), "miniatura del sito"
        if kind == "video":
            log.debug("anteprima: fotogramma con ffmpeg da %s", short(f.url))
            headers = {**f.headers, "User-Agent": USER_AGENT}
            ck = self.cookie_header(f.url)
            if ck:
                headers["Cookie"] = ck
            return video_frame(f.url, headers, proxy=self.proxy, ffmpeg=self.ffmpeg_path), "fotogramma (ffmpeg)"
        log.debug("anteprima: scarico l'immagine %s", short(f.url))
        return self._get_bytes(f.url, f.headers, max_bytes), "immagine"

    def _exists_skip(self, target: Path, size: int | None, mode: str) -> bool:
        """True se il file c'è già e va saltato."""
        if not target.exists():
            return False
        if mode == "do_not_save":
            return True
        if mode == "overwrite":
            return False
        same = size is not None and target.stat().st_size == size
        return same or (mode == "same_size" and size is None)

    async def _download(self, client: httpx.AsyncClient, f: RemoteFile, opts: dict | None = None) -> str:
        opts = opts or {}
        gate: HostGate = getattr(self, "_gate", None) or HostGate(self.per_host)
        gsem: asyncio.Semaphore = getattr(self, "_gsem", None) or asyncio.Semaphore(self.concurrency)
        mode = opts.get("conflicts") or self.default_conflicts
        min_size = opts.get("min_size", 0)
        folder = self.dest.joinpath(*[safe_part(p) for p in f.subdir.split("/") if p])
        target = folder / safe_part(f.name)
        if self.history is not None and self.skip_known:
            before = self.history.get(file_key(f.url))
            if before and Path(before).exists():
                log.info("= già scaricato prima: %s", before)
                self.on_event("skipped", {"file": f, "path": Path(before)})
                return "skipped"
        if self._exists_skip(target, f.size, mode):
            log.info("= già presente (%s): %s", mode, target)
            self.on_event("skipped", {"file": f, "path": target})
            return "skipped"

        free = free_bytes(self.dest)
        if free is not None and free < self.reserve_mb * 1024 * 1024 + (f.size or 0):
            msg = (f"Spazio su disco quasi finito ({_size(free)} liberi): mi fermo per non riempire il disco. "
                   f"Libera spazio e riprendi.")
            if not getattr(self, "_disk_warned", False):
                self._disk_warned = True
                log.error(msg)
                self.on_event("disk_full", {"message": msg, "free": free})
                self.stop()
            return "failed"
        folder.mkdir(parents=True, exist_ok=True)
        if is_hls(f):
            return await self._download_hls(f, target, opts)
        attempt = throttled = long_pauses = 0
        part: Path | None = None
        renamed = False
        old_part = target.with_name(target.name + ".part")
        if old_part.exists() and old_part.stat().st_size > 0 and mode != "overwrite":
            part = old_part                     # 7: pezzo lasciato da una pausa: si riprende da lì
            log.debug("  trovato %s (%s): riprendo", old_part.name, _size(old_part.stat().st_size))
        elif self.segments > 1 and (self.transport is None or getattr(self, "_test_segments", False)):
            seg = await self._try_segmented(f, target, opts, mode)
            if seg:
                return seg
        while attempt < self.retries:
            try:
                async with gate.slot(f.url, opts.get("delay")), gsem:
                    if self._stop:
                        raise asyncio.CancelledError
                    headers = dict(f.headers)
                    have = part.stat().st_size if part is not None and part.exists() else 0
                    if have:
                        headers["Range"] = f"bytes={have}-"
                    log.debug("↓ GET %s%s%s", short(f.url),
                              f"  Referer: {f.headers.get('Referer')}" if f.headers.get("Referer") else "",
                              f"  (riprendo da {_size(have)})" if have else "")
                    t1 = time.monotonic()
                    client = self._client_obj or client
                    if self.proxy and ip_locked(f.url):
                        # link legato all'IP del browser: col proxy darebbe 403
                        if self._direct_obj is None:
                            self._direct_obj = self._client(direct=True)
                            log.info("  I link di %s valgono solo per il tuo IP: questi file li scarico "
                                     "SENZA proxy", urlsplit(f.url).hostname)
                        client = self._direct_obj
                    async with client.stream("GET", f.url, headers=headers) as r:
                        log.debug("  risposta %d, %s, %s byte%s", r.status_code, r.headers.get("content-type", "?"),
                                  r.headers.get("content-length", "?"),
                                  f", nome dal server: {r.headers.get('content-disposition')}"
                                  if r.headers.get("content-disposition") else "")
                        if r.status_code in (429, 503):
                            wait = retry_after(r.headers.get("retry-after"), default=min(20 * (throttled + 1), 300))
                            gate.cooldown(f.url, wait)
                            throttled += 1
                            log.warning("! %s risponde %d (troppe richieste): rallento quel server per %.0f s",
                                        urlsplit(f.url).hostname, r.status_code, wait)
                            self.on_event("retry", {"file": f, "attempt": throttled,
                                                    "error": f"server occupato, attendo {wait:.0f} s"})
                            if throttled > 6:
                                # 13: il server insiste: pausa lunga solo per lui, gli altri continuano
                                long_pauses += 1
                                if long_pauses > 4:
                                    raise httpx.HTTPStatusError("troppe richieste", request=r.request, response=r)
                                pause = 15 * 60
                                gate.cooldown(f.url, pause)
                                throttled = 3
                                msg = (f"{urlsplit(f.url).hostname} continua a dire «troppe richieste»: "
                                       f"lo metto in pausa {pause // 60} minuti, gli altri siti continuano")
                                log.warning(msg)
                                self.on_event("host_paused", {"host": urlsplit(f.url).hostname, "seconds": pause,
                                                              "message": msg})
                            continue
                        if r.status_code == 416 and have:
                            log.debug("  la ripresa non è possibile: ricomincio da zero")
                            part.unlink(missing_ok=True)
                            continue
                        r.raise_for_status()
                        resumed = r.status_code == 206 and have > 0
                        if r.headers.get("last-modified"):
                            f.meta.setdefault("last_modified", r.headers["last-modified"])
                        length = int(r.headers.get("content-length", 0))
                        total = (have + length if resumed else length) or f.size or None
                        if not renamed:
                            cd = filename_from_cd(r.headers.get("content-disposition", ""))
                            if cd and not f.fixed_name and opts.get("use_content_disposition", True):
                                target = folder / safe_part(cd)
                                if self._exists_skip(target, total, mode):
                                    log.info("= già presente (%s): %s", mode, target)
                                    self.on_event("skipped", {"file": f, "path": target})
                                    return "skipped"
                            if min_size and total and total < min_size:
                                log.info("- saltato, troppo piccolo (%d < %d byte): %s", total, min_size, f.name)
                                self.on_event("filtered", {"file": f, "reason": "troppo piccolo"})
                                return "skipped"
                            if target.exists() and total and target.stat().st_size == total \
                                    and mode in ("rename", "same_size"):
                                # stesso nome e stessa grandezza: è lo stesso file, non un doppione da rinominare
                                log.info("= già presente (stessa grandezza): %s", target)
                                if self.history is not None:
                                    self.history.add(file_key(f.url), str(target), total)
                                self.on_event("skipped", {"file": f, "path": target})
                                return "skipped"
                            if target.exists() and mode == "rename":
                                target = unique_name(target, opts.get("rename_digits", 3))
                            renamed = True
                            part = target.with_name(target.name + ".part")
                            if part.exists() and not resumed:
                                part.unlink()
                        if resumed:
                            log.info("  ↻ riprendo %s da %s", target.name, _size(have))
                        got = have if resumed else 0
                        with open(part, "ab" if resumed else "wb") as fh:
                            async for chunk in r.aiter_bytes():   # scrive subito: se cade la connessione, si riprende da qui
                                if self._stop:
                                    raise asyncio.CancelledError
                                fh.write(chunk)
                                got += len(chunk)
                                self.on_event("progress", {"file": f, "bytes": got, "total": total})
                                await self._limiter.consume(len(chunk))
                if total and got < total:
                    raise httpx.ReadError(f"file incompleto ({got} di {total} byte)")
                if min_size and got < min_size:
                    part.unlink(missing_ok=True)
                    self.on_event("filtered", {"file": f, "reason": "troppo piccolo"})
                    return "skipped"
                if self.verify_files:
                    ok, why = await asyncio.to_thread(check_file, part, target.suffix)
                    if not ok:
                        log.warning("  ✗ %s: %s → lo riscarico", target.name, why)
                        try:
                            head = part.read_bytes()[:600].decode("utf-8", "replace")
                            t = re.search(r"<title[^>]*>([^<]{0,120})", head, re.I)
                            log.debug("    inizio della risposta: %s", (t.group(1) if t else re.sub(r"\s+", " ", head))[:200])
                        except OSError:
                            pass
                        part.unlink(missing_ok=True)
                        self.on_event("retry", {"file": f, "attempt": attempt + 1, "error": why})
                        raise httpx.ReadError(why)
                part.replace(target)
                secs = max(time.monotonic() - t1, 0.001)
                log.info("✓ %s (%s, %.1f s)", target, _size(got), secs)
                return await self._finished_ok(f, target, got)
            except (httpx.HTTPError, OSError) as e:
                if isinstance(e, httpx.HTTPError) and await self._switch_proxy(e):
                    continue                     # problema del proxy, non del file: riprovo col prossimo
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 403 and locked_ip(f.url):
                    want = locked_ip(f.url)
                    mine = await self._my_ip(self._direct_obj or self._client_obj or client)
                    if not getattr(self, "_ip_warned", False):
                        self._ip_warned = True
                        if mine and mine != want:
                            msg = (f"Il sito ha dato i link al browser con l'IP {want}, ma i download escono "
                                   f"con l'IP {mine}: per questo 403. VPN o proxy diversi tra browser e app? "
                                   "Rifai la ricerca con la stessa connessione per entrambi.")
                        else:
                            msg = (f"403 su un link valido solo per l'IP {want} (il tuo ora: {mine or '?'}). "
                                   "Provo a scaricarli col browser interno, che usa la stessa rete del login.")
                        log.error(msg)
                        self.on_event("warning", {"message": msg})
                    log.error("✗ %s: 403, link legato a un altro IP o non accessibile", short(f.url))
                    self.ip_failed.append((f, str(target), opts.get("delay")))
                    if part is not None:
                        part.unlink(missing_ok=True)
                    self.on_event("failed", {"file": f, "error": "403: link legato a un altro IP"})
                    return "failed"
                attempt += 1
                kept = part.stat().st_size if part is not None and part.exists() else 0
                log.warning("! tentativo %d/%d fallito per %s: %s%s", attempt, self.retries, short(f.url),
                            e or e.__class__.__name__, f" (tengo {_size(kept)} per riprendere)" if kept else "")
                self.on_event("retry", {"file": f, "attempt": attempt, "error": str(e)})
                await asyncio.sleep(min(2 ** attempt, 10))
            except asyncio.CancelledError:
                if part is not None and not self._pausing:
                    part.unlink(missing_ok=True)
                return "stopped"
        if part is not None:
            part.unlink(missing_ok=True)
        log.error("✗ non scaricato dopo %d tentativi: %s", self.retries, short(f.url))
        self._record_failure(f, "dopo tutti i tentativi")
        self.on_event("failed", {"file": f})
        return "failed"

    def _record_failure(self, f: RemoteFile, why: str):
        if self.history is not None:
            try:
                from .netpolicy import site_of
                self.history.add_failure(site_of(f.url), why)
            except Exception:  # noqa: BLE001
                pass

    async def _finished_ok(self, f: RemoteFile, target: Path, got: int) -> str:
        gate = getattr(self, "_gate", None)
        if gate is not None:
            gate.success(f.url)
        if self.name_pattern.strip() or self.file_dates or self.save_captions:
            self._name_counter += 1
            owner = next((p for p in f.subdir.replace("\\", "/").split("/") if p), "")
            try:
                target = await asyncio.to_thread(
                    finalize, target, f.url, f.meta, pattern=self.name_pattern, counter=self._name_counter,
                    owner=owner, set_dates=self.file_dates, captions=self.save_captions)
            except OSError as e:
                log.warning("  ritocco del file non riuscito (%s): resta %s", e, target.name)
        if self.history is not None:
            self.history.add(file_key(f.url), str(target), got)
        dup = None
        if self.dup_images != "off" and self.history is not None and kind_of(target.name) == "image":
            dup = await asyncio.to_thread(self._check_duplicate, target)
        if dup:
            original, moved = dup
            self.on_event("duplicate", {"file": f, "path": moved or target, "of": original})
            if moved:
                target = moved
        self.on_event("done", {"file": f, "path": target})
        return "done"

    def _check_duplicate(self, target: Path):
        """15: foto già scaricata con un altro nome o un'altra grandezza? (impronta dHash)"""
        from .netpolicy import hamming, image_hash
        h = image_hash(target)
        if h is None:
            return None
        for other_hash, other_path in self.history.hashes():
            if other_path != str(target) and hamming(h, other_hash) <= 4 and Path(other_path).exists():
                moved = None
                if self.dup_images == "move":
                    dd = self.dest / "_Doppioni"
                    dd.mkdir(parents=True, exist_ok=True)
                    moved = unique_name(dd / target.name) if (dd / target.name).exists() else dd / target.name
                    target.replace(moved)
                log.info("≈ %s è uguale a %s%s", target.name, other_path,
                         f" → spostato in {moved.parent.name}" if moved else "")
                return other_path, moved
        self.history.add_hash(h, str(target))
        return None

    async def _try_segmented(self, f: RemoteFile, target: Path, opts: dict, mode: str) -> str | None:
        """1: file grandi a pezzi (Range), solo se il server lo permette e dentro il limite per server.
        Restituisce "done"/"skipped" oppure None per usare il download normale."""
        if kind_of(f.name) != "video" and not (f.size and f.size >= SEGMENT_MIN):
            return None
        if self.proxy and ip_locked(f.url):
            return None
        if getattr(self, "_gate", None) is None or self._client_obj is None:
            return None
        gate: HostGate = self._gate
        client = self._client_obj
        try:
            async with gate.slot(f.url, None), self._gsem:
                r = await client.get(f.url, headers={**f.headers, "Range": "bytes=0-0"})
                if r.status_code != 206:
                    return None
                m = re.search(r"/(\d+)$", r.headers.get("content-range", ""))
                total = int(m.group(1)) if m else 0
                cd = filename_from_cd(r.headers.get("content-disposition", ""))
        except httpx.HTTPError:
            return None
        if total < SEGMENT_MIN:
            return None
        if cd and not f.fixed_name and opts.get("use_content_disposition", True):
            target = target.with_name(safe_part(cd))
        if self._exists_skip(target, total, mode) or (target.exists() and target.stat().st_size == total):
            log.info("= già presente: %s", target)
            self.on_event("skipped", {"file": f, "path": target})
            return "skipped"
        if target.exists() and mode == "rename":
            target = unique_name(target, opts.get("rename_digits", 3))
        n = max(2, min(self.segments, gate.per_host))
        size = -(-total // n)
        ranges = [(i * size, min(total, (i + 1) * size) - 1) for i in range(n)]
        part = target.with_name(target.name + ".part")
        with open(part, "wb") as fh:
            fh.truncate(total)
        done_bytes = [0] * n
        log.info("  ⇉ %s (%s) in %d pezzi", target.name, _size(total), n)
        t1 = time.monotonic()

        async def piece(i: int, a: int, b: int):
            pos, tries = a, 0
            while pos <= b:
                try:
                    async with gate.slot(f.url, None), self._gsem:
                        async with client.stream("GET", f.url, headers={**f.headers, "Range": f"bytes={pos}-{b}"}) as r:
                            if r.status_code in (429, 503):
                                gate.cooldown(f.url, retry_after(r.headers.get("retry-after"), 30))
                                raise httpx.HTTPStatusError("troppe richieste", request=r.request, response=r)
                            if r.status_code != 206:
                                raise httpx.HTTPStatusError(f"risposta {r.status_code}", request=r.request, response=r)
                            with open(part, "r+b") as fh:
                                fh.seek(pos)
                                async for chunk in r.aiter_bytes():
                                    if self._stop:
                                        raise asyncio.CancelledError
                                    fh.write(chunk)
                                    pos += len(chunk)
                                    done_bytes[i] = pos - a
                                    self.on_event("progress", {"file": f, "bytes": sum(done_bytes), "total": total})
                                    await self._limiter.consume(len(chunk))
                except httpx.HTTPError as e:
                    tries += 1
                    if tries >= self.retries:
                        raise
                    log.debug("  pezzo %d: %s, riprovo", i + 1, e)
                    await asyncio.sleep(min(2 ** tries, 10))

        try:
            await asyncio.gather(*(piece(i, a, b) for i, (a, b) in enumerate(ranges)))
        except httpx.HTTPError as e:
            log.warning("  download a pezzi non riuscito (%s): riprovo normale", e)
            part.unlink(missing_ok=True)
            return None
        except asyncio.CancelledError:
            part.unlink(missing_ok=True)
            raise
        if self.verify_files:
            ok, why = await asyncio.to_thread(check_file, part, target.suffix)
            if not ok:
                log.warning("  download a pezzi rovinato (%s): riprovo normale", why)
                part.unlink(missing_ok=True)
                return None
        part.replace(target)
        log.info("✓ %s (%s, %.1f s, %d pezzi)", target, _size(total), time.monotonic() - t1, n)
        return await self._finished_ok(f, target, total)

    async def _download_hls(self, f: RemoteFile, target: Path, opts: dict) -> str:
        """21: video HLS (.m3u8) senza protezione → un solo .mp4 con ffmpeg. Quelli cifrati/DRM no."""
        ff = find_ffmpeg(self.ffmpeg_path)
        out = target.with_suffix(".mp4")
        if out.exists():
            self.on_event("skipped", {"file": f, "path": out})
            return "skipped"
        if not ff:
            log.error("✗ %s: serve ffmpeg per i video HLS (brew install ffmpeg)", f.name)
            self.on_event("failed", {"file": f, "error": "serve ffmpeg"})
            return "failed"
        client = self._client_obj
        try:
            async with self._gate.slot(f.url, opts.get("delay")):
                url, text = f.url, (await client.get(f.url, headers=f.headers)).text
                if "#EXT-X-STREAM-INF" in text:          # playlist principale: prendo la qualità più alta
                    best, bw = None, -1
                    lines = text.splitlines()
                    for k, line in enumerate(lines):
                        if line.startswith("#EXT-X-STREAM-INF"):
                            m = re.search(r"BANDWIDTH=(\d+)", line)
                            b = int(m.group(1)) if m else 0
                            nxt = next((x for x in lines[k + 1:] if x and not x.startswith("#")), None)
                            if nxt and b > bw:
                                best, bw = nxt, b
                    if best:
                        from urllib.parse import urljoin
                        url = urljoin(f.url, best)
                        text += "\n" + (await client.get(url, headers=f.headers)).text
        except httpx.HTTPError as e:
            log.error("✗ %s: %s", f.name, e)
            self.on_event("failed", {"file": f, "error": str(e)})
            return "failed"
        if re.search(r"#EXT-X-(SESSION-)?KEY:(?!.*METHOD=NONE)", text):
            log.error("✗ %s: video protetto/cifrato: non lo scarico", f.name)
            self.on_event("failed", {"file": f, "error": "video protetto"})
            return "failed"
        headers = {**f.headers, "User-Agent": self.user_agent}
        ck = self.cookie_header(url)
        if ck:
            headers["Cookie"] = ck
        hdr = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
        tmp = out.with_name(out.name + ".part")
        cmd = [ff, "-y", "-loglevel", "error", "-headers", hdr, "-i", url, "-c", "copy",
               "-bsf:a", "aac_adtstoasc", "-f", "mp4", str(tmp)]
        log.info("  ▶ HLS → %s (ffmpeg)", out.name)
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.DEVNULL,
                                                    stderr=asyncio.subprocess.PIPE)
        try:
            while proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), 1.0)
                except asyncio.TimeoutError:
                    if tmp.exists():
                        self.on_event("progress", {"file": f, "bytes": tmp.stat().st_size, "total": None})
            err = (await proc.stderr.read()).decode(errors="replace")[-300:]
        except asyncio.CancelledError:
            proc.kill()
            tmp.unlink(missing_ok=True)
            raise
        if proc.returncode != 0 or not tmp.exists():
            tmp.unlink(missing_ok=True)
            log.error("✗ %s: ffmpeg: %s", f.name, err.strip())
            self.on_event("failed", {"file": f, "error": "ffmpeg"})
            return "failed"
        tmp.replace(out)
        log.info("✓ %s (%s)", out, _size(out.stat().st_size))
        return await self._finished_ok(f, out, out.stat().st_size)


class SpeedLimiter:
    """Limite di velocità totale per tutti i download insieme.

    kbps: limite fisso (0 = nessuno).
    share: 10 — usa solo questa percentuale della tua linea (es. 70 = lascia libero il 30%).
           Misura la velocità massima nei primi secondi, poi resta sotto quella quota."""

    MEASURE = 20.0

    def __init__(self, kbps: int = 0, share: int = 0):
        self.fixed = max(0, kbps) * 1024
        self.share = share if 0 < share < 100 else 0
        self.rate = self.fixed
        self.allowance = float(self.rate)
        self.last = time.monotonic()
        self.lock: asyncio.Lock | None = None
        self._t0: float | None = None
        self._win = (0.0, 0)
        self._peak = 0.0

    def _measure(self, n: int):
        now = time.monotonic()
        if self._t0 is None:
            self._t0, self._win = now, (now, 0)
        start, got = self._win
        got += n
        if now - start >= 2:
            self._peak = max(self._peak, got / (now - start))
            self._win = (now, 0)
        else:
            self._win = (start, got)
        if now - self._t0 >= self.MEASURE and self._peak:
            cap = max(100 * 1024, self._peak * self.share / 100)
            self.rate = min(self.fixed, cap) if self.fixed else cap
            self.allowance = float(self.rate)
            self.last = now
            log.info("Banda: linea fino a %s/s, ne uso il %d%% (%s/s)",
                     _size(self._peak), self.share, _size(self.rate))
            self.share = 0

    async def consume(self, n: int):
        if self.share:
            self._measure(n)
        if not self.rate:
            return
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            now = time.monotonic()
            self.allowance = min(self.rate, self.allowance + (now - self.last) * self.rate)
            self.last = now
            self.allowance -= n
            if self.allowance < 0:
                wait = -self.allowance / self.rate
                await asyncio.sleep(wait)
                self.last = time.monotonic()
                self.allowance = 0


def locked_ip(url: str) -> str | None:
    """IP per cui vale un link firmato CloudFront (None se il link non è legato a un IP)."""
    import base64
    import json as _json
    from urllib.parse import parse_qs
    pol = (parse_qs(urlsplit(url).query).get("Policy") or [""])[0]
    if not pol:
        return None
    raw = pol.replace("-", "+").replace("_", "=").replace("~", "/")
    try:
        data = _json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
        for st in data.get("Statement", []):
            ip = ((st.get("Condition") or {}).get("IpAddress") or {}).get("AWS:SourceIp")
            if ip:
                return ip.split("/")[0]
    except (ValueError, TypeError, AttributeError):
        pass
    return None


def system_proxy() -> str | None:
    """Proxy di sistema (macOS/Windows: impostazioni di rete). Il browser interno lo usa da solo:
    anche i download devono usarlo, se no escono con un altro IP e i link legati all'IP danno 403."""
    try:
        import urllib.request
        p = urllib.request.getproxies()
        return p.get("https") or p.get("http") or None
    except Exception:  # noqa: BLE001
        return None


def ip_locked(url: str) -> bool:
    """Link firmato (CloudFront) valido solo per un IP: quello del browser che l'ha ricevuto.
    Con un proxy l'IP cambia e il server risponde 403: questi file vanno scaricati senza proxy."""
    import base64
    import json as _json
    from urllib.parse import parse_qs
    q = parse_qs(urlsplit(url).query)
    pol = (q.get("Policy") or [""])[0]
    if not pol:
        return False
    raw = pol.replace("-", "+").replace("_", "=").replace("~", "/")
    try:
        data = _json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, TypeError):
        return "SourceIp" in pol
    for st in data.get("Statement", []):
        if "IpAddress" in (st.get("Condition") or {}):
            return True
    return False


class HostGate:
    """Cortesia verso ogni server: connessioni massime, pausa tra le richieste, raffreddamento dopo 429.

    scale: quanto della pausa del template usare (1 = tutta, 0.5 = metà, 0 = quasi niente).
    adaptive: parte con poche connessioni e ne aggiunge una ogni GROW_AFTER file andati bene,
    fino al massimo; a un «troppe richieste» dimezza. memory ricorda il limite di ogni server
    per la volta dopo. Se un server risponde 429/503 torna subito alla pausa piena per lui."""

    MIN_PAUSE = (0.3, 0.8)
    GROW_AFTER = 6

    def __init__(self, per_host: int = 2, scale: float = 1.0, adaptive: bool = False, memory=None):
        self.per_host = max(1, per_host)
        self.scale = max(0.0, min(scale, 1.0))
        self.adaptive = adaptive
        self.memory = memory
        self.limit: dict[str, int] = {}
        self.active: dict[str, int] = {}
        self.cond: dict[str, asyncio.Condition] = {}
        self.streak: dict[str, int] = {}
        self.next_ok: dict[str, float] = {}
        self.strict: set[str] = set()
        self._bg: set[asyncio.Task] = set()

    @staticmethod
    def host(url: str) -> str:
        return (urlsplit(url).hostname or "").lower()

    def limit_for(self, h: str) -> int:
        if h not in self.limit:
            start = self.per_host
            if self.adaptive:
                remembered = self.memory.get(h) if self.memory else None
                start = remembered or max(1, (self.per_host + 1) // 2)
                if remembered:
                    log.debug("  %s: riparto da %d connessioni (ricordate)", h, remembered)
            self.limit[h] = max(1, min(self.per_host, start))
        return self.limit[h]

    def pause_for(self, h: str, delay: tuple[float, float] | None) -> float:
        if not delay:
            return 0.0
        lo, hi = delay
        if h not in self.strict and self.scale < 1:
            if self.scale <= 0:
                lo, hi = self.MIN_PAUSE
            else:
                lo, hi = max(lo * self.scale, self.MIN_PAUSE[0]), max(hi * self.scale, self.MIN_PAUSE[1])
        return random.uniform(lo, hi)

    async def _acquire(self, h: str):
        c = self.cond.setdefault(h, asyncio.Condition())
        async with c:
            await c.wait_for(lambda: self.active.get(h, 0) < self.limit_for(h))
            self.active[h] = self.active.get(h, 0) + 1

    async def _release(self, h: str):
        self.active[h] = max(0, self.active.get(h, 1) - 1)
        await self._notify(h)

    async def _notify(self, h: str):
        c = self.cond.get(h)
        if c is not None:
            async with c:
                c.notify_all()

    def _bg_task(self, coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            coro.close()                       # fuori dal ciclo asincrono (es. nei test): niente da avvisare
            return
        t = asyncio.ensure_future(coro)
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    @asynccontextmanager
    async def slot(self, url: str, delay: tuple[float, float] | None = None):
        """Una "connessione" verso il server: al massimo `limit` insieme.
        La pausa vale per ogni connessione (come in EPF): dopo un file quella connessione
        resta occupata per la pausa, ma il file è già finito e il lavoro va avanti."""
        h = self.host(url)
        await self._acquire(h)
        try:
            wait = self.next_ok.get(h, 0) - time.monotonic()      # raffreddamento dopo 429/503
            if wait > 0:
                log.debug("  attesa %.1f s per %s (server occupato)", wait, h)
                await asyncio.sleep(wait)
        except BaseException:
            self._bg_task(self._release(h))
            raise
        try:
            yield
        finally:
            pause = self.pause_for(h, delay)
            if pause > 0:
                log.debug("  pausa %.1f s su questa connessione verso %s", pause, h)

            async def _later():
                try:
                    if pause > 0:
                        await asyncio.sleep(pause)
                finally:
                    await self._release(h)
            self._bg_task(_later())

    def success(self, url: str):
        """Un file è andato bene: con la modalità adattiva, ogni tanto una connessione in più."""
        if not self.adaptive:
            return
        h = self.host(url)
        self.streak[h] = self.streak.get(h, 0) + 1
        lim = self.limit_for(h)
        if self.streak[h] >= self.GROW_AFTER and lim < self.per_host and time.monotonic() > self.next_ok.get(h, 0):
            self.limit[h] = lim + 1
            self.streak[h] = 0
            log.info("  %s risponde bene: %d connessioni", h, lim + 1)
            self._bg_task(self._notify(h))

    def cooldown(self, url: str, seconds: float):
        h = self.host(url)
        if h not in self.strict and self.scale < 1:
            log.info("  %s si lamenta: da ora pause piene del template", h)
        self.strict.add(h)
        self.next_ok[h] = max(self.next_ok.get(h, 0), time.monotonic() + seconds)
        if self.adaptive:
            lim = self.limit_for(h)
            new = max(1, lim // 2)
            if new < lim:
                log.info("  %s: scendo a %d connessioni", h, new)
            self.limit[h] = new
            self.streak[h] = 0
            if self.memory:
                self.memory.set(h, new, throttled=True)

    def remember(self):
        """Salva per la volta dopo il limite raggiunto da ogni server."""
        if self.adaptive and self.memory:
            for h, lim in self.limit.items():
                self.memory.set(h, lim)
            self.memory.save()


def retry_after(value: str | None, default: float = 30) -> float:
    """Secondi da aspettare secondo l'intestazione Retry-After (numero o data)."""
    if not value:
        return default
    try:
        return max(1.0, min(float(value), 900))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        import datetime as _dt
        when = parsedate_to_datetime(value)
        return max(1.0, min((when - _dt.datetime.now(when.tzinfo)).total_seconds(), 900))
    except (TypeError, ValueError):
        return default


IMAGE_EXT = {".jpg", ".jpeg", ".jpe", ".jfif", ".png", ".gif", ".webp", ".bmp", ".avif", ".heic"}
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".mpg", ".mpeg", ".wmv", ".flv",
             ".ts", ".ogv", ".3gp", ".f4v"}


_GENERIC_SEGMENTS = {
    "l", "d", "a", "f", "u", "v", "i", "s", "c", "g", "p", "w", "links", "link", "album", "albums", "media",
    "posts", "post", "photos", "photo", "videos", "video", "gallery", "galleries", "pictures", "pics", "pic",
    "folder", "folders", "file", "files", "user", "users", "profile", "www", "download", "share", "api",
    "v1", "v2", "web", "home", "archive", "blog", "content", "view", "watch", "embed", "en", "it",
}
TYPE_FOLDERS = {"image": "Foto", "video": "Video", "other": "Altri"}


def source_name(url: str) -> str:
    """Nome leggibile della "fonte" di un link: profilo, album, cartella condivisa.
    onlyfans.com/mario/media -> mario · gofile.io/d/abc123 -> abc123 · gallery.php?gid=7 -> 7"""
    parts = urlsplit(url)
    for seg in (unquote(x) for x in parts.path.split("/") if x):
        low = seg.lower()
        if low in _GENERIC_SEGMENTS or re.fullmatch(r".+\.(php|html?|aspx?|jsp)", low):
            continue
        return safe_part(seg)[:80]
    for kv in parts.query.split("&"):
        if "=" in kv and kv.split("=", 1)[1]:
            return safe_part(unquote(kv.split("=", 1)[1]))[:80]
    host = (parts.hostname or "sito").lower().removeprefix("www.")
    return safe_part(host)


CHAT_LINK = re.compile(r"/chats?/(?:chat/)?([^/?#]+)", re.I)


FAN_SITE = re.compile(r"^https?://([^/]+\.)?(onlyfans\.com|fansly\.com)/", re.I)


def organize(subdir: str, link: str, name: str, per_link: bool, by_type: bool, owner: str | None = None,
             album: str | None = None) -> str:
    """Cartella finale di un file: [nome del link]/[sottocartelle del template]/[Foto|Video|Altri].
    Chat: [utente]/Chat/[Foto|Video] (utente = chi scrive nella chat, o il numero della chat)."""
    parts = [p for p in subdir.replace("\\", "/").split("/") if p]
    chat = CHAT_LINK.search(link)
    if chat:
        drop = {"my", "chats", "chat", chat.group(1).lower(), (owner or "").lower()}
        parts = [p for p in parts if p.lower() not in drop]
        parts[0:0] = [safe_part(owner or chat.group(1)), "Chat"]
    elif per_link:
        # nome dell'album/cartella se il sito lo dà (non il codice del link); profili OnlyFans/Fansly: il nome utente
        src = safe_part(album)[:120] if album and not FAN_SITE.match(link) else source_name(link)
        if not parts or src.lower() not in parts[0].lower():
            parts.insert(0, src)
    if by_type:
        parts.append(TYPE_FOLDERS[kind_of(name)])
    return "/".join(parts)


def chat_owner(session, link: str) -> str | None:
    """Nome utente di chi scrive in una chat (OnlyFans: il numero della chat è l'id dell'utente).
    Lo cerca nelle risposte che il browser interno ha già ricevuto."""
    m = CHAT_LINK.search(link or "")
    if not m or session is None:
        return None
    cid = m.group(1)
    if not cid.isdigit():
        return safe_part(cid)
    keyed = re.compile(r'"%s"\s*:\s*\{' % cid)
    by_id = re.compile(r'"id"\s*:\s*%s\b' % cid)
    uname = re.compile(r'"username"\s*:\s*"([^"\\]{1,80})"')
    for r in getattr(session, "requests", []) or []:
        text = r.text or ""
        if cid not in text:
            continue
        for rx in (keyed, by_id):
            for hit in rx.finditer(text):
                window = text[hit.end(): hit.end() + 1500]
                nxt = next((x for x in re.finditer(r'"id"\s*:\s*(\d+)', window) if x.group(1) != cid), None)
                if nxt:
                    window = window[: nxt.start()]
                u = uname.search(window)
                if u:
                    return safe_part(u.group(1))
    return None


def is_hls(f: RemoteFile) -> bool:
    return f.name.lower().endswith(".m3u8") or urlsplit(f.url).path.lower().endswith(".m3u8")


def order_for_download(files: list[RemoteFile]) -> list[RemoteFile]:
    """4 + 8: prima i file piccoli (foto, poi video), e i server a turno (uno lento non blocca gli altri)."""
    rank = {"image": 0, "other": 1, "video": 2}

    def key(f: RemoteFile):
        return (rank.get(kind_of(f.name), 1), f.size or 0)
    by_host: dict[str, list[RemoteFile]] = {}
    for f in sorted(files, key=key):
        by_host.setdefault(urlsplit(f.url).hostname or "", []).append(f)
    out: list[RemoteFile] = []
    queues = list(by_host.values())
    while queues:
        for q in list(queues):
            out.append(q.pop(0))
            if not q:
                queues.remove(q)
    return out


def mirror_key(url: str) -> str:
    """Lo stesso file servito da server diversi dello stesso sito ha la stessa chiave.
    es. store8.gofile.io/download/web/ID/a.mp4 e file-na-lax-1.gofile.io/download/web/ID/a.mp4"""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().split(".")
    site = ".".join(host[-3:] if len(host) >= 3 and len(host[-1]) == 2 and len(host[-2]) <= 3 else host[-2:])
    return f"{site}{parts.path}?{parts.query}"


_VOLATILE = re.compile(r"^(policy|signature|key-pair-id|expires?|exp|token|sig|hash|verify|x-amz-.*|t|ts|"
                       r"_|cache|cb|v|download|dl|n)$", re.I)


def file_key(url: str) -> str:
    """Chiave che resta uguale anche quando il sito rifirma il link (scadenza, token, firma...).
    Serve a riconoscere un file già scaricato in una ricerca successiva."""
    from urllib.parse import parse_qsl, urlencode
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().split(".")
    site = ".".join(host[-3:] if len(host) >= 3 and len(host[-1]) == 2 and len(host[-2]) <= 3 else host[-2:])
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _VOLATILE.match(k)]
    return f"{site}{parts.path}" + (f"?{urlencode(sorted(q))}" if q else "")


def kind_of(name: str) -> str:
    ext = Path(name.lower()).suffix
    return "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "other"


class FfmpegMissing(Exception):
    pass


def find_ffmpeg(custom: str | None = None) -> str | None:
    import shutil
    for cand in (custom, shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
                 str(Path.home() / ".homebrew/bin/ffmpeg"), "C:/ffmpeg/bin/ffmpeg.exe"):
        if cand and Path(cand).exists():
            return cand
    return None


def video_frame(src: str, headers: dict | None = None, width: int = 480, proxy: str | None = None,
                ffmpeg: str | None = None) -> bytes:
    """Un fotogramma JPEG da un video (file o indirizzo) con ffmpeg."""
    import subprocess
    ff = find_ffmpeg(ffmpeg)
    if not ff:
        raise FfmpegMissing("per i fotogrammi dei video serve ffmpeg (Mac: brew install ffmpeg)")
    pre = []
    if headers and src.startswith("http"):
        ua = headers.get("User-Agent")
        extra = "".join(f"{k}: {v}\r\n" for k, v in headers.items() if k != "User-Agent")
        if ua:
            pre += ["-user_agent", ua]
        if extra:
            pre += ["-headers", extra]
    if proxy and proxy.startswith("http") and src.startswith("http"):
        pre += ["-http_proxy", proxy]
    err = ""
    for seek in ("3", "0"):
        cmd = [ff, "-hide_banner", "-loglevel", "error", *pre, "-ss", seek, "-i", src,
               "-frames:v", "1", "-vf", f"scale={width}:-2", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=40)
        except subprocess.TimeoutExpired:
            raise ValueError("ffmpeg troppo lento (video lontano o enorme)") from None
        if r.returncode == 0 and r.stdout:
            return r.stdout
        err = r.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["nessun fotogramma"]
        err = err[0]
    log.debug("ffmpeg non riesce: %s", err)
    raise ValueError(f"ffmpeg: {err[:120]}")


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def filename_from_cd(cd: str) -> str:
    """Nome del file dall'intestazione Content-Disposition."""
    if not cd:
        return ""
    m = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", cd)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"([^"]+)"', cd) or re.search(r"filename\s*=\s*([^;]+)", cd)
    if m:
        name = m.group(1).strip()
        try:
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return name
    return ""


def unique_name(target: Path, digits: int = 3) -> Path:
    n = 1
    while True:
        cand = target.with_name(f"{target.stem}_{n:0{digits}d}{target.suffix}")
        if not cand.exists():
            return cand
        n += 1
