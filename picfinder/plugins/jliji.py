"""jliji.com: set di foto «/set/<n>» (con le sue pagine «?page=N») e pagine con l'elenco dei set.

Codice nostro, dalle regole del template EPF n. 2258:
  set     la parte dopo <div class="gallery-grid fino ai «related-sets» / </main>; niente miniature («/thumbs/»)
  elenco  la parte dopo <div class="sets-grid">: link ai set e alle pagine «?page=N»
La cartella prende il titolo del set (o il suo numero).
"""
from __future__ import annotations

import re
import sys

from ..core import PluginError, RemoteFile
from ..logs import log
from ._gallery import img_srcs, is_image, links, same_site, title_without, useful_part
from ._kit import clean_name, kit_for, name_from_url

NAME = "jliji"
PREFERRED = True
TESTED = ""
DELAY = (2.0, 5.0)
MAX_PAGES = 200

_SITE = re.compile(r"^https?://(?:www\.)?jliji\.com(?:/|$)", re.I)
_SET = re.compile(r"/set/(\d+)")
_PAGE = re.compile(r"[?&]page=\d+")
_ENDS = (r'<div class="related-sets">', r"</main>")


def match(url: str) -> bool:
    return bool(_SITE.match(url))


def _images(part: str, base: str) -> list[str]:
    out = []
    for u in links(part, base) + img_srcs(part, base):
        if is_image(u) and "/thumbs/" not in u and u not in out:
            out.append(u)
    return out


async def _set(kit, url: str):
    sid = _SET.search(url).group(1)
    first = await kit.fetch(url)
    folder = clean_name(title_without(first.text, "jliji", "jliji.com", "JLiJi")) or sid
    todo, seen, imgs = [first], {first.url, url}, []
    while todo:
        page = todo.pop(0)
        part = useful_part(page.text, (r'<div class="gallery-grid',), _ENDS, drop_img=False)
        imgs += [u for u in _images(part, page.url) if u not in imgs]
        for link in links(useful_part(page.text, (r'<div class="gallery-grid',), _ENDS), page.url):
            s = _SET.search(link)
            if s and s.group(1) == sid and _PAGE.search(link) and link not in seen and len(seen) < MAX_PAGES:
                seen.add(link)
                todo.append(await kit.fetch(link, referer=url))
    log.info("jliji: set «%s», %d foto", folder, len(imgs))
    for u in imgs:
        yield RemoteFile(url=u, name=name_from_url(u), subdir=folder, headers={"Referer": url},
                         meta={"folder_from_title": True, "album": folder})


async def list_files(client, url: str, password: str | None = None):
    kit = kit_for(sys.modules[__name__], client)
    n = 0
    if _SET.search(url):
        async for f in _set(kit, re.sub(r"[?&]page=\d+", "", url)):
            n += 1
            yield f
    else:
        todo, seen, sets = [url], set(), []
        while todo and len(seen) < MAX_PAGES:
            u = todo.pop(0)
            if u in seen:
                continue
            seen.add(u)
            page = await kit.fetch(u)
            part = useful_part(page.text, (r'<div class="sets-grid">',), _ENDS)
            for link in links(part, page.url):
                if not same_site(link, url):
                    continue
                if _SET.search(link):
                    base = re.sub(r"[?&]page=\d+", "", link)
                    if base not in sets:
                        sets.append(base)
                elif _PAGE.search(link) and link not in seen and link not in todo:
                    todo.append(link)
        log.info("jliji: %d pagine di elenco, %d set", len(seen), len(sets))
        for s in sets:
            try:
                async for f in _set(kit, s):
                    n += 1
                    yield f
            except PluginError as e:
                log.warning("  ✗ %s: %s", s, e)
    if not n:
        raise PluginError("jliji: nessuna foto trovata (pagina vuota o cambiata)")
