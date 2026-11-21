"""Registro: tutto quello che fa il motore finisce qui.

- File: una copia completa (livello DEBUG) di ogni sessione in <dati app>/log/,
  si tengono gli ultimi 20 file. Utile da mandare quando qualcosa non va.
- Finestra / Terminale: gli stessi messaggi, filtrati (INFO, oppure DEBUG con "Dettagliato").
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from .plugins import user_templates_dir

log = logging.getLogger("picfinder")
KEEP = 20
_file_handler: logging.Handler | None = None
FORMAT = "%(asctime)s %(levelname)-7s %(message)s"


def log_dir() -> Path:
    custom = os.environ.get("PICFINDER_LOGDIR")
    return Path(custom) if custom else user_templates_dir().parent / "log"


def setup_file_logging() -> Path | None:
    """Crea il file di log di questa sessione (una volta sola)."""
    global _file_handler
    log.setLevel(logging.DEBUG)
    if _file_handler is not None:
        return Path(_file_handler.baseFilename)
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        old = sorted(d.glob("picfinder-*.log"))
        for f in old[:-(KEEP - 1)] if len(old) >= KEEP else []:
            f.unlink(missing_ok=True)
        path = d / time.strftime("picfinder-%Y%m%d-%H%M%S.log")
        _file_handler = logging.FileHandler(path, encoding="utf-8")
        _file_handler.setLevel(logging.DEBUG)
        _file_handler.setFormatter(logging.Formatter(FORMAT, "%Y-%m-%d %H:%M:%S"))
        log.addHandler(_file_handler)
        return path
    except OSError:
        return None


def current_log_file() -> Path | None:
    return Path(_file_handler.baseFilename) if _file_handler else None


def short(url: str, n: int = 110) -> str:
    return url if len(url) <= n else url[: n - 40] + "…" + url[-39:]
