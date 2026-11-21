"""Avvio dell'app AllDownload.app (PyInstaller). Apre sempre la finestra."""
import faulthandler
import os
import sys
from pathlib import Path

# in un'app senza Terminale stdout/stderr possono mancare: le scritte non devono far cadere l'app
for name in ("stdout", "stderr"):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w"))

# se Qt o Python vanno in crash, il motivo finisce in un file (invece di sparire)
try:
    from picfinder.logs import log_dir
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    faulthandler.enable(open(d / "crash.log", "a", buffering=1))
except Exception:  # noqa: BLE001
    pass

from picfinder.gui import main  # noqa: E402

if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if not a.startswith("-psn_")]   # argomento che a volte aggiunge il Finder
    sys.exit(main())
