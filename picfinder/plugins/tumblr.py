"""Tumblr: tutti i post di un blog. Codice nostro (sostituisce il template EPF).

La pagina del blog chiede a …/api/v2/blog/<blog>/posts?… i post, con «authorization» (token del sito).
Il plugin parte da quella richiesta e segue «links.next.href». Per ogni immagine prende la misura più grande.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urlsplit

from ..core import PluginError, RemoteFile
from ..logs import log
from ._kit import clean_name, kit_for, name_from_url

NAME = "Tumblr"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = "Aspetta che si vedano i post del blog, poi premi «Continua download»."
BROWSER_USEFUL = r"tumblr\.com/(api/)?v2/blog/[^/]+/posts\?"
TESTED = ""
DELAY = (1.5, 3.0)

_RE = re.compile(r"^https?://(?:(?:www\.)?tumblr\.com/([^/?#]+)/?$|([^/.]+)\.tumblr\.com/(archive)?)", re.I)
_HEADERS = ("authorization", "x-version", "accept", "x-ad-blocker-enabled")
_SKIP = {"avatar", "post_author_avatar", "theme", "poster", "blog"}


def match(url: str) -> bool:
    return bool(_RE.match(url))


def _media(o, out: list, depth=0):
    if depth > 14:
        return
    if isinstance(o, dict):
        t = o.get("type")
        if t == "image" and isinstance(o.get("media"), list) and o["media"]:
            best = max(o["media"], key=lambda m: (m.get("width") or 0) * (m.get("height") or 0))
            if best.get("url"):
                out.append(best["url"])
            return
        if t == "video":
            media = o.get("media")
            u = o.get("url") or (media.get("url") if isinstance(media, dict) else None)
            if u and not re.search(r"(youtube|vimeo|instagram)\.", u):
                out.append(u)
            return
        for k, v in o.items():
            if k not in _SKIP and isinstance(v, (dict, list)):
                _media(v, out, depth + 1)
    elif isinstance(o, list):
        for v in o:
            _media(v, out, depth + 1)


async def list_files(client, url: str, password: str | None = None, session=None):
    m = _RE.match(url)
    blog = clean_name((m.group(1) or m.group(2)) if m else "")
    if session is None:
        raise PluginError("Tumblr: serve il browser interno (la pagina del blog aperta).")
    kit = kit_for(sys.modules[__name__], client, session)
    first = next(iter(kit.captured(BROWSER_USEFUL)), None)
    if first is None:
        raise PluginError("Tumblr: il browser non ha caricato i post. Aspetta che si vedano e riprova.")
    headers = kit.copy_headers(BROWSER_USEFUL, _HEADERS)
    p = urlsplit(first.url)
    prefix = f"{p.scheme}://{p.netloc}" + (p.path.split("/v2/")[0] if "/v2/" in p.path else "")
    page_url, pages, seen, n = first.url, 0, set(), 0
    while page_url and pages < 2000:
        pages += 1
        r = await kit.fetch(page_url, headers=headers, referer="https://www.tumblr.com/")
        d = r.json().get("response") or {}
        urls: list = []
        _media(d.get("posts") or [], urls)
        for u in urls:
            if u in seen:
                continue
            seen.add(u)
            n += 1
            yield RemoteFile(url=u, name=name_from_url(u), subdir=blog, meta={"folder_from_title": True, "album": blog})
        nxt = ((d.get("links") or {}).get("next") or {}).get("href")
        page_url = (prefix + nxt) if nxt and nxt.startswith("/") else nxt
    log.info("Tumblr: %d file in %d pagine", n, pages)
    if not n:
        raise PluginError("Tumblr: nessuna foto o video trovato nei post.")
