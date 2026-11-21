"""Sessione del browser interno: quello che il motore riceve quando premi "Continua download".

- cookies: per fare le richieste come il browser (login, controlli anti-bot)
- requests: le richieste fetch/XHR fatte dalla pagina, con intestazioni (token, firme...)
  e, quando possibile, la risposta (così non serve rifarle: alcune firme scadono subito)
- html: la pagina come la vedi tu, già costruita dal JavaScript
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class CapturedRequest:
    url: str
    method: str = "GET"
    headers: dict = field(default_factory=dict)   # nomi in minuscolo
    body: str | None = None
    status: int | None = None
    ctype: str = ""
    text: str | None = None                        # risposta (se testo/JSON)

    @classmethod
    def from_js(cls, d: dict) -> "CapturedRequest":
        return cls(url=str(d.get("url") or ""), method=str(d.get("method") or "GET").upper(),
                   headers={str(k).lower(): str(v) for k, v in (d.get("headers") or {}).items()},
                   body=d.get("body") if isinstance(d.get("body"), str) else None,
                   status=d.get("status"), ctype=str(d.get("ctype") or ""),
                   text=d.get("text") if isinstance(d.get("text"), str) else None)


@dataclass
class Cookie:
    name: str
    value: str
    domain: str = ""
    path: str = "/"


@dataclass
class BrowserSession:
    start_url: str
    final_url: str = ""
    html: str = ""
    requests: list[CapturedRequest] = field(default_factory=list)
    cookies: list[Cookie] = field(default_factory=list)
    user_agent: str = ""

    def header_for(self, url_regex: str, name: str) -> str | None:
        """Ultimo valore dell'intestazione `name` in una richiesta il cui indirizzo corrisponde a url_regex."""
        rx = re.compile(url_regex, re.I)
        name = name.lower()
        for r in reversed(self.requests):
            if name in r.headers and rx.search(r.url):
                return r.headers[name]
        return None

    # Siti che danno il token di accesso nelle API ma lo vogliono come cookie sui server dei file.
    # (Gofile: «Authorization: Bearer <token>» per api.gofile.io, cookie «accountToken» per file-*.gofile.io.)
    TOKEN_COOKIES = ((r"^https://api\.gofile\.io/", "accountToken", ".gofile.io"),)

    def add_token_cookies(self) -> list[str]:
        """Aggiunge i cookie che il browser avrebbe mandato col clic su «Download». Ritorna i nomi aggiunti."""
        added = []
        for rx, name, domain in self.TOKEN_COOKIES:
            if any(c.name == name for c in self.cookies):
                continue
            auth = self.header_for(rx, "authorization") or ""
            m = re.match(r"(?i)bearer\s+(\S+)", auth)
            if m:
                self.cookies.append(Cookie(name, m.group(1), domain, "/"))
                added.append(name)
        return added

    def cached(self) -> dict[tuple, CapturedRequest]:
        """Risposte già ricevute dal browser, per (metodo, url, corpo)."""
        out = {}
        for r in self.requests:
            if r.text is not None and (r.status or 200) < 400:
                out[(r.method, r.url, r.body if r.method != "GET" else None)] = r
        return out

    def summary(self) -> str:
        with_resp = sum(1 for r in self.requests if r.text is not None)
        return (f"{len(self.requests)} richieste catturate ({with_resp} con risposta), "
                f"{len(self.cookies)} cookie, pagina {len(self.html) // 1024} KB")
