"""Trova foto e video dentro le risposte JSON delle API (OnlyFans, Fansly, Tumblr...).

Regola: si prende la versione intera del file, mai miniature, anteprime o versioni ridotte.
Un media bloccato (non sbloccato / non abbonato) non ha l'indirizzo: si salta e si conta.
Un video protetto da DRM non si scarica (si conta e si avvisa).
"""
from __future__ import annotations

SKIP_KEYS = {"thumb", "thumbnail", "preview", "squarePreview", "avatar", "theme", "poster", "header",
             "variants", "videoSources", "squarePreviews"}
MEDIA_TYPES = {"photo", "video", "gif", "audio", "image"}


def _full_url(d: dict) -> str | None:
    files = d.get("files")
    if isinstance(files, dict):
        full = files.get("full")
        if isinstance(full, dict) and isinstance(full.get("url"), str):
            return full["url"]
    src = d.get("source")
    if isinstance(src, dict) and isinstance(src.get("source"), str):
        return src["source"]
    for k in ("full", "src", "url"):
        v = d.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
    return None


def _is_drm(d: dict) -> bool:
    files = d.get("files")
    return bool(isinstance(files, dict) and files.get("drm")) or bool(d.get("drm"))


def media_items(data, stats: dict | None = None) -> list[dict]:
    """[{"id", "url", "type"}] in ordine, senza doppioni. stats conta «locked» e «drm»."""
    stats = stats if stats is not None else {}
    out, seen = [], set()

    def walk(o, depth=0):
        if depth > 16:
            return
        if isinstance(o, dict):
            t = str(o.get("type") or "").lower()
            if t in MEDIA_TYPES and ("canView" in o or "files" in o or "source" in o or "full" in o):
                if o.get("canView") is False:
                    stats["locked"] = stats.get("locked", 0) + 1
                else:
                    url = _full_url(o)
                    if url:
                        key = str(o.get("id") or url)
                        if key not in seen:
                            seen.add(key)
                            out.append({"id": key, "url": url, "type": t})
                    elif _is_drm(o):
                        stats["drm"] = stats.get("drm", 0) + 1
                    else:
                        stats["locked"] = stats.get("locked", 0) + 1
                return
            for k, v in o.items():
                if k in SKIP_KEYS:
                    continue
                if isinstance(v, (dict, list)):
                    walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)
    walk(data)
    return out
