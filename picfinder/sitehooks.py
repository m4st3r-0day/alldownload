"""Parser dedicati ("individual parsers" di EPF).

Alcuni siti nascondono gli indirizzi veri (codificati, cifrati...). Un hook riceve
l'indirizzo e il testo di una pagina e restituisce testo extra con gli indirizzi
trovati: il motore li aggiunge alla coda come se fossero nella pagina.
"""
from __future__ import annotations

import base64
import json
import re
from typing import Callable
from urllib.parse import parse_qs, quote, urlencode, urlsplit

Hook = Callable[[str, str], str]
_HOOKS: list[tuple[re.Pattern, Hook]] = []


def hook(url_regex: str):
    def deco(fn: Hook) -> Hook:
        _HOOKS.append((re.compile(url_regex, re.I), fn))
        return fn
    return deco


def covered(template) -> bool:
    """True se c'è un parser dedicato per gli indirizzi che questo template visita."""
    pats = [r.pattern for r in template.included + template.start_res]
    return any(rx.search(p.replace("\\", "")) or rx.pattern.split("[")[0] in p for rx, _ in _HOOKS for p in pats)


def run(url: str, text: str) -> str:
    out = []
    for rx, fn in _HOOKS:
        if rx.search(url):
            try:
                out.append(fn(url, text))
            except Exception:  # noqa: BLE001 - un hook rotto non blocca il download
                pass
    return "\n".join(x for x in out if x)


# Bunkr (2026): la API dà server + percorso; il link si completa con un «token» chiesto al servizio /sign.
# Qui si ricorda server e nome per ogni percorso, finché arriva la risposta di /sign.
_BUNKR_PENDING: dict[str, tuple[str, str]] = {}
BUNKR_SIGN = "https://glb-apisign.cdn.cr/sign"


@hook(r"bunkr[^/]*/api/_001_v2$")
def bunkr_api(url: str, text: str) -> str:
    """Bunkr: la API restituisce dove sta il file.

    Formato nuovo: {"mediafiles": "https://xx.cdn.cr", "path": "/storage/media/<id>.mp4", "original": "nome.mp4"}
                   → poi GET /sign?path=<percorso> dà {"token", "ex"} da aggiungere al link (come il pulsante Download).
    Formato vecchio: {"encrypted": true, "timestamp": 1731590000, "url": "<base64>"} cifrato con XOR,
                   chiave "SECRET_KEY_" + (timestamp // 3600).
    """
    data = json.loads(text)
    if data.get("mediafiles") and data.get("path"):
        path = data["path"]
        _BUNKR_PENDING[path] = (data["mediafiles"].rstrip("/"), data.get("original") or "")
        if len(_BUNKR_PENDING) > 5000:
            _BUNKR_PENDING.pop(next(iter(_BUNKR_PENDING)))
        return f"{BUNKR_SIGN}?{urlencode({'path': path}, quote_via=quote)}"
    link = data.get("url", "")
    if data.get("encrypted"):
        key = f"SECRET_KEY_{int(data['timestamp']) // 3600}".encode()
        raw = base64.b64decode(link + "=" * (-len(link) % 4))
        link = bytes(b ^ key[i % len(key)] for i, b in enumerate(raw)).decode("utf-8", "replace")
    return link


@hook(r"glb-apisign\.cdn\.cr/sign\?")
def bunkr_sign(url: str, text: str) -> str:
    """Risposta di /sign: {"token": ..., "ex": ...} → link finale del file (con il nome originale)."""
    data = json.loads(text)
    path = parse_qs(urlsplit(url).query).get("path", [""])[0]
    host, original = _BUNKR_PENDING.get(path, ("", ""))
    if not (host and data.get("token")):
        return ""
    q = {"n": original} if original else {}
    q.update(token=str(data["token"]), ex=str(data.get("ex", "")))
    return f"{host}{quote(path)}?{urlencode(q, quote_via=quote)}"
