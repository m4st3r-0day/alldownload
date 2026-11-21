"""Bunkr: album e file singoli, foto e video. Codice nostro (sostituisce il template EPF).

Come fa il pulsante «Download» del sito (novembre 2026):
  1. pagina del file  /f/<slug>      → link «https://dl.bunkr…/file/<id>»
  2. POST <dl>/api/_001_v2 {"id"}    → {"mediafiles": server, "path": percorso, "original": nome}
     (formato vecchio: {"encrypted": true, "timestamp", "url": base64 cifrato XOR})
  3. GET  glb-apisign.cdn.cr/sign?path=<percorso> → {"token", "ex"}
  4. file: <server><percorso>?n=<nome>&token=…&ex=…

Album: per le FOTO l'elenco «gallery» (POST /api/album/gallery {"slug"}) dà subito il numero di ogni file,
così si salta la pagina /f/ di ciascuna. I video passano sempre dalla pagina del file.
La cartella prende il nome dell'album.
"""
from __future__ import annotations

import base64
import re
import sys
from urllib.parse import quote, urlencode, urlsplit

from ..core import PluginError, RemoteFile
from ..logs import log
from ._kit import clean_name, kit_for, name_from_url, page_title

NAME = "Bunkr"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = "Aspetta di vedere il contenuto dell'album, poi premi «Continua download»."
BROWSER_USEFUL = r"bunkr[^/]*/api/"
TESTED = "2026-11"
DELAY = (2.0, 3.0)

SIGN = "https://glb-apisign.cdn.cr/sign"
_RE = re.compile(r"^https?://(?:[^/]+\.)?(bunkrr?[^/.]*\.[a-z]{2,})/(a|f|v|i|d)/([^/?#]+)", re.I)
_DL = re.compile(r'href="(https://[^"]+?)/file/(\d+)"')
_FILE_HREF = re.compile(r'href="(/f/[A-Za-z0-9_-]+)"')
_NAME = re.compile(r'class="[^"]*\btheName\b[^"]*"[^>]*>([^<]+)<')
_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".jfif", ".heic")


def match(url: str) -> bool:
    return bool(_RE.match(url))


def decrypt_old(data: dict) -> str:
    """Formato vecchio della API: indirizzo cifrato con XOR, chiave «SECRET_KEY_<ora>»."""
    link = data.get("url", "")
    if data.get("encrypted") and link:
        raw = base64.b64decode(link)
        key = f"SECRET_KEY_{int(data.get('timestamp', 0)) // 3600}".encode()
        link = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode("utf-8", "replace")
    return link


async def _file_url(kit, dl_base: str, fid: str, referer: str) -> tuple[str, str]:
    """Numero del file → (indirizzo del file firmato, nome originale)."""
    api = await kit.fetch(f"{dl_base}/api/_001_v2", "POST", json_body={"id": str(fid)}, referer=referer)
    data = api.json()
    if data.get("mediafiles") and data.get("path"):
        path, original = data["path"], data.get("original") or ""
        sig = await kit.fetch(f"{SIGN}?{urlencode({'path': path}, quote_via=quote)}", referer=referer)
        s = sig.json()
        if not s.get("token"):
            raise PluginError("Bunkr non ha dato il permesso per il file (firma mancante)")
        q = {"n": original} if original else {}
        q.update(token=str(s["token"]), ex=str(s.get("ex", "")))
        return f"{data['mediafiles'].rstrip('/')}{quote(path)}?{urlencode(q, quote_via=quote)}", original
    link = decrypt_old(data)
    if not link.startswith("http"):
        raise PluginError("Bunkr ha cambiato la risposta della sua API: il plugin va aggiornato")
    return link, ""


async def _from_file_page(kit, origin: str, slug_path: str, referer: str):
    page = await kit.fetch(origin + slug_path, referer=referer)
    m = _DL.search(page.text)
    if not m:
        log.warning("  Bunkr: nella pagina %s non trovo il link di download", slug_path)
        return None
    return m.group(1), m.group(2), page.url


def _album_items(html: str) -> list[tuple[str, str]]:
    """[(«/f/slug», nome)] nell'ordine della pagina. Il nome può mancare."""
    hrefs = list(dict.fromkeys(_FILE_HREF.findall(html)))
    names = [clean_name(n, 200) for n in _NAME.findall(html)]
    if len(names) == len(hrefs):
        return list(zip(hrefs, names))
    return [(h, "") for h in hrefs]


async def list_files(client, url: str, password: str | None = None, session=None):
    m = _RE.match(url)
    if not m:
        raise PluginError("Non è un link Bunkr")
    kit = kit_for(sys.modules[__name__], client, session)
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    kind, slug = m.group(2).lower(), m.group(3)

    if kind != "a":                                          # file singolo
        hit = await _from_file_page(kit, origin, f"/f/{slug}", url)
        if hit:
            dl_base, fid, ref = hit
            link, original = await _file_url(kit, dl_base, fid, ref)
            yield RemoteFile(url=link, name=original or name_from_url(link), headers={"Referer": origin + "/"})
        return

    # album: pagina (dal browser se c'è), titolo, elenco dei file
    if session is not None and session.html and "/a/" in (session.final_url or url):
        html = session.html
        log.info("Pagina %s → dal browser", url)
    else:
        html = (await kit.fetch(url)).text
    album = page_title(html, url) or slug
    items = _album_items(html)
    log.info("Bunkr: album «%s», %d file", album, len(items))
    if not items:
        raise PluginError("Album vuoto, o Bunkr ha cambiato la pagina (nessun link /f/ trovato)")
    meta = {"folder_from_title": True, "album": album}

    # foto: elenco «gallery» con i numeri dei file (salta la pagina /f/ di ognuna)
    photo_ids: dict[str, str] = {}
    if any(n.lower().endswith(_IMAGE_EXT) for _, n in items):
        try:
            g = await kit.fetch(f"{origin}/api/album/gallery", "POST", json_body={"slug": slug}, referer=url)
            for it in (g.json().get("data") or []):
                if it.get("id") and it.get("name"):
                    photo_ids.setdefault(clean_name(str(it["name"]), 200), str(it["id"]))
            log.info("  elenco «gallery»: %d foto con il numero già pronto", len(photo_ids))
        except PluginError as e:
            log.debug("  elenco «gallery» non disponibile: %s", e)
    dl_base = f"{parts.scheme}://dl.{parts.hostname}"

    for href, name in items:
        fid = photo_ids.get(name) if name else None
        ref = origin + href
        link = original = None
        if fid:
            try:
                link, original = await _file_url(kit, dl_base, fid, ref)
            except PluginError as e:
                log.debug("  via veloce non riuscita per %s (%s): uso la pagina del file", name, e)
        if link is None:
            try:
                hit = await _from_file_page(kit, origin, href, url)
                if not hit:
                    continue
                dl_base, fid, ref = hit
                link, original = await _file_url(kit, dl_base, fid, ref)
            except PluginError as e:
                log.warning("  ✗ %s: %s", name or href, e)
                continue
        yield RemoteFile(url=link, name=(original or name or name_from_url(link)), subdir=album,
                         headers={"Referer": origin + "/"}, meta=dict(meta))
