"""Koofr: conversione del template EPF n. 1814, con il bug delle sottocartelle corretto.
Tutto finisce in una cartella col nome del link condiviso (non col suo codice). Provato a novembre 2026.

API usate (le stesse del template EPF):
  elenco cartella:  {base}/api/v2/public/links/{id}/bundle?path=/percorso[&password=...]
  download file:    {base}/content/links/{id}/files/get/{nome}?path=/percorso/nome
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

import httpx

from ..core import PluginError, RemoteFile

NAME = "Koofr"
PREFERRED = True   # passa davanti al template .etmpl: qui la cartella prende il nome del link condiviso

# app.koofr.net/links/<id>, app.koofr.eu/links/<id>, link brevi k00.fr/<code>
_LINK_RE = re.compile(r"^https?://app\.koofr\.[a-z]+/links/([^/?#]+)", re.I)
_SHORT_RE = re.compile(r"^https?://k00\.fr/[^/?#]+", re.I)


def match(url: str) -> bool:
    return bool(_LINK_RE.match(url) or _SHORT_RE.match(url))


async def _resolve(client: httpx.AsyncClient, url: str) -> tuple[str, str]:
    """Restituisce (base, link_id). I link brevi k00.fr vengono seguiti."""
    if _SHORT_RE.match(url):
        r = await client.get(url)
        url = str(r.url)
    m = _LINK_RE.match(url)
    if not m:
        raise PluginError("Link Koofr non riconosciuto.")
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}", m.group(1)


async def _link_name(client: httpx.AsyncClient, base: str, link_id: str, referer: str,
                     password: str | None) -> str:
    """Nome della cartella condivisa (es. «Vacanze 2024»), dalle informazioni del link."""
    try:
        params = {"password": password} if password else None
        r = await client.get(f"{base}/api/v2/public/links/{link_id}", params=params,
                             headers={"Referer": referer})
        if r.status_code == 200:
            name = (r.json() or {}).get("name") or ""
            if name.strip() and name.strip() != "/":
                return name.strip()
    except (httpx.HTTPError, ValueError):
        pass
    return ""


def _clean(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name).strip(" .-")[:120]


async def list_files(client: httpx.AsyncClient, url: str, password: str | None = None):
    base, link_id = await _resolve(client, url)
    referer = f"{base}/links/{link_id}"
    pw = f"&password={quote(password, safe='')}" if password else ""
    root = _clean(await _link_name(client, base, link_id, referer, password))

    async def walk(path: str):
        params = {"path": path}
        if password:
            params["password"] = password
        r = await client.get(f"{base}/api/v2/public/links/{link_id}/bundle",
                             params=params, headers={"Referer": referer})
        if r.status_code in (401, 403):
            raise PluginError("Il link è protetto: password mancante o errata.")
        if r.status_code == 404:
            raise PluginError("Link Koofr inesistente o scaduto.")
        r.raise_for_status()
        data = r.json()
        nonlocal root
        if not root and path == "/":          # riserva: il nome della cartella principale dall'elenco
            root = _clean(((data.get("file") or {}).get("name") or "").strip("/")) or link_id

        for item in data.get("files", []):
            name = item["name"]
            child = f"{path.rstrip('/')}/{name}"     # percorso COMPLETO (fix bug EPF)
            if item.get("type") == "dir":
                async for f in walk(child):
                    yield f
            elif item.get("type") == "file":
                yield RemoteFile(
                    url=(f"{base}/content/links/{link_id}/files/get/{quote(name, safe='')}"
                         f"?path={quote(child, safe='')}{pw}"),
                    name=name,
                    subdir="/".join(x for x in (root, path.strip("/")) if x),
                    size=item.get("size"),
                    headers={"Referer": referer},
                    meta={"folder_from_title": True},   # niente cartella in più col codice del link
                )

    async for f in walk("/"):
        yield f


TESTED = "2026-11"
