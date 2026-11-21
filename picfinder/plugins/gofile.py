"""Gofile: cartelle e sottocartelle. Codice nostro (sostituisce il template EPF).

Serve il browser interno: la pagina chiede a api.gofile.io/contents/<id> l'elenco, con le intestazioni
«authorization» (token ospite) e «x-website-token». Il plugin le copia e chiede le sottocartelle allo
stesso modo. I server dei file vogliono il token come cookie «accountToken» (lo aggiunge il download).
La cartella prende il nome della cartella condivisa; le sottocartelle restano sotto.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit

from ..core import PluginError, RemoteFile
from ..logs import log
from ._kit import clean_name, kit_for

NAME = "Gofile"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = "Aspetta di vedere i file della cartella, poi premi «Continua download»."
BROWSER_USEFUL = r"api\.gofile\.io/"
TESTED = "2026-11"
DELAY = (1.0, 2.0)

API = "https://api.gofile.io"
_RE = re.compile(r"^https?://(?:www\.)?gofile\.io/d/([A-Za-z0-9-]+)", re.I)
_HEADERS = ("authorization", "x-website-token", "x-bl", "accept")


def match(url: str) -> bool:
    return bool(_RE.match(url))


def _contents_url(cid: str, page: int, template_query: str) -> str:
    """Stessi parametri della richiesta del browser; «page» solo se il sito la usa."""
    q = dict(parse_qsl(template_query)) if template_query else \
        {"page": "1", "pageSize": "100", "sortField": "name", "sortDirection": "1"}
    if "page" in q or page > 1:
        q["page"] = str(page)
    return f"{API}/contents/{cid}?{urlencode(q)}"


async def list_files(client, url: str, password: str | None = None, session=None):
    m = _RE.match(url)
    if not m:
        raise PluginError("Non è un link Gofile")
    root_id = m.group(1)
    kit = kit_for(sys.modules[__name__], client, session)
    headers = kit.copy_headers(r"api\.gofile\.io/contents/", _HEADERS)
    if "authorization" not in headers:
        raise PluginError("Gofile: manca il token del browser interno. Apri il link nel browser e aspetta "
                          "di vedere i file prima di «Continua download».")
    headers["origin"] = "https://gofile.io"
    first = next((r for r in kit.captured(r"api\.gofile\.io/contents/" + re.escape(root_id))), None)
    tq = urlsplit(first.url).query if first else ""
    if password:
        import hashlib
        tq = urlencode(dict(parse_qsl(tq), password=hashlib.sha256(password.encode()).hexdigest()))
    root_name = ""
    stack = [(root_id, "")]
    seen = set()
    n = 0
    while stack:
        cid, path = stack.pop(0)
        if cid in seen:
            continue
        seen.add(cid)
        page = 1
        while True:
            # la prima pagina della cartella principale c'è già (risposta del browser): stesso indirizzo
            u = first.url if (first is not None and cid == root_id and page == 1) else _contents_url(cid, page, tq)
            r = await kit.fetch(u, headers=headers, referer="https://gofile.io/")
            d = r.json()
            if d.get("status") != "ok":
                st = d.get("status", "?")
                if "password" in st:
                    raise PluginError("Gofile: la cartella ha la password (mettila nel campo Password)")
                raise PluginError(f"Gofile risponde «{st}»")
            data = d.get("data") or {}
            if cid == root_id and not root_name:
                root_name = clean_name(data.get("name") or "") or root_id
                path = root_name
                log.info("Gofile: cartella «%s»", root_name)
            children = data.get("children") or {}
            items = children.values() if isinstance(children, dict) else children
            for ch in items:
                if ch.get("type") == "folder":
                    stack.append((ch.get("id"), f"{path}/{clean_name(ch.get('name') or ch.get('id'))}"))
                elif ch.get("type") == "file" and ch.get("link"):
                    n += 1
                    yield RemoteFile(url=ch["link"], name=clean_name(ch.get("name") or "", 200) or f"file_{n}",
                                     subdir=path, size=ch.get("size"),
                                     headers={"Referer": "https://gofile.io/"}, thumb=ch.get("thumbnail") or "",
                                     meta={"folder_from_title": True, "album": root_name})
            meta = data.get("metadata") or {}
            more = meta.get("hasNextPage") or (meta.get("totalPages") and page < int(meta["totalPages"]))
            if not more:
                break
            page += 1
    if not n:
        raise PluginError("Cartella Gofile vuota (o i file non sono disponibili)")
