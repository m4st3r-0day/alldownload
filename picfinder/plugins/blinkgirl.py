"""blinkgirl.com: articoli con galleria «/<nome>/» e pagine di elenco (home, categorie, «/page/<n>/»).

Codice nostro, dalle regole del template EPF n. 2255:
  articolo  la parte dopo <figure class="wp-block-gallery fino ai commenti / al piè di pagina:
            le foto grandi (link alle immagini, altrimenti le immagini stesse)
  elenco    la parte dopo <div class="tdb_module_loop: link agli articoli e alle pagine «/page/<n>/»
La cartella prende il nome dell'articolo.
"""
from __future__ import annotations

import re
import sys

from ..core import PluginError, RemoteFile
from ..logs import log
from ._gallery import img_srcs, is_image, links, same_site, slug, title_without, useful_part
from ._kit import clean_name, kit_for, name_from_url

NAME = "blinkgirl"
PREFERRED = True
TESTED = "2026-11"
DELAY = (2.0, 5.0)
MAX_LIST_PAGES = 200

_SITE = re.compile(r"^https?://(?:www\.)?blinkgirl\.com(?:/|$)", re.I)
_POST = re.compile(r"^https?://(?:www\.)?blinkgirl\.com/([^/?#]+)/?$", re.I)
_LIST_PAGE = re.compile(r"/page/\d+/?$")
_ENDS = (r'<div[^<>]+id="comments"', r'<div class="td-footer-template-wrap"')
_THUMB_SPAN = re.compile(r'<span class="entry-thumb.*?</span>', re.I | re.S)


def match(url: str) -> bool:
    return bool(_SITE.match(url))


async def _post(kit, url: str):
    page = await kit.fetch(url)
    folder = clean_name(title_without(page.text, "BlinkGirl", "blinkgirl.com")) or slug(url)
    part = useful_part(page.text, (r'<figure class="wp-block-gallery',), _ENDS, drop_img=False)
    part = _THUMB_SPAN.sub("", part)
    imgs = [u for u in links(part, page.url) if is_image(u)] or [u for u in img_srcs(part, page.url) if is_image(u)]
    log.info("blinkgirl: «%s», %d foto", folder, len(imgs))
    for u in imgs:
        yield RemoteFile(url=u, name=name_from_url(u), subdir=folder, headers={"Referer": page.url},
                         meta={"folder_from_title": True, "album": folder})


async def list_files(client, url: str, password: str | None = None):
    kit = kit_for(sys.modules[__name__], client)
    n = 0
    m = _POST.match(url.split("?")[0])
    if m and m.group(1) != "page":
        async for f in _post(kit, url):
            n += 1
            yield f
    else:
        todo, seen, posts = [url], set(), []
        while todo and len(seen) < MAX_LIST_PAGES:
            u = todo.pop(0)
            if u in seen:
                continue
            seen.add(u)
            page = await kit.fetch(u)
            part = useful_part(page.text, (r'<div class="tdb_module_loop',), _ENDS)
            for link in links(part, page.url):
                if not same_site(link, url):
                    continue
                if _LIST_PAGE.search(link.split("?")[0]):
                    if link not in seen and link not in todo:
                        todo.append(link)
                elif _POST.match(link) and link not in posts:
                    posts.append(link)
        log.info("blinkgirl: %d pagine di elenco, %d articoli", len(seen), len(posts))
        for p in posts:
            try:
                async for f in _post(kit, p):
                    n += 1
                    yield f
            except PluginError as e:
                log.warning("  ✗ %s: %s", p, e)
    if not n:
        raise PluginError("blinkgirl: nessuna foto trovata (pagina vuota o cambiata)")
