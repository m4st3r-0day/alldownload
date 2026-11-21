"""happymodal.com: gallerie «/p/<n>/» e pagine con l'elenco delle gallerie (home, tag, «/page/<n>/»).

Codice nostro, dalle regole del template EPF n. 2269:
  galleria  la parte dopo <div class="gallery"> fino a <aside / <footer, senza <img>: i link sono le foto grandi
  elenco    la parte dopo <div class="grid" data-lib-grid>: link alle gallerie «/p/<n>/» e alle pagine «/page/<n>/»
La cartella prende il titolo della galleria.
"""
from __future__ import annotations

import re
import sys

from ..core import PluginError, RemoteFile
from ..logs import log
from ._gallery import links, same_site, title_without, useful_part
from ._kit import clean_name, kit_for, name_from_url

NAME = "happymodal"
PREFERRED = True
TESTED = "2026-11"
DELAY = (2.0, 3.0)
MAX_LIST_PAGES = 200

_SITE = re.compile(r"^https?://(?:www\.)?happymodal\.com(?:/|$)", re.I)
_GALLERY = re.compile(r"/p/\d+/?$")
_LIST_PAGE = re.compile(r"/page/\d+/?$")
_IMAGE = re.compile(r"\.(?:jpe?g|png|gif|webp)$", re.I)
_ENDS = (r"<aside\b", r"<footer\b")


def match(url: str) -> bool:
    return bool(_SITE.match(url))


def _is_image(u: str) -> bool:
    return bool(_IMAGE.search(u.split("?")[0]))


async def _gallery(kit, url: str):
    page = await kit.fetch(url)
    folder = clean_name(title_without(page.text, "HappyModal", "happymodal.com", "Happy Modal")) \
        or url.rstrip("/").rsplit("/", 1)[-1]
    part = useful_part(page.text, (r'<div class="gallery"',), _ENDS)
    imgs = [u for u in links(part, page.url) if _is_image(u)]
    log.info("happymodal: galleria «%s», %d foto", folder, len(imgs))
    for u in imgs:
        yield RemoteFile(url=u, name=name_from_url(u), subdir=folder, headers={"Referer": page.url},
                         meta={"folder_from_title": True, "album": folder})


async def list_files(client, url: str, password: str | None = None):
    kit = kit_for(sys.modules[__name__], client)
    n = 0
    path = url.split("?")[0]
    if _GALLERY.search(path):
        async for f in _gallery(kit, url):
            n += 1
            yield f
    else:                                   # elenco di gallerie, con tutte le sue pagine
        todo, seen, galleries = [url], set(), []
        while todo and len(seen) < MAX_LIST_PAGES:
            u = todo.pop(0)
            if u in seen:
                continue
            seen.add(u)
            page = await kit.fetch(u)
            part = useful_part(page.text, (r'<div class="grid" data-lib-grid',), _ENDS)
            for link in links(part, page.url):
                if not same_site(link, url):
                    continue
                p = link.split("?")[0]
                if _GALLERY.search(p) and link not in galleries:
                    galleries.append(link)
                elif _LIST_PAGE.search(p) and link not in seen and link not in todo:
                    todo.append(link)
        log.info("happymodal: %d pagine di elenco, %d gallerie", len(seen), len(galleries))
        for g in galleries:
            try:
                async for f in _gallery(kit, g):
                    n += 1
                    yield f
            except PluginError as e:
                log.warning("  ✗ %s: %s", g, e)
    if not n:
        raise PluginError("happymodal: nessuna foto trovata (pagina vuota o cambiata)")
