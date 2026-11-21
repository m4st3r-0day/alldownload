"""X (x.com / twitter.com): foto e video di un profilo — «Media», «Post», «Risposte», «Repost».

Codice nostro, dalle regole dei template EPF n. 405 (media) e 1255 (post):
  1. si apre il browser interno: fai login col tuo account e aspetta di vedere il profilo
  2. il sito chiede i post con «/graphql/<id>/User…?variables=…»: si usa la risposta che ha già il browser
  3. le pagine dopo: stessa richiesta con «cursor» = cursore «Bottom» della pagina prima,
     con le stesse intestazioni del browser (authorization, x-csrf-token, …)
Foto alla grandezza originale («?name=orig»), video e GIF nella qualità più alta (mp4).
Pause di 6-8 s tra le pagine, come i template: X blocca chi va di fretta.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..core import PluginError, RemoteFile
from ..logs import log
from ._kit import clean_name, kit_for

NAME = "X (Twitter)"
PREFERRED = True
ACCEPTS_SESSION = True
NEEDS_BROWSER = True
BROWSER_MESSAGE = ("Fai login col tuo account X. Torna al profilo (pulsante Home) e aspetta di vedere i contenuti, "
                   "poi premi «Continua download».")
BROWSER_USEFUL = r"/graphql/[^/]+/User[A-Za-z]*\?"
TESTED = ""
DELAY = (6.0, 8.0)
MAX_PAGES = 400

_RESERVED = {"home", "i", "explore", "search", "settings", "notifications", "messages", "compose", "login",
             "logout", "signup", "tos", "privacy", "hashtag", "intent", "share", "jobs", "premium"}
_PROFILE = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})"
                      r"(?:/(media|with_replies|reposts))?/?(?:[?#].*)?$", re.I)
_GRAPHQL = re.compile(r"/graphql/[^/]+/(User[A-Za-z]*)\?", re.I)
_COPY = ("authorization", "x-csrf-token", "x-twitter-active-user", "x-twitter-client-language",
         "x-client-transaction-id")
_WANT = {"media": ("UserMedia",), "with_replies": ("UserTweetsAndReplies",), "reposts": ("UserTweets",),
         None: ("UserTweets",)}


def match(url: str) -> bool:
    m = _PROFILE.match(url)
    return bool(m and m.group(1).lower() not in _RESERVED)


def _walk(o, depth=0):
    if depth > 40:
        return
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v, depth + 1)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, depth + 1)


def _date(s: str | None) -> float | None:
    try:
        return datetime.strptime(s or "", "%a %b %d %H:%M:%S %z %Y").timestamp()
    except ValueError:
        return None


def _best_video(info: dict) -> str:
    mp4 = [v for v in info.get("variants") or [] if v.get("content_type") == "video/mp4" and v.get("url")]
    return max(mp4, key=lambda v: v.get("bitrate") or 0)["url"] if mp4 else ""


def media_from(data, handle: str | None = None) -> list[dict]:
    """Ogni file dei tweet in una risposta GraphQL: {key, url, name, date, caption, tweet}.
    Con handle: solo i tweet di quel profilo (non quelli citati di altri)."""
    out = []
    for o in _walk(data):
        legacy = o.get("legacy") if isinstance(o.get("legacy"), dict) else None
        if not legacy or "extended_entities" not in legacy and "entities" not in legacy:
            continue
        if handle:
            sn = (((o.get("core") or {}).get("user_results") or {}).get("result") or {})
            sn = ((sn.get("legacy") or {}).get("screen_name") or (sn.get("core") or {}).get("screen_name") or "")
            if sn and sn.lower() != handle.lower() and not legacy.get("retweeted_status_result"):
                continue
        media = (legacy.get("extended_entities") or {}).get("media") or (legacy.get("entities") or {}).get("media") or []
        for m in media:
            key = m.get("media_key") or m.get("id_str")
            if m.get("type") == "photo":
                base = m.get("media_url_https") or ""
                if not base:
                    continue
                stem, _, ext = base.rsplit("/", 1)[-1].partition(".")
                url = f"{base.rsplit('.', 1)[0]}?format={ext or 'jpg'}&name=orig"
                name = f"{stem}.{ext or 'jpg'}"
            else:                                           # video, animated_gif
                url = _best_video(m.get("video_info") or {})
                if not url:
                    continue
                name = url.split("?")[0].rsplit("/", 1)[-1]
            tid = legacy.get("id_str") or o.get("rest_id") or ""
            out.append({"key": key or url, "url": url, "name": f"{tid}_{name}" if tid else name,
                        "date": _date(legacy.get("created_at")), "caption": legacy.get("full_text") or "",
                        "tweet": tid})
    return out


def bottom_cursor(data) -> str:
    for o in _walk(data):
        if o.get("cursorType") == "Bottom" and isinstance(o.get("value"), str):
            return o["value"]
    return ""


def with_cursor(url: str, cursor: str) -> str:
    p = urlsplit(url)
    q = parse_qsl(p.query, keep_blank_values=True)
    out = []
    for k, v in q:
        if k == "variables":
            try:
                var = json.loads(v)
            except ValueError:
                var = {}
            var["cursor"] = cursor
            v = json.dumps(var, separators=(",", ":"))
        out.append((k, v))
    return urlunsplit(p._replace(query=urlencode(out)))


async def list_files(client, url: str, password: str | None = None, session=None):
    m = _PROFILE.match(url)
    if not m:
        raise PluginError("X: serve il link di un profilo (es. https://x.com/nome/media)")
    if session is None:
        raise PluginError("X: serve il browser interno (login e profilo caricato).")
    handle, tab = m.group(1), (m.group(2) or "").lower() or None
    kit = kit_for(sys.modules[__name__], client, session)
    caps = [r for r in kit.captured(_GRAPHQL.pattern) if _GRAPHQL.search(r.url)]
    wanted = [r for r in caps if _GRAPHQL.search(r.url).group(1) in _WANT[tab]] or \
             [r for r in caps if _GRAPHQL.search(r.url).group(1) not in ("UserByScreenName", "UserByRestId")]
    if not wanted:
        raise PluginError("X: il browser non ha caricato i post. Fai login, apri il profilo, aspetta di vedere i "
                          "contenuti e poi premi «Continua download».")
    first = wanted[0]
    headers = {k: v for k, v in first.headers.items() if k in _COPY}
    headers.update({"content-type": "application/json", "x-twitter-auth-type": "OAuth2Session"})
    folder = clean_name(f"@{handle}")
    seen_keys, seen_cursors, n, pages = set(), set(), 0, 0
    page_url, text = first.url, first.text
    while page_url and pages < MAX_PAGES:
        if text is None:
            text = (await kit.fetch(page_url, headers=headers, referer=f"https://x.com/{handle}")).text
        pages += 1
        try:
            data = json.loads(text)
        except ValueError:
            raise PluginError("X: risposta non valida (forse troppe richieste: riprova più tardi)") from None
        if data.get("errors") and not data.get("data"):
            raise PluginError(f"X: {data['errors'][0].get('message', 'errore')}")
        new = 0
        for item in media_from(data, handle if tab != "reposts" else None):
            if item["key"] in seen_keys:
                continue
            seen_keys.add(item["key"])
            new += 1
            n += 1
            meta = {k: item[k] for k in ("date", "caption") if item[k]}
            meta["album"] = folder
            yield RemoteFile(url=item["url"], name=item["name"], subdir=folder, fixed_name=True,
                             headers={"Referer": "https://x.com/"}, meta=meta)
        cursor = bottom_cursor(data)
        log.info("X: pagina %d, %d file nuovi", pages, new)
        if not cursor or cursor in seen_cursors or (new == 0 and pages > 1 and not _has_tweets(data)):
            break
        seen_cursors.add(cursor)
        page_url, text = with_cursor(first.url, cursor), None
    if not n:
        raise PluginError("X: nessuna foto o video trovato su questo profilo.")


def _has_tweets(data) -> bool:
    return any(o.get("__typename") == "Tweet" for o in _walk(data))
