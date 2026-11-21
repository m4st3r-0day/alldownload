"""filester: cartelle e file singoli. Codice nostro (sostituisce il template EPF).

  cartella  /f/<id>   → ogni file è un elemento con onclick «/d/<slug>» e data-name="nome"
                         (sottocartelle: onclick «/f/<id>»; altre pagine: «?page=N»)
  file      POST /v2/api/public/download {"file_slug"} → {"file", "name", "server", "token"}
            → <server>/v2/<file>?token=…&download=true&n=<nome>
La cartella prende il nome della cartella condivisa.
"""
from __future__ import annotations

import html as _html
import re
import sys
from urllib.parse import quote, urlsplit

from ..core import PluginError, RemoteFile
from ..logs import log
from ._kit import clean_name, kit_for, page_title

NAME = "filester"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = "Se te lo chiede, dimostra di essere una persona, poi premi «Continua download»."
BROWSER_USEFUL = r"filester\.[^/]+/(v2/)?api/"
TESTED = "2026-11"
DELAY = (3.0, 5.0)

_RE = re.compile(r"^https?://(?:www\.)?(filester\.[a-z]+)/(f|d)/([^/?#]+)", re.I)
_ITEM = re.compile(r'<[^>]+class="[^"]*\bfile-item\b[^"]*"([^>]*)>', re.I)
_ONCLICK = re.compile(r'''window\.location\.href\s*=\s*['"]/(d|f)/([^'"#?/]+)['"]''')
_DATA_NAME = re.compile(r'data-name="([^"]*)"')
_PAGE = re.compile(r'href="([^"]*[?&]page=(\d+))"')


def match(url: str) -> bool:
    return bool(_RE.match(url))


async def _download_url(kit, origin: str, slug: str, referer: str) -> tuple[str, str]:
    r = await kit.fetch(f"{origin}/v2/api/public/download", "POST", json_body={"file_slug": slug},
                        referer=referer)
    d = r.json()
    if not (d.get("file") and d.get("server") and d.get("token")):
        raise PluginError(d.get("message") or d.get("error") or "filester non ha dato il link del file")
    name = d.get("name") or ""
    url = (f"{d['server'].rstrip('/')}/v2/{quote(d['file'])}?token={quote(str(d['token']))}"
           f"&download=true&n={quote(name)}")
    return url, name


def _items(html: str) -> list[tuple[str, str, str]]:
    """[(«d» o «f», slug, nome)] nell'ordine della pagina."""
    out = []
    for m in _ITEM.finditer(html):
        attrs = m.group(1)
        oc = _ONCLICK.search(attrs)
        if not oc:
            continue
        nm = _DATA_NAME.search(attrs)
        out.append((oc.group(1), oc.group(2), clean_name(_html.unescape(nm.group(1)), 200) if nm else ""))
    if not out:                                   # pagina diversa: basta l'onclick
        out = [(k, s, "") for k, s in _ONCLICK.findall(html)]
    seen, uniq = set(), []
    for it in out:
        if it[:2] not in seen:
            seen.add(it[:2])
            uniq.append(it)
    return uniq


async def _folder(kit, origin, folder_id, folder_name, html_first, url, depth=0):
    visited_pages = set()
    html, page_url = html_first, url
    while True:
        for kind, slug, name in _items(html):
            if kind == "f":
                if depth >= 6:
                    continue
                sub = await kit.fetch(f"{origin}/f/{slug}", referer=page_url)
                sub_name = clean_name(page_title(sub.text, sub.url)) or slug
                async for f in _folder(kit, origin, slug, f"{folder_name}/{sub_name}", sub.text, sub.url, depth + 1):
                    yield f
                continue
            try:
                link, real = await _download_url(kit, origin, slug, page_url)
            except PluginError as e:
                log.warning("  ✗ %s: %s", name or slug, e)
                continue
            yield link, (real or name), folder_name
        nxt = None
        for href, n in _PAGE.findall(html):
            if n not in visited_pages and int(n) > 1:
                nxt = (href, n)
                break
        if not nxt:
            return
        visited_pages.add(nxt[1])
        nurl = _html.unescape(nxt[0])
        if nurl.startswith("?"):
            nurl = f"{origin}/f/{folder_id}{nurl}"
        elif nurl.startswith("/"):
            nurl = origin + nurl
        page = await kit.fetch(nurl, referer=page_url)
        html, page_url = page.text, page.url


async def list_files(client, url: str, password: str | None = None, session=None):
    m = _RE.match(url)
    if not m:
        raise PluginError("Non è un link filester")
    kit = kit_for(sys.modules[__name__], client, session)
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    kind, slug = m.group(2).lower(), m.group(3)
    if kind == "d":
        link, name = await _download_url(kit, origin, slug, url)
        yield RemoteFile(url=link, name=name or slug, headers={"Referer": origin + "/"})
        return
    if session is not None and session.html and f"/f/{slug}" in (session.final_url or url):
        html, page_url = session.html, session.final_url or url
        log.info("Pagina %s → dal browser", url)
    else:
        p = await kit.fetch(url)
        html, page_url = p.text, p.url
    folder = clean_name(page_title(html, page_url)) or slug
    log.info("filester: cartella «%s»", folder)
    n = 0
    async for link, name, sub in _folder(kit, origin, slug, folder, html, page_url):
        n += 1
        yield RemoteFile(url=link, name=name or f"file_{n}", subdir=sub, headers={"Referer": origin + "/"},
                         meta={"folder_from_title": True, "album": folder})
    if not n:
        raise PluginError("Cartella vuota, o filester ha cambiato la pagina (nessun file trovato)")
