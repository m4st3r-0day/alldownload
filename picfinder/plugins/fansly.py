"""Fansly: media del profilo. Codice nostro (sostituisce il template EPF). Solo il tuo account.

La pagina Media chiede a apiv3.fansly.com …/mediaoffers/location?…&before=<id>&after=… pagine di media,
con le intestazioni «authorization», «fansly-client-*». Il plugin parte dalla prima pagina vista dal
browser e va avanti con «before=<ultimo id>», con le stesse intestazioni. Si prende solo la versione
intera (non le «variants» ridotte).
"""
from __future__ import annotations

import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..core import PluginError, RemoteFile
from ..logs import log
from ._kit import clean_name, kit_for, name_from_url

NAME = "Fansly"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = "Fai login e apri la pagina Media del profilo; quando vedi i contenuti premi «Continua download»."
BROWSER_USEFUL = r"fansly\.com/api/.+/mediaoffers/location\?"
TESTED = ""
DELAY = (2.0, 4.0)

_RE = re.compile(r"^https?://(?:www\.)?fansly\.com/([^/?#]+)/(media|posts)", re.I)
_HEADERS = ("authorization", "fansly-client-check", "fansly-client-id", "fansly-client-ts",
            "fansly-session-id", "accept")


def match(url: str) -> bool:
    return bool(_RE.match(url))


def _with_before(url: str, before: str) -> str:
    p = urlsplit(url)
    q = dict(parse_qsl(p.query, keep_blank_values=True))
    q["before"] = before
    return urlunsplit(p._replace(query=urlencode(q)))


def _media(resp: dict) -> list[tuple[str, str]]:
    """[(indirizzo, nome)] della versione intera di ogni media di una pagina."""
    out = []
    for am in resp.get("accountMedia") or []:
        m = am.get("media") or {}
        locs = [l.get("location") for l in (m.get("locations") or []) if l.get("location")]
        if locs:
            out.append((locs[0], clean_name(m.get("filename") or "", 200)))
    return out


async def list_files(client, url: str, password: str | None = None, session=None):
    if session is None:
        raise PluginError("Fansly: serve il browser interno (login e pagina Media aperta).")
    kit = kit_for(sys.modules[__name__], client, session)
    first = next(iter(kit.captured(BROWSER_USEFUL)), None)
    if first is None:
        raise PluginError("Fansly: il browser non ha caricato la pagina Media. Aprila e aspetta i contenuti.")
    headers = kit.copy_headers(BROWSER_USEFUL, _HEADERS)
    headers["origin"] = "https://fansly.com"
    page_url, seen_pages, seen, n = first.url, set(), set(), 0
    while page_url not in seen_pages and len(seen_pages) < 500:
        seen_pages.add(page_url)
        r = await kit.fetch(page_url, headers=headers, referer="https://fansly.com/")
        d = r.json()
        resp = d.get("response") or {}
        for link, name in _media(resp):
            if link in seen:
                continue
            seen.add(link)
            n += 1
            yield RemoteFile(url=link, name=name or name_from_url(link), headers={"Referer": "https://fansly.com/"})
        data = resp.get("data") or []
        if not data:
            break
        page_url = _with_before(page_url, str(data[-1].get("id")))
    log.info("Fansly: %d file in %d pagine", n, len(seen_pages))
    if not n:
        raise PluginError("Fansly: nessun file scaricabile (contenuti bloccati o pagina non caricata).")
