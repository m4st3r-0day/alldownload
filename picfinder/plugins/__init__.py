"""Registro dei template.

Ordine di ricerca:
  1. template .etmpl nella cartella utente (quelli che aggiungi tu)
  2. template .etmpl inclusi nell'app (picfinder/templates)
  3. plugin Python in questa cartella (per i siti troppo complicati per un .etmpl)
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from pathlib import Path

_PLUGINS: list | None = None
_ERRORS: list[str] = []
_SUPERSEDED: list[str] = []

BUILTIN_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


def user_templates_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "PicFinder" / "templates"


def template_dirs() -> list[Path]:
    extra = os.environ.get("PICFINDER_TEMPLATES")
    dirs = [Path(extra)] if extra else []
    return dirs + [user_templates_dir(), BUILTIN_TEMPLATES]


def _origin(d: Path) -> str:
    return "inclusi" if d == BUILTIN_TEMPLATES else "tuoi"


def _load() -> list:
    from ..etmpl import EtmplPlugin, Template

    plugins: list = []
    _ERRORS.clear()
    _SUPERSEDED.clear()
    for d in template_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.etmpl")):
            try:
                p = EtmplPlugin(Template.load(f))
                p.KEY = f"{_origin(d)}/{f.name}"
                plugins.append(p)
            except Exception as e:  # noqa: BLE001 - un template rotto non deve bloccare l'app
                _ERRORS.append(f"{f.name}: {e}")
    # stesso template (stesso TemplateDatabaseID) in più cartelle: vale la versione più nuova.
    # A pari versione vince la tua copia (le tue modifiche). Così una copia vecchia non nasconde
    # un template incluso aggiornato.
    best: dict[str, object] = {}
    for p in plugins:
        tid = p.t.db_id
        if not tid:
            continue
        cur = best.get(tid)
        if cur is None or p.t.db_version > cur.t.db_version:
            best[tid] = p
    old = [p for p in plugins if p.t.db_id and best[p.t.db_id] is not p]
    for p in old:
        _SUPERSEDED.append(f"{p.KEY} (versione {p.t.db_version}) → uso {best[p.t.db_id].KEY} "
                           f"(versione {best[p.t.db_id].t.db_version})")
    plugins = [p for p in plugins if p not in old]
    preferred = []
    for info in pkgutil.iter_modules(__path__):
        mod = importlib.import_module(f"{__name__}.{info.name}")
        if hasattr(mod, "match") and hasattr(mod, "list_files"):
            mod.KEY = f"python/{info.name}"
            # PREFERRED = True: il plugin Python passa davanti ai template .etmpl dello stesso sito
            (preferred if getattr(mod, "PREFERRED", False) else plugins).append(mod)
    return preferred + plugins


# ---------- template attivi / disattivati ----------
def _disabled_file() -> Path:
    return user_templates_dir().parent / "template_disattivati.txt"


def disabled() -> set[str]:
    try:
        return {l.strip() for l in _disabled_file().read_text(encoding="utf-8").splitlines() if l.strip()}
    except OSError:
        return set()


def set_enabled(key: str, enabled: bool) -> None:
    keys = disabled()
    (keys.discard if enabled else keys.add)(key)
    f = _disabled_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(sorted(keys)) + ("\n" if keys else ""), encoding="utf-8")


def is_enabled(plugin) -> bool:
    return getattr(plugin, "KEY", "") not in disabled()


def entries() -> list[dict]:
    """Descrizione di tutti i template per la finestra "Template" e per la riga di comando."""
    from ..etmpl import EtmplPlugin

    off = disabled()
    out = []
    for p in all_plugins():
        if isinstance(p, EtmplPlugin):
            t = p.t
            out.append(dict(key=p.KEY, service=t.service, kind=t.kind, title=t.title,
                            origin=p.KEY.split("/")[0], path=str(t.path), issues=t.compatibility(),
                            patterns=[r.pattern for r in t.start_res], enabled=p.KEY not in off,
                            tested=t.tested))
        else:
            out.append(dict(key=p.KEY, service=p.NAME, kind="plugin Python" + (" (prioritario)" if getattr(p, "PREFERRED", False) else ""), title=p.NAME,
                            origin="python", path=getattr(p, "__file__", ""), issues=[],
                            patterns=[], enabled=p.KEY not in off, tested=getattr(p, "TESTED", "")))
    return out


def all_plugins() -> list:
    global _PLUGINS
    if _PLUGINS is None:
        _PLUGINS = _load()
    return _PLUGINS


def reload() -> list:
    global _PLUGINS
    _PLUGINS = None
    return all_plugins()


def load_errors() -> list[str]:
    return list(_ERRORS)


def superseded() -> list[str]:
    """Template scartati perché c'è una versione più nuova dello stesso."""
    return list(_SUPERSEDED)


def _specificity(p, url: str) -> int:
    """Quanto è preciso il template per questo link: vince quello con l'espressione più lunga che combacia
    (es. onlyfans.com/my/chats/chat/… batte onlyfans.com/.+)."""
    res = getattr(getattr(p, "t", None), "start_res", None)
    if not res:
        return 0
    return max((len(r.pattern) for r in res if r.search(url)), default=0)


# ---------- browser interno: vale per template e plugin Python ----------
def needs_browser(p) -> bool:
    if p is None:
        return False
    t = getattr(p, "t", None)
    if t is not None and hasattr(t, "needs_browser"):
        return t.needs_browser()
    return bool(getattr(p, "NEEDS_BROWSER", False))


def browser_message(p) -> str:
    t = getattr(p, "t", None)
    if t is not None and hasattr(t, "browser_message"):
        return t.browser_message()
    return getattr(p, "BROWSER_MESSAGE", "") if p is not None else ""


def browser_useful(p):
    """Funzione url → bool: quali richieste del browser servono (o None)."""
    t = getattr(p, "t", None)
    if t is not None and hasattr(t, "browser_useful"):
        return t.browser_useful
    rx = getattr(p, "BROWSER_USEFUL", "") if p is not None else ""
    if not rx:
        return None
    import re as _re
    c = _re.compile(rx, _re.I)
    return lambda url: bool(c.search(url))


def find_plugin(url: str):
    off = disabled()
    hits = [p for p in all_plugins() if getattr(p, "KEY", "") not in off and p.match(url)]
    if not hits:
        return None
    if any(getattr(p, "PREFERRED", False) for p in hits):
        return next(p for p in hits if getattr(p, "PREFERRED", False))
    best = max(_specificity(p, url) for p in hits)
    return next(p for p in hits if _specificity(p, url) == best)
