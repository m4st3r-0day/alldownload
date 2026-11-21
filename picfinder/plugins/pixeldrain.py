"""pixeldrain: usa l'API pubblica invece del template EPF.

Con il template EPF il motore deve aprire ogni file per scoprire come si chiama
(un file alla volta, con la pausa del template): lento. L'API restituisce tutta la
lista in una sola richiesta, con nomi, dimensioni e miniature.

  lista:     GET /api/list/<id>        -> {"title": ..., "files": [{"id", "name", "size", ...}]}
  file:      GET /api/file/<id>/info   -> {"id", "name", "size", ...}
  download:  GET /api/file/<id>?download
  miniatura: GET /api/file/<id>/thumbnail   (anche per i video)
"""
from __future__ import annotations

import re

import httpx

from ..core import PluginError, RemoteFile
from ..logs import log

NAME = "pixeldrain (API)"
PREFERRED = True   # ha la precedenza su un template .etmpl di pixeldrain
TESTED = "2026-11"

_RE = re.compile(r"^https?://(?:www\.)?(pixeldrain\.(?:com|net)|pixeldra\.in)/(l|u)/([A-Za-z0-9]+)", re.I)


def match(url: str) -> bool:
    return bool(_RE.match(url))


def _clean(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name or "").strip(" .-")[:120]


def _file(base: str, item: dict, folder: str) -> RemoteFile:
    fid = item["id"]
    return RemoteFile(
        meta={"folder_from_title": True, "album": folder} if folder else {},
        url=f"{base}/api/file/{fid}?download",
        name=item.get("name") or fid,
        size=item.get("size"),
        subdir=folder,
        headers={"Referer": f"{base}/"},
        fixed_name=True,
        thumb=f"{base}/api/file/{fid}/thumbnail",
    )


async def _get_json(client: httpx.AsyncClient, url: str) -> dict:
    log.debug("→ GET %s", url)
    r = await client.get(url)
    log.info("API %s → %d, %.1f KB", url, r.status_code, len(r.content) / 1024)
    if r.status_code == 404:
        raise PluginError("Lista o file pixeldrain non trovato (link sbagliato o cancellato).")
    if r.status_code in (401, 403):
        raise PluginError("pixeldrain rifiuta l'accesso a questo link.")
    r.raise_for_status()
    data = r.json()
    if data.get("success") is False:
        raise PluginError(f"pixeldrain: {data.get('message') or data.get('value') or 'errore'}")
    return data


async def list_files(client: httpx.AsyncClient, url: str, password: str | None = None):
    m = _RE.match(url)
    if not m:
        raise PluginError("Link pixeldrain non riconosciuto.")
    host, kind, ident = m.groups()
    base = f"https://{host}"
    if kind == "l":
        data = await _get_json(client, f"{base}/api/list/{ident}")
        items = data.get("files") or []
        log.info("Lista «%s»: %d file", data.get("title") or ident, len(items))
        folder = _clean(data.get("title") or "") or ident      # nome della lista, non il suo codice
        for item in items:
            yield _file(base, item, folder)
    else:
        info = await _get_json(client, f"{base}/api/file/{ident}/info")
        yield _file(base, info, "")
