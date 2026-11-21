"""gedecomix.com: fumetti «/porncomic/<fumetto>/», capitoli «/porncomic/<fumetto>/<capitolo>/» ed elenchi.

Codice nostro, dalle regole del template EPF n. 2254 (sito fatto con il tema «WP-manga»):
  capitolo  la parte dopo <div class="reading-content"> fino alla barra di navigazione in basso:
            le pagine sono immagini in «/static/WP-manga/data/», salvate come 001, 002, … nell'ordine
  fumetto   la parte dopo <ul class="main version-chap: link ai capitoli
            (se l'elenco arriva dopo, si chiede come fa la pagina: POST <fumetto>/ajax/chapters/)
  elenco    la parte dopo <div id="loop-content": link ai fumetti e alle pagine «/page/<n>/»
Cartelle: <fumetto>/<capitolo>.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urlsplit

from ..core import PluginError, RemoteFile
from ..logs import log
from ._gallery import img_srcs, links, same_site, title_without, useful_part
from ._kit import clean_name, kit_for

NAME = "gedecomix"
PREFERRED = True
TESTED = "2026-11"
DELAY = (2.0, 5.0)
MAX_LIST_PAGES = 200

_SITE = re.compile(r"^https?://(?:www\.)?gedecomix\.com(?:/|$)", re.I)
_COMIC = re.compile(r"/porncomic/([^/?#]+)/?$")
_CHAPTER = re.compile(r"/porncomic/([^/?#]+)/([^/?#]+)/?$")
_LIST_PAGE = re.compile(r"/page/\d+/?$")
_DATA = re.compile(r"/static/WP-manga/data/", re.I)


def match(url: str) -> bool:
    return bool(_SITE.match(url))


def _path(url: str) -> str:
    return urlsplit(url).path


async def _chapter(kit, url: str, comic_name: str | None = None):
    m = _CHAPTER.search(_path(url))
    page = await kit.fetch(url)
    comic = comic_name or clean_name(m.group(1).replace("-", " ")) or m.group(1)
    chap = clean_name(m.group(2).replace("-", " ")) or m.group(2)
    part = useful_part(page.text, (r'<div class="reading-content">',),
                       (r'<div[^<>]+id="manga-reading-nav-foot"', r'<footer class="site-footer">'), drop_img=False)
    imgs = [u for u in img_srcs(part, page.url) if _DATA.search(u)]
    log.info("gedecomix: «%s» / «%s», %d pagine", comic, chap, len(imgs))
    for i, u in enumerate(imgs, 1):
        ext = re.search(r"\.([A-Za-z0-9]{2,5})$", u.split("?")[0])
        yield RemoteFile(url=u, name=f"{i:03d}.{ext.group(1).lower() if ext else 'jpg'}", subdir=f"{comic}/{chap}",
                         headers={"Referer": page.url}, fixed_name=True, meta={"album": comic})


async def _comic(kit, url: str):
    page = await kit.fetch(url)
    slug_ = _COMIC.search(_path(url)).group(1)
    comic = clean_name(title_without(page.text, "Gedecomix", "gedecomix.com")) or slug_
    part = useful_part(page.text, (r'<ul class="main version-chap',), (r'<button id="clear-read-status"',
                                                                       r'<footer class="site-footer">'))
    chapters = [l for l in links(part, page.url) if _CHAPTER.search(_path(l))
                and _CHAPTER.search(_path(l)).group(1) == slug_]
    if not chapters:                                   # elenco dei capitoli caricato dopo (tema WP-manga)
        try:
            ajax = await kit.fetch(url.rstrip("/") + "/ajax/chapters/", "POST", data="", referer=url,
                                   headers={"X-Requested-With": "XMLHttpRequest"})
            chapters = [l for l in links(ajax.text, page.url) if _CHAPTER.search(_path(l))]
        except PluginError as e:
            log.debug("  elenco capitoli via ajax non riuscito: %s", e)
    chapters = list(dict.fromkeys(chapters))[::-1]     # il sito li mostra dal più nuovo: si scarica dal primo
    log.info("gedecomix: «%s», %d capitoli", comic, len(chapters))
    for c in chapters:
        async for f in _chapter(kit, c, comic):
            yield f


async def list_files(client, url: str, password: str | None = None):
    kit = kit_for(sys.modules[__name__], client)
    n = 0
    path = _path(url)
    if _CHAPTER.search(path) and not _LIST_PAGE.search(path):
        gen = _chapter(kit, url)
    elif _COMIC.search(path):
        gen = _comic(kit, url)
    else:
        gen = None
    if gen is not None:
        async for f in gen:
            n += 1
            yield f
    else:
        todo, seen, comics = [url], set(), []
        while todo and len(seen) < MAX_LIST_PAGES:
            u = todo.pop(0)
            if u in seen:
                continue
            seen.add(u)
            page = await kit.fetch(u)
            part = useful_part(page.text, (r'<div id="loop-content"',), (r'<footer class="site-footer">',))
            for link in links(part, page.url):
                if not same_site(link, url):
                    continue
                p = _path(link)
                if _LIST_PAGE.search(p):
                    if link not in seen and link not in todo:
                        todo.append(link)
                elif _COMIC.search(p) and link not in comics:
                    comics.append(link)
        log.info("gedecomix: %d pagine di elenco, %d fumetti", len(seen), len(comics))
        for c in comics:
            try:
                async for f in _comic(kit, c):
                    n += 1
                    yield f
            except PluginError as e:
                log.warning("  ✗ %s: %s", c, e)
    if not n:
        raise PluginError("gedecomix: nessuna pagina trovata (fumetto vuoto o pagina cambiata)")
