"""av01.media: pagina di un video → video HLS salvato come .mp4 (con ffmpeg).

Codice nostro, dalle regole del template EPF n. 2252:
  1. il lettore della pagina chiede «/api/v1/videos/<id>/cdn-access?token_v2=…» (il token lo calcola la pagina:
     per questo si apre il browser interno e si prende la risposta che ha ricevuto lui)
  2. la risposta ha «access_token» → «/api/v1/videos/<id>/manifest/master.m3u8?access_token=…»
  3. il video HLS si scarica con ffmpeg (qualità più alta). I video cifrati non si scaricano (regola dell'app).
"""
from __future__ import annotations

import json
import re
import sys

from ..core import PluginError, RemoteFile
from ..logs import log
from ._gallery import title_without
from ._kit import clean_name, kit_for

NAME = "av01 (video)"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = "Aspetta che la pagina e il lettore video siano caricati del tutto, poi premi «Continua download»."
BROWSER_USEFUL = r"/api/v1/videos/\d+/cdn-access"
TESTED = ""
DELAY = (2.0, 5.0)

ORIGIN = "https://www.av01.media"
_SITE = re.compile(r"^https?://(?:www\.)?av01\.media/", re.I)
_VIDEO_ID = re.compile(r"/video/(\d+)")
_ACCESS = re.compile(r"/(api/v1/videos/(\d+))/cdn-access\?")
_TOKEN = re.compile(r'"access_token"\s*:\s*"([^"]+)"')


def match(url: str) -> bool:
    return bool(_SITE.match(url))


async def list_files(client, url: str, password: str | None = None, session=None):
    kit = kit_for(sys.modules[__name__], client, session)
    want = _VIDEO_ID.search(url)
    reqs = [r for r in kit.captured(r"/api/v1/videos/\d+/cdn-access\?") if _ACCESS.search(r.url)]
    if want:
        reqs = [r for r in reqs if _ACCESS.search(r.url).group(2) == want.group(1)] or reqs
    if not reqs:
        raise PluginError("av01: il lettore video non ha ancora chiesto il permesso al server. Apri la pagina del "
                          "video nel browser interno, aspetta che il lettore sia pronto, poi «Continua download».")
    title = ""
    if session is not None and session.html:
        title = clean_name(title_without(session.html, "AV01", "av01.media", "AV01.media"))
    done = set()
    for r in reqs:
        api, vid = _ACCESS.search(r.url).groups()
        if vid in done:
            continue
        text = r.text or ""
        if not _TOKEN.search(text):                       # risposta non catturata: la chiedo con gli stessi dati
            hdr = {k: v for k, v in r.headers.items() if k in ("authorization", "accept", "x-requested-with")}
            text = (await kit.fetch(r.url, headers=hdr, referer=url)).text
        m = _TOKEN.search(text)
        if not m:
            try:
                log.debug("  risposta cdn-access: %s", json.dumps(json.loads(text))[:300])
            except ValueError:
                pass
            raise PluginError("av01: il server non ha dato il permesso per il video (access_token mancante)")
        done.add(vid)
        manifest = f"{ORIGIN}/{api}/manifest/master.m3u8?access_token={m.group(1)}"
        name = f"{title} [{vid}].mp4" if title else f"av01 {vid}.mp4"
        log.info("av01: video %s → HLS", vid)
        yield RemoteFile(url=manifest, name=name, fixed_name=True,
                         headers={"Referer": url, "Origin": ORIGIN}, opts={"conflicts": "do_not_save"})
