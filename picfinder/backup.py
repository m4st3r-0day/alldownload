"""Esporta / importa progetti e impostazioni (per cambiare computer o tenerne una copia).

Il file .zip contiene:
  settings.json          impostazioni (proxy e token GitHub solo se lo chiedi)
  picfinder.db           progetti, storico dei download, contatori
  templates/             i tuoi template
  template_disattivati.txt
I login del browser interno NON ci sono (sono dati personali e si rifanno in un minuto).
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
import zipfile
from pathlib import Path

from .plugins import user_templates_dir
from .projects import default_db_path
from .settings import Settings

MANIFEST = "alldownload-backup.json"


def _paths() -> dict[str, Path]:
    base = user_templates_dir().parent
    return {"settings": Settings.path(), "db": default_db_path(), "templates": user_templates_dir(),
            "disabled": base / "template_disattivati.txt"}


def export_zip(dest: Path, include_secrets: bool = False) -> dict:
    p = _paths()
    dest = Path(dest)
    info = {"version": 1, "created": time.time(), "secrets": include_secrets, "files": []}
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        if p["settings"].exists():
            data = json.loads(p["settings"].read_text(encoding="utf-8") or "{}")
            if not include_secrets:
                data["github_token"] = ""
                data["proxies"] = []
                data["proxy_list_url"] = ""
                data["proxy_mode"] = "off"
            z.writestr("settings.json", json.dumps(data, indent=2, ensure_ascii=False))
            info["files"].append("settings.json")
        if p["db"].exists():
            with tempfile.TemporaryDirectory() as tmp:          # copia coerente anche con l'app aperta
                copy = Path(tmp) / "picfinder.db"
                src = sqlite3.connect(p["db"])
                dst = sqlite3.connect(copy)
                with dst:
                    src.backup(dst)
                src.close()
                dst.close()
                z.write(copy, "picfinder.db")
            info["files"].append("picfinder.db")
        if p["templates"].is_dir():
            for f in sorted(p["templates"].glob("*.etmpl")):
                z.write(f, f"templates/{f.name}")
                info["files"].append(f"templates/{f.name}")
        if p["disabled"].exists():
            z.write(p["disabled"], "template_disattivati.txt")
            info["files"].append("template_disattivati.txt")
        z.writestr(MANIFEST, json.dumps(info, indent=2))
    return info


def read_manifest(src: Path) -> dict:
    with zipfile.ZipFile(src) as z:
        if MANIFEST not in z.namelist():
            raise ValueError("Non è un backup di AllDownload")
        return json.loads(z.read(MANIFEST))


def import_zip(src: Path) -> Path:
    """Rimette impostazioni, progetti e template dal backup. Prima salva una copia di quelli attuali.
    Ritorna il file con la copia di prima. Se nel backup non ci sono proxy/token, tiene quelli attuali."""
    src = Path(src)
    read_manifest(src)
    p = _paths()
    keep = p["db"].parent / f"prima-dell-importazione-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    export_zip(keep, include_secrets=True)
    with zipfile.ZipFile(src) as z:
        names = set(z.namelist())
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError("Backup non valido")
        if "settings.json" in names:
            new = json.loads(z.read("settings.json"))
            if p["settings"].exists():
                cur = json.loads(p["settings"].read_text(encoding="utf-8") or "{}")
                for k in ("github_token", "proxies", "proxy_list_url", "proxy_mode"):
                    if not new.get(k) and cur.get(k):
                        new[k] = cur[k]
            p["settings"].parent.mkdir(parents=True, exist_ok=True)
            p["settings"].write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")
        if "picfinder.db" in names:
            p["db"].parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as tmp:
                z.extract("picfinder.db", tmp)
                shutil.copy2(Path(tmp) / "picfinder.db", p["db"])
        p["templates"].mkdir(parents=True, exist_ok=True)
        for n in names:
            if n.startswith("templates/") and n.endswith(".etmpl"):
                (p["templates"] / Path(n).name).write_bytes(z.read(n))
        if "template_disattivati.txt" in names:
            p["disabled"].write_bytes(z.read("template_disattivati.txt"))
    return keep
