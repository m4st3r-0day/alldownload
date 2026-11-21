"""ImageFap: gallerie e categorie (elenco di gallerie). Codice nostro (sostituisce i template EPF).

  galleria   /pictures/<gid>/<nome>, /gallery/<gid>, /gallery.php?gid=<gid>
             pagine «?gid=…&page=N&view=0» → link «/photo/<id>/» → pagina della foto → immagine intera («/full/»)
  categoria  /pics/<id>/… → link alle gallerie, ognuna nella sua cartella
Il sito è lento con chi va di fretta: pause di 4-7 s tra due pagine (come il template originale).
"""
from __future__ import annotations

import html as _html
import re
import sys
from urllib.parse import urljoin

from ..core import PluginError, RemoteFile
from ..logs import log
from ._kit import clean_name, kit_for, name_from_url, page_title

NAME = "ImageFap"
PREFERRED = True
TESTED = ""
DELAY = (4.0, 7.0)

_GALLERY = re.compile(r"imagefap\.com/(?:pictures/(\d+)|gallery/(\d+)|gallery\.php\?gid=(\d+))", re.I)
_CATEGORY = re.compile(r"imagefap\.com/pics/\d+/", re.I)
_PHOTO = re.compile(r'<a[^>]+href="(/photo/(\d+)/)\?[^"]*"')
_PAGE = re.compile(r'href="([^"]*\?gid=\d+&(?:amp;)?page=(\d+)&(?:amp;)?view=0)"')
_FULL = re.compile(r'''(?:src|href|data-src)=["'](https?://[^"']+/full/[^"']+?\.(?:jpe?g|png|gif|bmp|jfif|webp))''', re.I)
_ALT = re.compile(r'<img[^>]+id="mainPhoto"[^>]*alt="([^"]*)"|<img[^>]+alt="([^"]*)"[^>]*id="mainPhoto"', re.I)
_GAL_LINK = re.compile(r'href="(/(?:gallery\.php\?gid=\d+|pictures/\d+/[^"?#]*|gallery/\d+))"')


def match(url: str) -> bool:
    return bool(_GALLERY.search(url) or _CATEGORY.search(url))


def _gid(url: str) -> str:
    m = _GALLERY.search(url)
    return next(g for g in m.groups() if g) if m else ""


async def _gallery(kit, url: str, folder: str | None = None):
    gid = _gid(url)
    first = await kit.fetch(url)
    title = re.sub(r"\s+Porn Pics.*$", "", page_title(first.text, first.url), flags=re.I)
    name = folder or clean_name(title) or gid
    log.info("ImageFap: galleria «%s»", name)
    pages, done, queue = {first.url: first.text}, set(), []
    html = first.text
    photos: list[str] = []
    while True:
        for href, _pid in _PHOTO.findall(html):
            if href not in photos:
                photos.append(href)
        for href, n in _PAGE.findall(html):
            full = urljoin(first.url, _html.unescape(href))
            if full not in pages and full not in queue:
                queue.append(full)
        if not queue:
            break
        nxt = queue.pop(0)
        if nxt in done:
            continue
        done.add(nxt)
        html = (await kit.fetch(nxt, referer=first.url)).text
        pages[nxt] = html
    for href in photos:
        try:
            p = await kit.fetch(urljoin(first.url, href), referer=first.url)
        except PluginError as e:
            log.warning("  ✗ %s: %s", href, e)
            continue
        m = _FULL.search(p.text)
        if not m:
            log.debug("  nella pagina %s non trovo l'immagine intera", href)
            continue
        img = _html.unescape(m.group(1))
        alt = _ALT.search(p.text)
        nm = clean_name(next((g for g in alt.groups() if g), ""), 200) if alt else ""
        ext = name_from_url(img).rsplit(".", 1)[-1] if "." in name_from_url(img) else "jpg"
        fname = (nm if nm.lower().endswith("." + ext.lower()) else f"{nm}.{ext}") if nm else name_from_url(img)
        yield RemoteFile(url=img, name=fname, subdir=name, headers={"Referer": p.url},
                         meta={"folder_from_title": True, "album": name})


async def list_files(client, url: str, password: str | None = None):
    kit = kit_for(sys.modules[__name__], client)
    n = 0
    if _CATEGORY.search(url) and not _GALLERY.search(url):
        cat = await kit.fetch(url)
        links = list(dict.fromkeys(_GAL_LINK.findall(cat.text)))
        log.info("ImageFap: categoria con %d gallerie", len(links))
        for href in links:
            async for f in _gallery(kit, urljoin(cat.url, _html.unescape(href))):
                n += 1
                yield f
    else:
        async for f in _gallery(kit, url):
            n += 1
            yield f
    if not n:
        raise PluginError("ImageFap: nessuna immagine trovata (galleria vuota o pagina cambiata)")
