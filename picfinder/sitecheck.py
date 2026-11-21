"""Controllo dei siti: prova a cercare (senza scaricare) un link salvato per ogni sito dei tuoi progetti.

Serve a capire subito se un sito ha cambiato qualcosa: per ogni sito dice «funziona (N file)»,
«0 file» o l'errore. I siti che vogliono il browser interno (login) si saltano: vanno provati a mano.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import plugins
from .core import Downloader, PluginError


@dataclass
class SiteResult:
    site: str
    link: str
    plugin: str
    status: str          # ok | empty | error | skipped
    found: int = 0
    message: str = ""
    seconds: float = 0.0


def links_by_site(projects) -> dict[str, str]:
    """Un link per sito (il più recente), dai progetti salvati."""
    out: dict[str, str] = {}
    for p in sorted(projects, key=lambda p: p.last_run or p.created or 0, reverse=True):
        for link in p.links:
            host = (urlsplit(link).hostname or "").lower().removeprefix("www.")
            if host and host not in out:
                out[host] = link
    return out


async def _check_one(dest, link: str, limit: int = 3, timeout: float = 90) -> tuple[int, str]:
    dl = Downloader(dest, patterns=None)
    found = 0
    msg = ""

    async def run():
        nonlocal found
        for _ in await dl.scan(link):
            found += 1

    try:
        await asyncio.wait_for(run(), timeout)
    except asyncio.TimeoutError:
        msg = "ci mette troppo (oltre 90 s)"
    except PluginError as e:
        msg = str(e)
    return found, msg


def check_sites(projects, dest, on_result=None) -> list[SiteResult]:
    results = []
    for site, link in links_by_site(projects).items():
        p = plugins.find_plugin(link)
        name = getattr(p, "NAME", None) or (getattr(p, "t", None) and p.t.service) or "?"
        if p is None:
            r = SiteResult(site, link, "-", "skipped", message="nessun template o plugin")
        elif plugins.needs_browser(p):
            r = SiteResult(site, link, name, "skipped", message="serve il browser interno: prova a mano")
        else:
            t0 = time.monotonic()
            try:
                n, msg = asyncio.run(_check_one(dest, link))
            except Exception as e:  # noqa: BLE001 - un sito rotto non deve fermare gli altri
                n, msg = 0, f"{type(e).__name__}: {e}"
            status = "error" if msg and not n else ("ok" if n else "empty")
            r = SiteResult(site, link, name, status, n, msg, time.monotonic() - t0)
        results.append(r)
        if on_result:
            on_result(r)
    return results
