"""Uso: python -m picfinder <link> [-o cartella] [-p password] [--tutti]"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .core import DEFAULT_PATTERNS, Downloader, PluginError


def update_project(store, p, transport=None) -> int:
    """Scarica solo i file nuovi di un progetto. Restituisce il numero di errori."""
    known = store.known_urls(p.id)

    def on_event(kind, d):
        f = d.get("file")
        if kind in ("done", "skipped", "failed") and f is not None:
            path = d.get("path")
            store.record(p.id, f.url, kind, getattr(path, "name", f.name), str(path or ""))
            mark = {"done": "✓", "skipped": "=", "failed": "✗"}[kind]
            print(f"  {mark} {path or f.name}")
        elif kind == "warning":
            print(f"  ⚠ {d['message']}")

    dl = Downloader(p.dest or "Download", None if p.all_files else DEFAULT_PATTERNS, on_event=on_event,
                    transport=transport)
    try:
        files = asyncio.run(dl.scan_many(p.links, p.password or None))
    except PluginError as e:
        print(f"  Errore: {e}", file=sys.stderr)
        return 1
    new = [f for f in files if f.url not in known]
    print(f"  {len(files)} file trovati, {len(new)} nuovi")
    stats = asyncio.run(dl.download(new)) if new else {"failed": 0}
    store.touch(p.id)
    return stats["failed"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="picfinder", description="Scarica foto e video da link condivisi.")
    ap.add_argument("url", nargs="?", help="link da scaricare (senza link apre la finestra)")
    ap.add_argument("-o", "--output", default="Download", help="cartella di destinazione")
    ap.add_argument("-p", "--password", help="password del link, se serve")
    ap.add_argument("-j", "--paralleli", type=int, default=0, help="download contemporanei (0 = dalle Impostazioni)")
    ap.add_argument("--proxy", help="proxy da usare, es. socks5://127.0.0.1:1080 o http://host:porta")
    ap.add_argument("--tutti", action="store_true", help="scarica tutti i tipi di file, non solo foto/video")
    ap.add_argument("--template", action="store_true", help="mostra i template e se sono attivi")
    ap.add_argument("-v", "--dettagli", action="store_true",
                    help="mostra nel Terminale tutto il registro (ogni richiesta, ogni link scartato)")
    ap.add_argument("--progetti", action="store_true", help="mostra i progetti salvati")
    ap.add_argument("--aggiorna", metavar="NOME", action="append",
                    help="aggiorna un progetto o un'intera categoria (solo file nuovi); ripetibile. "
                         "Usa \"tutti\" per tutti i progetti")
    args = ap.parse_args(argv)

    from .logs import FORMAT, setup_file_logging
    logfile = setup_file_logging()
    if args.dettagli:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter(FORMAT, "%H:%M:%S"))
        logging.getLogger("picfinder").addHandler(h)
    if logfile and args.url:
        print(f"Registro completo: {logfile}")

    if args.progetti or args.aggiorna:
        from .projects import Store
        store = Store()
        if args.progetti:
            for p in store.list():
                print(f"{p.id:>4}  {p.category or '-':<16} {p.title:<30} {p.saved} file  {len(p.links)} link")
            return 0
        names = args.aggiorna
        projects = store.list() if [n.lower() for n in names] == ["tutti"] else \
            [p for n in names for p in store.find(n)]
        if not projects:
            print("Nessun progetto con questo nome o categoria. Vedi: python -m picfinder --progetti",
                  file=sys.stderr)
            return 2
        failed = 0
        for p in projects:
            print(f"\n== {p.title} ==")
            failed += update_project(store, p)
        return 1 if failed else 0

    if args.template:
        from . import plugins
        for e in sorted(plugins.entries(), key=lambda e: e["service"].lower()):
            hard = any(l == "hard" for l, _ in e["issues"])
            real = [i for i in e["issues"] if i[0] != "info"]
            state = "parziale" if hard else ("supportato" if e.get("tested") else
                                             ("da provare" if real else "compatibile"))
            print(f"[{'x' if e['enabled'] else ' '}] {e['service']:<16} {e['kind'] or '-':<12} "
                  f"{state:<12} {e['key']}")
            for lvl, t in e["issues"]:
                print(f"      {'✗' if lvl == 'hard' else '◐'} {t}")
        return 0

    if not args.url:
        from .gui import main as gui_main
        return gui_main()

    def on_event(kind: str, d: dict) -> None:
        if kind == "plugin":
            print(f"Template: {d['name']}")
        elif kind == "found":
            print(f"\rTrovati: {d['total']}", end="", flush=True)
        elif kind == "done":
            print(f"\n  ✓ {d['path']}", end="")
        elif kind == "skipped":
            print(f"\n  = già presente: {d['path']}", end="")
        elif kind == "retry":
            print(f"\n  ! nuovo tentativo {d['attempt']} per {d['file'].name}: {d['error']}", end="")
        elif kind == "failed":
            print(f"\n  ✗ fallito: {d['file'].name}", end="")
        elif kind == "warning":
            print(f"\n  ⚠ {d['message']}", end="")
        elif kind == "filtered":
            print(f"\n  - saltato ({d['reason']}): {d['file'].name}", end="")
        elif kind == "finished":
            print(f"\n\nFatto. Scaricati {d['done']}, già presenti {d['skipped']}, falliti {d['failed']}.")

    from .proxies import ProxyPool
    from .settings import Settings
    cfg = Settings.load()
    pool = None if args.proxy or cfg.proxy_mode == "off" or not cfg.enabled_proxies() else \
        ProxyPool(cfg.enabled_proxies(), cfg.proxy_mode, cfg.proxy_test_url)
    dl = Downloader(args.output, None if args.tutti else DEFAULT_PATTERNS,
                    concurrency=args.paralleli or cfg.parallel, on_event=on_event, proxy=args.proxy,
                    proxy_pool=pool, per_host=cfg.per_host, retries=cfg.retries, timeout=cfg.timeout,
                    speed_limit_kbps=cfg.speed_limit_kbps, default_conflicts=cfg.default_conflicts,
                    user_agent=cfg.custom_user_agent or None, folder_per_link=cfg.folder_per_link,
                    split_by_type=cfg.split_by_type)
    try:
        stats = asyncio.run(dl.run(args.url, args.password))
    except PluginError as e:
        print(f"Errore: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrotto.")
        return 130
    return 0 if stats["failed"] == 0 else 1
