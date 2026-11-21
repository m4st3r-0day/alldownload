"""Motore compatibile con i template .etmpl di Extreme Picture Finder.

Come lavora (come EPF):
  1. Il link iniziale sceglie il template ([StartingURLTemplates]).
  2. Ogni pagina scaricata produce nuovi indirizzi: link nei tag HTML, url(...) nei CSS,
     indirizzi nel testo semplice e [CustomParsers].
  3. Gli indirizzi passano i filtri [IncludedURLs] / [ExcludedURLs].
  4. Se il nome del file corrisponde a [TargetFiles] -> download, altrimenti -> pagina da esplorare.

Variabili negli indirizzi:
  [#n]          gruppo n della corrispondenza attuale
  [#k:n]        gruppo n del parser k (k parte da 1)
  [#-k:n] [#+k:n]  gruppo n del parser k posizioni prima / dopo questo
  [#func(...)#] funzioni: jsonencode, jsondecode, urlencode, urldecode, htmldecode,
                lowercase, uppercase, base64decode, base64encode, dectohex, hextodec

I parser vedono il testo "URL della pagina" + a capo + contenuto della pagina.

Estensione PicFinder (EPF ignora le sezioni che non conosce):
  [PicFinderStart]
  Expression000=regex sul link incollato dall'utente
  Address000=indirizzo da cui partire davvero
  PasswordParam000=nome del parametro password da aggiungere (se l'utente la inserisce)
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import configparser
import fnmatch
import html
import json
import random
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

import httpx

from . import sitehooks
from .netpolicy import page_cache
from .core import PluginError, RemoteFile, filename_from_cd
from .postproc import json_meta
from .logs import log, short

NO_ADDRESS = "/-/-/"
MAX_PAGES = 20000
MAX_CHAIN = 15
_TEXT_TYPES = ("text/", "json", "xml", "javascript", "mpegurl")

_FUNC_RE = re.compile(r"\[#([A-Za-z_0-9]+)\((.*?)\)#\]", re.S)
_REF_RE = re.compile(r"\[#([-+]?\d+):(\d+)\]|\[#(\d+)\]")
_TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*)>", re.S)
_ATTR_RE = re.compile(r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""")
_CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")\s]+)""", re.I)
_PLAIN_URL_RE = re.compile(r"""https?://[^\s"'<>\\)\]}]+""")
_LINK_ATTRS = ("href", "src", "data-src", "data-original", "data-url", "poster", "background")
# tag che caricano "pezzi" della pagina (immagini, script, stili): non sono pagine da esplorare
_RESOURCE_TAGS = {"img", "script", "link", "source", "audio", "video", "track", "embed", "picture", "input"}
_SKIP_SCHEMES = ("javascript:", "mailto:", "data:", "tel:", "about:", "#")


def _json_unescape(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def _b64decode(s: str) -> str:
    s = s.strip()
    try:
        return base64.b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", "replace")
    except ValueError:
        return s


def _hex_to_dec(s: str) -> str:
    try:
        return str(int(s.strip(), 16))
    except ValueError:
        return s


def _dec_to_hex(s: str) -> str:
    try:
        return format(int(s.strip()), "x")
    except ValueError:
        return s


FUNCS = {
    "jsonencode": lambda s: quote(_json_unescape(s), safe=""),
    "jsondecode": _json_unescape,
    "urlencode": lambda s: quote(s, safe=""),
    "urldecode": unquote,
    "htmldecode": html.unescape,
    "lowercase": str.lower,
    "uppercase": str.upper,
    "base64decode": _b64decode,
    "base64encode": lambda s: base64.b64encode(s.encode()).decode(),
    "hextodec": _hex_to_dec,
    "dectohex": _dec_to_hex,
}


def _grp(m: re.Match | None, n: int) -> str:
    if m is None or n > (m.re.groups or 0):
        return ""
    return m.group(n) or ""


def expand(template: str, cur: re.Match | None, ctx: list, idx: int = 0) -> str:
    """Sostituisce [#n], [#k:n], [#-k:n], [#+k:n] e [#funzione(...)#]."""
    def ref(m: re.Match) -> str:
        if m.group(3) is not None:
            return _grp(cur, int(m.group(3)))
        k_txt, n = m.group(1), int(m.group(2))
        k = int(k_txt)
        target = idx + k if k_txt[0] in "+-" else k - 1
        return _grp(ctx[target] if 0 <= target < len(ctx) else None, n)

    def func(m: re.Match) -> str:
        arg = _REF_RE.sub(ref, m.group(2))
        f = FUNCS.get(m.group(1).lower())
        return f(arg) if f else arg

    return _REF_RE.sub(ref, _FUNC_RE.sub(func, template))


_CHALLENGE = re.compile(r"cf-chl|challenge-platform|Just a moment\.\.\.|cf_chl_opt|ddos-guard|"
                        r"Checking your browser|hcaptcha\.com|g-recaptcha|turnstile", re.I)


def _looks_like_challenge(text: str) -> bool:
    return bool(text) and len(text) < 300_000 and bool(_CHALLENGE.search(text[:200_000]))


_LINK_KEYS = ("link", "url", "download", "downloadUrl", "download_url", "src", "file", "directLink")
_THUMB_KEYS = ("thumbnail", "thumb", "thumbnailUrl", "thumbnail_url", "preview", "poster")


def json_thumbs(text: str) -> dict[str, str]:
    """In un JSON, oggetti con un link al file e una miniatura: {link: miniatura}."""
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    out: dict[str, str] = {}

    def walk(o, depth=0):
        if depth > 12:
            return
        if isinstance(o, dict):
            link = next((o[k] for k in _LINK_KEYS if isinstance(o.get(k), str) and o[k].startswith("http")), None)
            thumb = next((o[k] for k in _THUMB_KEYS if isinstance(o.get(k), str) and o[k].startswith("http")), None)
            if link and thumb:
                out[link] = thumb
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)
    walk(data)
    return out


_TITLE_RES = (re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I),
              re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title', re.I),
              re.compile(r"<title[^>]*>([^<]+)</title>", re.I))


def _json_urls(text: str) -> set[str]:
    """Tutti gli indirizzi http(s) scritti per intero dentro un JSON (vuoto se non è un JSON)."""
    t = text.lstrip()
    if not t[:1] in ("{", "[") or len(t) > 20_000_000:
        return set()
    try:
        data = json.loads(t)
    except ValueError:
        return set()
    out: set[str] = set()
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
        elif isinstance(o, str) and o.startswith(("http://", "https://")) and len(o) < 4000:
            out.add(o)
    return out


def json_title(text: str) -> str:
    """Nome della cartella/album in una risposta JSON: {"data": {"name": ...}} o {"title"/"name": ...}."""
    t = text.lstrip()
    if t[:1] != "{" or len(t) > 20_000_000:
        return ""
    try:
        d = json.loads(t)
    except ValueError:
        return ""
    for o in (d.get("data") if isinstance(d.get("data"), dict) else None, d):
        if isinstance(o, dict):
            for k in ("title", "name", "folderName", "albumName"):
                v = o.get(k)
                if isinstance(v, str) and v.strip() and "/" not in v.strip("/") and not v.startswith("http"):
                    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", v).strip(" .-")[:120]
    return ""


def page_title(html: str, url: str) -> str:
    """Titolo leggibile di una pagina, senza il nome del sito: «Vacanze 2024 | Bunkr» → «Vacanze 2024»."""
    import html as _html
    for rx in _TITLE_RES:
        m = rx.search(html[:200_000])
        if m:
            t = _html.unescape(m.group(1)).strip()
            break
    else:
        return ""
    site = site_of(url).split(".")[0].lower()
    parts = [p.strip() for p in re.split(r"\s+[|–—-]\s+", t) if p.strip()]
    while len(parts) > 1 and site and site in parts[-1].lower():
        parts.pop()
    t = " - ".join(parts)
    if site and site in t.lower():          # titolo generico del sito («Gofile — Cloud Storage…»): non serve
        return ""
    t = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", t).strip(" .-")
    return t[:120]


def site_of(url: str) -> str:
    """Dominio del sito senza sottodomini: cdn1.filester.me -> filester.me, a.b.co.uk -> b.co.uk."""
    host = (urlsplit(url).hostname or "").lower()
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and len(parts[-2]) <= 3:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def _rx(s: str, flags=re.I) -> re.Pattern:
    return re.compile(s, flags)


@dataclass
class Parser:
    expr: re.Pattern
    address: str
    method: str = "GET"
    post: str = ""


@dataclass
class Rule:
    expr: re.Pattern
    address: str
    extra: str = ""


@dataclass
class HeaderRule:
    url_re: re.Pattern
    name: str
    kind: str
    value: str


@dataclass
class Link:
    url: str
    method: str = "GET"
    data: str | None = None
    hint: str = ""        # nome suggerito (es. attributo alt)
    trusted: bool = False  # trovato da un parser dedicato: ignora il limite "stesso sito"
    resource: bool = False  # src di img/script/link…: si scarica solo se è un file target, mai esplorato
    plain: bool = False     # trovato nel testo semplice (può essere lo stesso indirizzo di un tag)


def _save_debug_pages(pages: list[tuple[str, str]]) -> None:
    """0 file trovati: salva le prime pagine nella cartella dei log, così si vede cosa c'era."""
    try:
        from .logs import log_dir
        d = log_dir() / "pagine"
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for i, (u, text) in enumerate(pages, 1):
            host = re.sub(r"[^A-Za-z0-9.-]", "_", urlsplit(u).hostname or "pagina")
            f = d / f"{stamp}-{host}-{i}.html"
            f.write_text(f"<!-- {u} -->\n{text}", encoding="utf-8")
            log.info("  pagina salvata per controllo → %s", f)
        old = sorted(d.glob("*.html"))[:-30]          # tiene solo le ultime 30
        for f in old:
            f.unlink(missing_ok=True)
    except OSError as e:
        log.debug("  non riesco a salvare la pagina: %s", e)


STREAM_MANIFEST = re.compile(r"\.(m3u8|mpd)(\?|$)", re.I)


# {POST_URL}, \\/contact ...: modelli e testi dentro i JSON, non indirizzi veri
BROKEN_URL = re.compile(r"[{}<>]|%7B|%7D|\\/|\\$", re.I)


@dataclass
class Template:
    path: Path
    title: str
    settings: dict
    start_res: list[re.Pattern]
    targets: list[str]
    included: list[re.Pattern]
    excluded: list[re.Pattern]
    parsers: list[Parser]
    referers: list[dict]
    subfolder_rules: list[Rule]
    excluded_parts: list[tuple[re.Pattern | None, re.Pattern | None]]
    headers: list[HeaderRule] = field(default_factory=list)
    start_rewrites: list[Rule] = field(default_factory=list)
    db_id: str = ""            # TemplateDatabaseID: stesso template in versioni diverse
    db_version: int = 0        # TemplateDatabaseVersion

    # ---------- caricamento ----------
    @classmethod
    def load(cls, path: str | Path) -> "Template":
        path = Path(path)
        cp = configparser.RawConfigParser(delimiters=("=",), strict=False,
                                          interpolation=None, comment_prefixes=(";",))
        cp.optionxform = str
        cp.read_string(_read_text(path))

        def lst(section: str, key: str) -> list[str]:
            out, i = [], 0
            while cp.has_option(section, f"{key}{i:03d}"):
                out.append(cp.get(section, f"{key}{i:03d}"))
                i += 1
            return out

        def get(section: str, key: str, i: int | None = None, default: str = "") -> str:
            k = key if i is None else f"{key}{i:03d}"
            return cp.get(section, k) if cp.has_option(section, k) else default

        settings = dict(cp.items("Settings")) if cp.has_section("Settings") else {}
        title = unquote(get("TemplateSettings", "EncodedTitle")) or path.stem

        parsers = [Parser(_rx(e, 0), get("CustomParsers", "Address", i),
                          get("CustomParsers", "RequestType", i, "GET").upper() or "GET",
                          unquote(get("CustomParsers", "POSTData", i)))
                   for i, e in enumerate(lst("CustomParsers", "Expression"))]
        referers = [{"re": _rx(u),
                     "type": get("CustomHTTPReferers", "RefererType", i, "hrtNatural"),
                     "text": get("CustomHTTPReferers", "Text", i),
                     "cpre": get("CustomHTTPReferers", "CPRE", i),
                     "cpresult": get("CustomHTTPReferers", "CPResult", i)}
                    for i, u in enumerate(lst("CustomHTTPReferers", "URLRegExp"))]
        sub_rules = [Rule(_rx(e), get("SubFoldersParentURLREs", "Address", i))
                     for i, e in enumerate(lst("SubFoldersParentURLREs", "Expression"))]
        parts = []
        i = 0
        while cp.has_option("ExcludedPageParts", f"From{i:03d}") or cp.has_option("ExcludedPageParts", f"To{i:03d}"):
            frm, to = get("ExcludedPageParts", "From", i), get("ExcludedPageParts", "To", i)
            if frm or to:
                parts.append((_rx(frm, re.S) if frm else None, _rx(to, re.S) if to else None))
            i += 1
        headers = []
        for i, u in enumerate(lst("CustomHTTPHeaders", "URLRegEx")):
            j = 0
            while cp.has_option("CustomHTTPHeaders", f"Name{i:03d}_{j:03d}"):
                headers.append(HeaderRule(_rx(u), get("CustomHTTPHeaders", f"Name{i:03d}_{j:03d}"),
                                          get("CustomHTTPHeaders", f"Type{i:03d}_{j:03d}", None, "chvtText"),
                                          get("CustomHTTPHeaders", f"Value{i:03d}_{j:03d}")))
                j += 1
        rewrites = [Rule(_rx(e), get("PicFinderStart", "Address", i),
                         get("PicFinderStart", "PasswordParam", i))
                    for i, e in enumerate(lst("PicFinderStart", "Expression"))]

        return cls(
            path=path, title=title, settings=settings,
            start_res=[_rx(u) for u in lst("StartingURLTemplates", "URL")],
            targets=lst("TargetFiles", "File"),
            included=[_rx(u) for u in lst("IncludedURLs", "URL")],
            excluded=[_rx(u) for u in lst("ExcludedURLs", "URL")],
            parsers=parsers, referers=referers, subfolder_rules=sub_rules,
            excluded_parts=parts, headers=headers, start_rewrites=rewrites,
            db_id=get("TemplateSettings", "TemplateDatabaseID").strip(),
            db_version=int(re.sub(r"\D", "", get("TemplateSettings", "TemplateDatabaseVersion")) or 0),
        )

    # ---------- impostazioni ----------
    def flag(self, key: str, default: bool = False) -> bool:
        v = self.settings.get(key)
        return default if v is None else v.strip().lower() == "true"

    def num(self, key: str, default: float = 0) -> float:
        try:
            return float(self.settings.get(key, default))
        except ValueError:
            return default

    @property
    def options(self) -> dict:
        """Opzioni del template che usa il Downloader."""
        o: dict = {}
        if (n := int(self.num("SuggestedSimultaneousConnections"))) > 0:
            o["connections"] = n
        if self.flag("UseRandomDelayBetweenDownloads"):
            lo = self.num("MinDelayBetweenDownloads")
            o["delay"] = (lo, max(lo, self.num("MaxDelayBetweenDownloads", lo)))
        c = {"rncDoNotSave": "do_not_save", "rncRename": "rename", "rncOverwrite": "overwrite"}.get(
            self.settings.get("ResolveNamingConflictsType", ""))
        if c:                              # altrimenti vale l'impostazione dell'app
            o["conflicts"] = c
        o["rename_digits"] = int(self.num("ConflictsRenameNumberOfDigits", 3)) or 3
        if self.flag("UseMinFileSizeLimit"):
            unit = {"fsuB": 1, "fsuKB": 1024, "fsuMB": 1024 ** 2, "fsuGB": 1024 ** 3}.get(
                self.settings.get("MinFileSizeUnit", "fsuKB"), 1024)
            o["min_size"] = int(self.num("MinFileSizeLimit") * unit)
        o["use_content_disposition"] = self.settings.get("SaveNamingType", "sntOriginal") == "sntOriginal"
        return o

    def needs_browser(self) -> bool:
        """Il template vuole il browser interno (login manuale o intestazioni da copiare)."""
        return (self.flag("ManualLogin") and not self.start_rewrites) or \
            any(h.kind != "chvtText" for h in self.headers)

    def browser_message(self) -> str:
        return unquote(self.settings.get("ManualLoginMessage", "")).strip()

    def browser_useful(self, url: str) -> bool:
        """Una richiesta catturata dal browser serve a questo template?"""
        return any(r.search(url) for r in self.included) or \
            any(re.search(h.value or "$^", url, re.I) for h in self.headers if h.kind != "chvtText")

    def warnings(self, session=None) -> list[str]:
        if session is not None or not self.needs_browser():
            return []
        return ["Questo template vuole il browser interno (login o intestazioni da copiare), "
                "ma la ricerca parte senza: il sito potrebbe non mostrare niente."]

    # ---------- descrizione e compatibilità ----------
    _KINDS = {"gallery": "galleria", "category": "categoria", "album": "album", "blog": "blog",
              "user": "utente", "profile": "profilo", "search": "ricerca", "tag": "tag",
              "post": "post", "video": "video", "videos": "video", "photos": "foto"}

    @property
    def service(self) -> str:
        """Nome del servizio, preso dal titolo: "imagefap.com gallery downloader" -> "imagefap.com"."""
        first = (self.title.split() or [self.path.stem])[0]
        return first if "." in first else first[:1].upper() + first[1:]

    @property
    def kind(self) -> str:
        rest = [w for w in self.title.split()[1:] if w.lower() not in ("downloader", "template")]
        return " ".join(self._KINDS.get(w.lower(), w) for w in rest) or "link condiviso"

    def compatibility(self) -> list[tuple[str, str]]:
        """Cose che PicFinder non sa ancora fare: [(livello, testo)].

        livello "soft" = può funzionare lo stesso (da provare), "hard" = manca qualcosa di sicuro,
        "info" = solo come si usa (non cambia lo stato).
        Lista vuota = compatibile.
        """
        soft, issues = [], []
        s = self.settings
        if any(h.kind not in ("chvtText", "chvtCopyFromParent") for h in self.headers):
            issues.append("tipo di intestazione non supportato: " +
                          ", ".join(sorted({h.kind for h in self.headers} - {"chvtText", "chvtCopyFromParent"})))
        info = []
        if self.needs_browser():          # non è un problema: solo un'informazione su come si usa
            info.append("usa il browser interno: si apre da solo, fai login o aspetta il contenuto e premi "
                        "«Continua download»")
        if s.get("ExplorationType", "setRegular") != "setRegular":
            issues.append(f"modalità di esplorazione {s['ExplorationType']} (es. TGP)")
        if s.get("ExplorationLimit", "selEntireSite") not in ("selEntireSite", "selNone", ""):
            issues.append(f"limite di esplorazione {s['ExplorationLimit']}")
        if s.get("SaveNamingType", "sntOriginal") not in ("sntOriginal", "sntTagAttributeValue"):
            issues.append(f"nomi dei file {s['SaveNamingType']}")
        if s.get("SubFoldersMode", "sfmNone") not in ("sfmNone", "sfmParentURLRE", ""):
            issues.append(f"sottocartelle {s['SubFoldersMode']}")
        texts = [p.address + p.post + p.expr.pattern for p in self.parsers]
        texts += [r.address for r in self.subfolder_rules + self.start_rewrites]
        used = {m.lower() for t in texts for m in re.findall(r"\[#([A-Za-z_0-9]+)\(", t)}
        missing = sorted(used - set(FUNCS))
        if missing:
            issues.append("funzioni non ancora supportate: " + ", ".join(missing))
        if any("[$" in t for t in texts):
            issues.append("cicli [$da-a$] nei Custom Parsers")
        if any(_REF_RE.search(p.expr.pattern) for p in self.parsers):
            issues.append("riferimenti ad altri parser dentro l'Expression")
        known = sitehooks.covered(self)
        internal = ("instagram", "x.com", "twitter", "flickr", "deviantart", "vk.com", "reddit",
                    "smugmug", "imgur", "tumblr")
        if not known and any(k in self.title.lower() for k in internal):
            soft.append("in EPF questo sito usa anche un parser interno: potrebbe servirne uno dedicato")
        return [("hard", i) for i in issues] + [("soft", i) for i in soft] + [("info", i) for i in info]

    @property
    def tested(self) -> str:
        """Data dell'ultima prova vera sul sito (PicFinderTested=2026-11 nel template), o vuoto."""
        return self.settings.get("PicFinderTested", "").strip()

    # ---------- regole ----------
    def start_url(self, url: str, password: str | None) -> str:
        for r in self.start_rewrites:
            m = r.expr.search(url)
            if m:
                new = expand(r.address, m, [])
                if password and r.extra:
                    sep = "&" if "?" in new else "?"
                    new += f"{sep}{r.extra}={quote(password, safe='')}"
                return new
        return url

    @staticmethod
    def file_name(url: str) -> str:
        parts = urlsplit(url)
        n = parse_qs(parts.query).get("n", [""])[0].strip()      # Bunkr, filester: «?n=nome vero.mp4»
        if n and "." in n and "/" not in n and len(n) < 250:
            return n
        name = unquote(parts.path.rstrip("/").rsplit("/", 1)[-1])
        if "\\u" in name or "\\/" in name:   # nome preso grezzo da un JSON
            name = _json_unescape(name)
        return name

    def is_target(self, url: str) -> bool:
        return self.is_target_name(self.file_name(url))

    def is_target_name(self, name: str) -> bool:
        name = name.lower()
        if not name:
            return False
        for p in self.targets:
            p = p.lower()
            if p == "*.":                      # file senza estensione
                if "." not in name:
                    return True
            elif fnmatch.fnmatch(name, p):
                return True
        return False

    def why_not(self, url: str, start: str, target: bool = False, trusted: bool = False) -> str | None:
        """None se l'indirizzo va seguito, altrimenti il motivo per cui viene scartato."""
        if BROKEN_URL.search(url):
            return "indirizzo rotto (pezzo di codice, non un link vero)"
        for r in self.included:
            if r.search(url):
                return None
        for r in self.excluded:
            if r.search(url):
                return f"escluso da [ExcludedURLs] «{r.pattern}»"
        if trusted or (target and self.flag("DownloadTargetFilesFromExternalSites")):
            return None
        if self.settings.get("ExplorationLimit", "selEntireSite") == "selEntireSite" \
                and site_of(url) != site_of(start):
            return f"altro sito ({site_of(url)})"
        return None

    def allowed(self, url: str, start: str, target: bool = False, trusted: bool = False) -> bool:
        return self.why_not(url, start, target, trusted) is None

    def strip_parts(self, text: str) -> str:
        """Toglie le parti di pagina. From vuoto = dall'inizio, To vuoto = fino alla fine."""
        for frm, to in self.excluded_parts:
            if frm is None:
                m2 = to.search(text) if to is not None else None
                if m2:
                    text = text[m2.end():]
                continue
            pos = 0
            while pos <= len(text) and (m1 := frm.search(text, pos)):
                if to is None:
                    text = text[:m1.start()]
                    break
                m2 = to.search(text, m1.end())
                if not m2:
                    break
                if m2.end() == m1.start():       # niente da togliere: evita giri infiniti
                    pos = m1.start() + 1
                    continue
                text = text[:m1.start()] + text[m2.end():]
                pos = m1.start()
        return text

    def _naming_attr(self) -> str:
        if self.settings.get("SaveNamingType") == "sntTagAttributeValue":
            return self.settings.get("NamingTagAttributeName", "").lower()
        return ""

    def extract(self, page_url: str, text: str, extra: str = "") -> list[Link]:
        body = self.strip_parts(text)
        full = page_url + "\r\n" + body
        ctx = [p.expr.search(full) for p in self.parsers]
        out: list[Link] = []
        for i, p in enumerate(self.parsers):
            if not p.address or re.fullmatch(r"[/\-]+", p.address.strip()):   # "/-/-/" = nessun indirizzo
                continue
            for m in p.expr.finditer(full):
                addr = expand(p.address, m, ctx, i).strip()
                if addr:
                    data = expand(p.post, m, ctx, i) if p.method == "POST" else None
                    out.append(Link(urljoin(page_url, html.unescape(addr)), p.method, data))

        name_attr = self._naming_attr()
        for tm in _TAG_RE.finditer(body):
            is_res = tm.group(1).lower() in _RESOURCE_TAGS
            attrs = {a.group(1).lower(): html.unescape(a.group(2) or a.group(3) or a.group(4) or "")
                     for a in _ATTR_RE.finditer(tm.group(2))}
            hint = attrs.get(name_attr, "").strip() if name_attr else ""
            values = [attrs[a] for a in _LINK_ATTRS if attrs.get(a)]
            for key in ("srcset", "data-srcset"):
                if attrs.get(key):
                    values += [part.strip().split()[0] for part in attrs[key].split(",") if part.strip()]
            for v in values:
                v = v.strip()
                if v and not v.lower().startswith(_SKIP_SCHEMES):
                    out.append(Link(urljoin(page_url, v), hint=hint, resource=is_res))
        for u in _CSS_URL_RE.findall(body):
            if not u.lower().startswith(_SKIP_SCHEMES):
                out.append(Link(urljoin(page_url, html.unescape(u)), resource=True))
        full_urls = _json_urls(text)          # nei JSON: indirizzi interi, anche con «(1)» nel nome
        for u in _PLAIN_URL_RE.findall(body.replace("\\/", "/")):
            u = html.unescape(u).rstrip(".,;")
            if full_urls and u not in full_urls:
                longer = [j for j in full_urls if j.startswith(u) and len(j) > len(u)]
                if len(longer) == 1:          # l'espressione si era fermata a una parentesi
                    u = longer[0]
            out.append(Link(u, plain=True))
        for u in _PLAIN_URL_RE.findall(extra):
            out.append(Link(u, trusted=True))

        seen: dict[tuple, Link] = {}
        for link in out:
            link.url = link.url.split("#", 1)[0] if "#" in link.url and link.method == "GET" else link.url
            key = (link.method, link.url, link.data)
            if key not in seen or (link.hint and not seen[key].hint):
                if key in seen:
                    link.trusted = link.trusted or seen[key].trusted
                    link.resource = link.resource and seen[key].resource
                seen[key] = link
            elif not link.resource and not link.plain:
                seen[key].resource = False     # trovato anche come link vero (es. <a href>)
        return list(seen.values())

    def subfolder(self, chain: tuple[str, ...], titles: dict[str, str] | None = None) -> str:
        """Cartella dal link (es. /a/PU25NYca → «PU25NYca»). Con PicFinderFolderFromTitle=True nel template
        si usa invece il titolo dell'album/cartella, se la pagina l'ha dato («Vacanze 2024»)."""
        if self.settings.get("SubFoldersMode") != "sfmParentURLRE":
            return ""
        use_title = self.settings.get("PicFinderFolderFromTitle", "").lower() == "true" and titles
        for parent in chain:
            for r in self.subfolder_rules:
                m = r.expr.search(parent)
                if m:
                    if use_title and titles.get(parent):
                        return titles[parent]
                    return unquote(expand(r.address, m, [])).replace("\\", "/").strip("/")
        return ""

    def referer(self, url: str, parent: str | None) -> str | None:
        for r in self.referers:
            if r["re"].search(url):
                t = r["type"]
                if t == "hrtCustomParser":
                    m = re.search(r["cpre"], url, re.I)
                    return expand(r["cpresult"], m, []) if m else parent
                if t in ("hrtCustomText", "hrtSimpleText"):
                    return r["text"]
                if t == "hrtNone":
                    return None
                return parent
        t = self.settings.get("DefaultRefererType", "hrtNatural")
        if t == "hrtNone":
            return None
        if t in ("hrtCustomText", "hrtSimpleText"):
            return self.settings.get("DefaultRefererCustomText") or None
        return parent

    def request_headers(self, url: str, parent: str | None, data: str | None = None,
                        session=None) -> dict:
        h = {}
        ref = self.referer(url, parent)
        if ref:
            h["Referer"] = ref
        for rule in self.headers:
            if not rule.url_re.search(url):
                continue
            if rule.kind == "chvtText":
                h[rule.name] = rule.value
            elif rule.kind == "chvtCopyFromParent" and session is not None:
                v = session.header_for(rule.value or ".", rule.name)
                if v is not None:
                    h[rule.name] = v
        if data and data.lstrip().startswith(("{", "[")) and not any(k.lower() == "content-type" for k in h):
            h["Content-Type"] = "application/json"
        return h

    def target_name(self, url: str, hint: str) -> tuple[str, bool]:
        """(nome del file, nome fissato dal template)."""
        original = self.file_name(url)
        if hint:
            ext = PurePosixPath(original).suffix
            return (hint if hint.lower().endswith(ext.lower()) else hint + ext), True
        return original, False


class EtmplPlugin:
    """Rende un template .etmpl usabile come un plugin del Downloader."""
    OWN_FILTER = True  # i file da scaricare li decide [TargetFiles]

    def __init__(self, template: Template):
        self.t = template
        self.NAME = template.title
        self.on_event = lambda kind, data: None

    @property
    def options(self) -> dict:
        return self.t.options

    def match(self, url: str) -> bool:
        return any(r.search(url) for r in self.t.start_res)

    def _warn(self, msg: str):
        log.warning(msg)
        self.on_event("warning", {"message": msg})

    ACCEPTS_SESSION = True

    async def list_files(self, client: httpx.AsyncClient, url: str, password: str | None = None,
                         session=None):
        t = self.t
        for w in t.warnings(session):
            self._warn(w)
        start = t.start_url(url, password)
        depth_limit = int(t.num("ExplorationDepth")) if t.flag("UseExplorationDepth") else 0
        delay = t.options.get("delay")
        scale = float(getattr(self, "pause_scale", 1.0) or 1.0)
        if delay and scale != 1.0:          # mai a raffica: almeno ~0,3 s tra due pagine dello stesso server
            delay = (max(0.3, delay[0] * scale), max(0.6, delay[1] * scale))
        log.info("Template «%s» (%s) — partenza: %s", t.title, t.path.name, short(start))
        if start != url:
            log.debug("  link incollato %s → riscritto da [PicFinderStart]", short(url))
        log.debug("  opzioni: %s; profondità max: %s", t.options, depth_limit or "nessuna")
        # (link, catena dei padri, profondità)
        queue: deque[tuple[Link, tuple[str, ...], int]] = deque([(Link(start), (), 0)])
        fast: deque[tuple[Link, tuple[str, ...], int]] = deque()   # file e risposte già nel browser: subito
        seen: set = set()
        pages = found = 0
        cache = session.cached() if session else {}
        thumbs: dict[str, str] = {}
        metas: dict[str, dict] = {}         # 10: data del post e didascalia, dai JSON delle API
        titles: dict[str, str] = {}         # titolo di album/cartelle, per dare il nome alla cartella
        html_pages: dict[str, tuple[str, str]] = {}
        debug_pages: list[tuple[str, str]] = []          # per capire i casi "0 file"
        api_pages: list[tuple[str, str]] = []            # risposte API del template (registro dettagliato)
        if session is not None:
            log.info("Uso la sessione del browser interno: %s", session.summary())
            def _same(a: str, b: str) -> bool:
                norm = lambda x: x.split("#")[0].rstrip("/")
                return bool(a) and bool(b) and norm(a) == norm(b)
            if session.html and (not session.final_url or _same(session.final_url, start)
                                 or _same(session.final_url, session.start_url)):
                for u in {start, session.start_url, session.final_url}:
                    html_pages[u] = (session.final_url or start, session.html)
            elif session.html:
                log.warning("  Il browser è finito su un'altra pagina (%s): non la uso, "
                            "scarico di nuovo %s con i cookie del login", short(session.final_url), short(start))
            # le richieste fatte dalla pagina (API, JSON...) diventano punti di partenza
            seeded = 0
            for rec in session.requests:
                if rec.url in (start, session.final_url):
                    continue
                link0 = Link(rec.url, rec.method, rec.body if rec.method != "GET" else None)
                tgt = link0.method == "GET" and t.is_target(rec.url)
                reason = t.why_not(rec.url, start, target=tgt)
                if reason is None:
                    fast.append((link0, ((session.final_url or start),), 1))
                    seeded += 1
                    log.debug("  + dal browser: %s %s%s", rec.method, short(rec.url),
                              "  (risposta già pronta)" if (rec.method, rec.url, link0.data) in cache else "")
            log.info("  %d richieste del browser messe in coda", seeded)
        t0 = time.monotonic()
        browser_api = session is not None and any(
            (r.method, r.url, r.body if r.method != "GET" else None) in cache and t.browser_useful(r.url)
            for r in session.requests)
        if browser_api:
            log.info("  il browser ha già le risposte delle API del sito: uso quelle e ignoro le miniature "
                     "della pagina")
        last_hit: dict[str, float] = {}
        while queue or fast:
            link, chain, depth = (fast or queue).popleft()
            key = (link.method, link.url, link.data)
            if key in seen:
                continue
            seen.add(key)
            parent = chain[0] if chain else None

            if link.method == "GET" and t.is_target(link.url):
                name, fixed = t.target_name(link.url, link.hint)
                found += 1
                sub = t.subfolder(chain, titles)
                log.debug("  ✓ file: %s%s ← %s", name, f"  [cartella {sub}]" if sub else "", short(link.url))
                meta = dict(metas.get(link.url, {}))
                if sub and sub in titles.values():
                    meta["folder_from_title"] = True       # niente cartella in più col codice del link
                # nome dell'album = titolo della pagina più «in alto» (il link incollato o la prima API)
                album = next((titles[c] for c in reversed(chain) if titles.get(c)), "")
                if album:
                    meta["album"] = album
                yield RemoteFile(url=link.url, name=name, subdir=sub,
                                 headers=t.request_headers(link.url, parent, None, session),
                                 fixed_name=fixed, thumb=thumbs.get(link.url, ""), meta=meta)
                continue
            if depth_limit and depth > depth_limit:
                log.debug("  - non seguito (profondità %d > %d): %s", depth, depth_limit, short(link.url))
                continue

            pages += 1
            if pages > MAX_PAGES:
                raise PluginError(f"Troppe pagine (> {MAX_PAGES}): template in un giro infinito?")
            self.on_event("page", {"url": link.url, "depth": depth})
            req_headers = t.request_headers(link.url, parent, link.data, session)
            ck = (link.method, link.url, link.data if link.method != "GET" else None)
            binary = None      # (nome, dimensione) se la "pagina" è in realtà un file
            rendered = False
            if link.method == "GET" and link.url in html_pages:
                rendered = True
                page_url, text = html_pages.pop(link.url)
                status, ctype, ms = 200, "text/html (dal browser)", 0
            elif ck in cache:
                rec = cache.pop(ck)
                page_url, text = link.url, rec.text or ""
                status, ctype, ms = rec.status or 200, (rec.ctype or "application/json") + " (dal browser)", 0
            else:
                host = (urlsplit(link.url).hostname or "").lower()
                if delay and host in last_hit:
                    # pausa del template, per server: un'API su un altro server non aspetta la pagina
                    wait = random.uniform(*delay) - (time.monotonic() - last_hit[host])
                    if wait > 0.05:
                        log.debug("  attesa %.1f s (ritardo del template)", wait)
                        await asyncio.sleep(wait)
                last_hit[host] = time.monotonic()
                log.debug("→ %s %s (profondità %d)%s", link.method, short(link.url), depth,
                          f"  dati: {link.data[:200]}" if link.data else "")
                if req_headers:
                    log.debug("  intestazioni: %s", {k: (v if k.lower() not in ("authorization", "cookie")
                                                         else "***") for k, v in req_headers.items()})
                t1 = time.monotonic()
                text = ""
                pc = page_cache() if link.method == "GET" else None
                send_headers = {**req_headers, **(pc.validators(link.url) if pc else {})}
                try:
                    async with client.stream(link.method, link.url, content=link.data,
                                             headers=send_headers) as r:
                        status = r.status_code
                        ctype = r.headers.get("content-type", "text/html").lower()
                        page_url = str(r.url)
                        is_text = any(x in ctype for x in _TEXT_TYPES)
                        if status == 304 and pc:
                            row = pc.get(link.url)
                            if row:
                                status, ctype, text, page_url = 200, row[2] + " (invariata, copia salvata)", row[3], link.url
                                log.debug("  304: la pagina non è cambiata, uso la copia salvata")
                        elif status < 400 and not is_text:
                            cd = filename_from_cd(r.headers.get("content-disposition", ""))
                            size = int(r.headers.get("content-length", 0)) or None
                            binary = (cd or t.file_name(page_url), size)
                        elif status < 400 or t.flag("ParseErrorPages") or pages == 1:
                            await r.aread()
                            text = r.text
                            if pc and status == 200:
                                pc.put(link.url, r.headers.get("etag"), r.headers.get("last-modified"), ctype, text)
                except httpx.HTTPError as e:
                    if pages == 1:
                        log.error("✗ %s: %s", short(link.url), e)
                        raise PluginError(f"Impossibile aprire il link: {e}") from e
                    self._warn(f"Errore di rete su {short(link.url)}: {e}")
                    continue
                ms = (time.monotonic() - t1) * 1000
                if page_url != link.url:
                    log.debug("  redirect → %s", short(page_url))
            if text and len(debug_pages) < 3:
                debug_pages.append((page_url, text))
            if text and len(api_pages) < 2 and t.included and any(r.search(page_url) for r in t.included):
                api_pages.append((page_url, text))
            if binary is not None:
                # nessuna estensione nell'indirizzo, ma il server manda un file: lo teniamo se è un target
                name, size = binary
                if link.method == "GET" and t.is_target_name(name):
                    found += 1
                    log.info("  ✓ file dal server: %s (%s, %d ms)", name, ctype, ms)
                    yield RemoteFile(url=link.url, name=name, size=size, subdir=t.subfolder(chain, titles),
                                     headers=req_headers, fixed_name=False)
                else:
                    log.info("  - risposta non di testo (%s), «%s» non è un tipo da scaricare", ctype, name)
                continue
            if status >= 400:
                if pages == 1:
                    log.error("✗ %s → errore %d", short(link.url), status)
                    if text and _looks_like_challenge(text):
                        log.error("  la pagina sembra un controllo anti-bot (Cloudflare/DDoS-Guard/captcha)")
                        raise PluginError("Il sito mostra un controllo «sei umano?». Usa il bottone «Browser»: "
                                          "risolvi il controllo e premi «Continua download».")
                    if status in (401, 403):
                        raise PluginError("Il sito rifiuta l'accesso (password mancante o errata, "
                                          "oppure serve il login: usa il bottone «Browser»).")
                    raise PluginError(f"Il sito risponde con errore {status}.")
                self._warn(f"Errore {status} su {short(link.url)}")
                if not t.flag("ParseErrorPages"):
                    continue
            if pages == 1 and session is None and _looks_like_challenge(text):
                self._warn("La prima pagina sembra un controllo anti-bot: se non trova niente, usa il bottone "
                           "«Browser» e premi «Continua download» quando vedi il contenuto.")
            log.info("Pagina %s → %d, %s, %.1f KB, %d ms", short(page_url), status, ctype.split(";")[0],
                     len(text) / 1024, ms)
            if "html" in ctype or text.lstrip()[:1] in ("<", "{"):
                ttl = page_title(text, page_url) if text.lstrip()[:1] == "<" else json_title(text)
                if ttl:
                    titles.setdefault(page_url, ttl)
                    titles.setdefault(link.url, ttl)
            if "json" in ctype or text.lstrip()[:1] in ("{", "["):
                found_meta = json_meta(text)
                if found_meta:
                    for u, m in found_meta.items():
                        metas.setdefault(u, m)
                    log.debug("  date/didascalie trovate nel JSON: %d", len(found_meta))
                found_thumbs = json_thumbs(text)
                if found_thumbs:
                    thumbs.update(found_thumbs)
                    log.debug("  miniature trovate nel JSON: %d", len(found_thumbs))
            extra = sitehooks.run(page_url, text)
            if extra:
                log.debug("  parser dedicato: %s", short(extra.strip(), 200))
            if log.isEnabledFor(logging.DEBUG):
                body = t.strip_parts(text)
                if len(body) != len(text):
                    log.debug("  [ExcludedPageParts]: tolti %d caratteri su %d", len(text) - len(body), len(text))
                full = page_url + "\r\n" + body
                for i, ps in enumerate(t.parsers):
                    n = len(ps.expr.findall(full))
                    log.debug("  parser %d (%s): %d corrispondenze  «%s»", i + 1, ps.method, n,
                              short(ps.expr.pattern, 80))
            new_chain = (page_url, *chain)[:MAX_CHAIN]
            added, rejected = 0, {}
            branch: list = []          # link di questa pagina: si seguono SUBITO (in profondità), così i file
            #                            escono uno dopo l'altro invece di arrivare tutti alla fine
            for new in t.extract(page_url, text, extra):
                k = (new.method, new.url, new.data)
                if k in seen:
                    continue
                is_target = new.method == "GET" and t.is_target(new.url)
                reason = t.why_not(new.url, start, target=is_target, trusted=new.trusted)
                if reason is None and new.resource and not is_target:
                    reason = "risorsa della pagina (immagine/script/stile), non è un file da scaricare"
                if reason is None and not is_target and STREAM_MANIFEST.search(new.url):
                    reason = "flusso video HLS/DASH (non è un file, spesso protetto)"
                if reason is None and browser_api and not is_target and not rendered and t.included \
                        and not any(r.search(new.url) for r in t.included):
                    # i dati veri arrivano dalle API catturate: il resto (testi, cdn, form...) fa solo perdere tempo
                    reason = "fuori dalle API del template (non in [IncludedURLs])"
                if reason is None and rendered:
                    # la pagina costruita dal browser è piena di miniature e link dell'interfaccia
                    if is_target and new.resource and browser_api:
                        reason = "miniatura della pagina (gli originali arrivano dalle API)"
                    elif not is_target and t.included and not any(r.search(new.url) for r in t.included):
                        reason = "link dell'interfaccia del sito (non in [IncludedURLs])"
                if reason is None:
                    nk = (new.method, new.url, new.data if new.method != "GET" else None)
                    if is_target or nk in cache:
                        fast.append((new, new_chain, depth + 1))
                    else:
                        branch.append((new, new_chain, depth + 1))
                    added += 1
                    log.debug("  + %s %s%s", "file" if is_target else "coda", short(new.url),
                              f"  (POST {new.data[:80]})" if new.data else "")
                else:
                    rejected[reason] = rejected.get(reason, 0) + 1
                    if rejected[reason] <= 5:
                        log.debug("  - scartato (%s): %s", reason, short(new.url))
            log.info("  %d indirizzi nuovi in coda, %d scartati%s", added, sum(rejected.values()),
                     ("  [" + "; ".join(f"{n}× {r}" for r, n in rejected.items()) + "]") if rejected else "")
            queue.extendleft(reversed(branch))
        log.info("Ricerca finita: %d pagine, %d file, %.1f s", pages, found, time.monotonic() - t0)
        if not found and debug_pages:
            _save_debug_pages(debug_pages)
        elif api_pages and log.isEnabledFor(logging.DEBUG):
            _save_debug_pages(api_pages)
