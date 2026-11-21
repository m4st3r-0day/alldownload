"""OnlyFans: media del profilo e chat (foto e video sbloccati). Codice nostro (sostituisce i template EPF).

Solo il TUO account e i contenuti a cui hai già accesso. Niente DRM.

Come funziona: nel browser interno fai login e scorri la pagina (Media del profilo, o la galleria
della chat) fino in fondo; la pagina chiede alle API del sito pagine di post/messaggi, firmate
(intestazioni «sign», «time», «app-token»...). Il plugin legge quelle risposte (o le richiede di nuovo
con le stesse intestazioni) e prende la versione intera di ogni foto e video.
I link dei file valgono solo per l'IP del browser: niente proxy.
"""
from __future__ import annotations

import json
import re
import sys

from ..core import PluginError, RemoteFile
from ..logs import log
from ..postproc import json_meta
from ._kit import kit_for, name_from_url
from ._media_json import media_items

NAME = "OnlyFans"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = ("Fai login. Poi scorri la pagina (Media del profilo o galleria della chat) fino in fondo, "
                   "così si caricano tutti i contenuti, e premi «Continua download».")
BROWSER_USEFUL = r"onlyfans\.com/api2/v2/(users/\d+/(posts|medias?)|chats/\d+/(media|messages))"
TESTED = "2026-11"
DELAY = (3.0, 5.0)

_PROFILE = re.compile(r"^https?://(?:www\.)?onlyfans\.com/(?!my/|api2/)([A-Za-z0-9_.-]+)(?:/(media|photos|videos|posts))?/?(?:[?#].*)?$", re.I)
_CHAT = re.compile(r"^https?://(?:www\.)?onlyfans\.com/my/chats/chat/(\d+)", re.I)
_API = re.compile(BROWSER_USEFUL, re.I)


def match(url: str) -> bool:
    return bool(_CHAT.match(url) or _PROFILE.match(url))


async def list_files(client, url: str, password: str | None = None, session=None):
    if session is None:
        raise PluginError("OnlyFans: serve il browser interno (login e pagina caricata).")
    kit = kit_for(sys.modules[__name__], client, session)
    chat = _CHAT.match(url)
    want = re.compile(rf"/api2/v2/chats/{chat.group(1)}/" if chat else r"/api2/v2/users/\d+/(posts|medias?)", re.I)
    reqs = [r for r in session.requests if _API.search(r.url) and want.search(r.url)]
    if not reqs:
        raise PluginError("OnlyFans: il browser non ha caricato i contenuti. Apri la pagina Media (o la galleria "
                          "della chat), scorri fino in fondo e poi premi «Continua download».")
    log.info("OnlyFans: %d pagine di contenuti dal browser", len(reqs))
    stats: dict = {}
    seen = set()
    n = 0
    for r in reqs:
        text = r.text
        if text is None:                         # il browser non ha la risposta: la richiedo uguale
            h = {k: v for k, v in r.headers.items() if k not in ("content-length", "host", "cookie")}
            try:
                text = (await kit.fetch(r.url, r.method, data=r.body, headers=h,
                                        referer="https://onlyfans.com/")).text
            except PluginError as e:
                log.warning("  pagina non riletta (%s): %s", r.url[:80], e)
                continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        meta = json_meta(text)
        for m in media_items(data, stats):
            if m["id"] in seen:
                continue
            seen.add(m["id"])
            n += 1
            yield RemoteFile(url=m["url"], name=name_from_url(m["url"]),
                             headers={"Referer": "https://onlyfans.com/"}, meta=dict(meta.get(m["url"], {})))
    if stats.get("locked"):
        log.info("  %d contenuti bloccati (non sbloccati o senza abbonamento): saltati", stats["locked"])
    if stats.get("drm"):
        log.warning("  %d video protetti da DRM: non si scaricano", stats["drm"])
    if not n:
        raise PluginError("OnlyFans: nessun file scaricabile in quello che il browser ha caricato "
                          "(contenuti bloccati, o pagina non scorsa fino in fondo).")
