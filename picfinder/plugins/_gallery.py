"""Aiuti per i siti «a galleria»: pagina con l'elenco degli album → pagina dell'album → link alle immagini grandi.

Come le «ExcludedPageParts» dei template: si tiene solo la parte utile della pagina (dopo un segno di inizio,
prima di un segno di fine) e si tolgono i tag <img>, così le miniature non finiscono tra i file.
"""
from __future__ import annotations

import html as _html
import re
from urllib.parse import urljoin, urlsplit

_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_HREF = re.compile(r'''<a\b[^>]*?\bhref\s*=\s*["']([^"'#]+)["']''', re.I)


def useful_part(html: str, starts: tuple[str, ...] = (), ends: tuple[str, ...] = (), drop_img: bool = True) -> str:
    """Tiene la pagina dopo l'ultimo segno di inizio trovato e prima del primo segno di fine (regex)."""
    for s in starts:
        m = re.search(s, html, re.I)
        if m:
            html = html[m.start():]
    cut = len(html)
    for e in ends:
        m = re.search(e, html, re.I)
        if m:
            cut = min(cut, m.start())
    html = html[:cut]
    return _IMG_TAG.sub("", html) if drop_img else html


def links(html: str, base: str) -> list[str]:
    """Link <a href> assoluti, senza doppioni, nell'ordine della pagina."""
    out = []
    for h in _HREF.findall(html):
        u = urljoin(base, _html.unescape(h.strip()))
        if u.startswith("http") and u not in out:
            out.append(u)
    return out


def same_site(a: str, b: str) -> bool:
    ha, hb = (urlsplit(x).hostname or "" for x in (a, b))
    return ha.removeprefix("www.") == hb.removeprefix("www.")


def title_without(html: str, *suffixes: str) -> str:
    """Testo di <title> senza il nome del sito in fondo."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    t = _html.unescape(m.group(1)).strip() if m else ""
    for s in suffixes:
        t = re.sub(r"\s*[|–—-]?\s*" + re.escape(s) + r"\s*$", "", t, flags=re.I)
    return t.strip()


_IMG_SRC = re.compile(r'''<img\b[^>]*?\b(?:data-src|data-lazy-src|src)\s*=\s*["']\s*([^"'\s][^"']*?)\s*["']''', re.I)
IMAGE_EXT = re.compile(r"\.(?:jpe?g|png|gif|webp|avif|bmp|jfif)$", re.I)


def is_image(u: str) -> bool:
    return bool(IMAGE_EXT.search(u.split("?")[0].split("#")[0]))


def img_srcs(html: str, base: str) -> list[str]:
    """Indirizzi delle immagini nei tag <img> (data-src prima di src, per le pagine «lazy»)."""
    out = []
    for tag in re.findall(r"<img\b[^>]*>", html, re.I):
        m = re.search(r'''\b(?:data-src|data-lazy-src)\s*=\s*["']\s*([^"']+?)\s*["']''', tag, re.I) or \
            re.search(r'''\bsrc\s*=\s*["']\s*([^"']+?)\s*["']''', tag, re.I)
        if m and not m.group(1).startswith("data:"):
            u = urljoin(base, _html.unescape(m.group(1)))
            if u not in out:
                out.append(u)
    return out


def slug(url: str, index: int = -1) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    try:
        return parts[index]
    except IndexError:
        return ""
