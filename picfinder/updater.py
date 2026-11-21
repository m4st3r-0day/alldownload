"""Aggiornamenti dall'app: controlla GitHub, mostra le novità, scarica e installa.

Da dove legge la nuova versione (in quest'ordine):
1. l'ultima «Release» del repo (titolo + note);
2. se non ci sono release: il tag vX.Y.Z più alto, con le note prese dalla sezione giusta di CHANGELOG.md.

Come installa:
- app avviata dal codice (Avvia PicFinder.command): scarica il codice di quella versione, salva una copia
  di quello attuale in «backup», sostituisce i file (mai impostazioni, log, login del browser, .venv),
  reinstalla le librerie se sono cambiate, riavvia;
- app impacchettata (.app / .exe): scarica il file della release per il tuo sistema
  (es. AllDownload-mac.zip) e lo mette al posto di quella vecchia dopo la chiusura.

Il repo è pubblico: il token GitHub non serve (facoltativo, solo se GitHub limita le richieste).
Il token non finisce mai nei log.
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from . import __version__

log = logging.getLogger("picfinder.update")

REPO = "m4st3r-0day/alldownload"
API = "https://api.github.com"
# mai toccati da un aggiornamento
KEEP = {"settings.json", "log", "browser-profilo", ".venv", ".git", "_to_delete", "backup",
        "download_in_sospeso.json", "limiti_siti.json"}

Progress = Callable[[int, int], None]          # (fatti, totale) in byte; totale 0 = sconosciuto


class UpdateError(Exception):
    pass


@dataclass
class UpdateInfo:
    version: str
    title: str = ""
    notes: str = ""                 # markdown
    published: str = ""
    page_url: str = ""
    source_url: str = ""            # zip del codice di quella versione
    asset_url: str = ""             # file per l'app impacchettata (se c'è)
    asset_name: str = ""
    sums_url: str = ""              # SHA256SUMS (se c'è)
    from_release: bool = True
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- versioni
def parse_version(v: str) -> tuple:
    """«v1.2.10» → (1, 2, 10, 1). Le pre-release (1.2.0-beta) valgono meno della finale."""
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$", v or "")
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), 0 if m.group(4).strip() else 1)


def is_newer(remote: str, local: str | None = None) -> bool:
    return parse_version(remote) > parse_version(local or __version__)


def changelog_section(text: str, version: str) -> str:
    """Prende da CHANGELOG.md la parte «## [1.2.0] …» fino alla versione dopo."""
    v = re.escape(version.lstrip("v"))
    m = re.search(rf"^##\s*\[?v?{v}\]?.*?$\n(.*?)(?=^##\s|\Z)", text or "", re.M | re.S)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------- GitHub
def _headers(token: str = "", raw: bool = False) -> dict:
    h = {"Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": f"AllDownload/{__version__}"}
    if token.strip():
        h["Authorization"] = f"Bearer {token.strip()}"
    return h


def _get(client: httpx.Client, url: str, token: str, raw: bool = False) -> httpx.Response:
    r = client.get(url, headers=_headers(token, raw))
    if r.status_code == 401:
        raise UpdateError("Il token GitHub non è valido o è scaduto.")
    if r.status_code == 403 and r.headers.get("x-ratelimit-remaining") == "0":
        raise UpdateError("GitHub: troppe richieste. Riprova tra un'ora (o aggiungi un token).")
    return r


def check(token: str = "", repo: str = REPO, timeout: float = 15) -> UpdateInfo | None:
    """None = sei già all'ultima versione. Errore leggibile se non si può controllare."""
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        r = _get(c, f"{API}/repos/{repo}/releases/latest", token)
        if r.status_code == 200:
            d = r.json()
            info = _from_release(d)
        elif r.status_code == 404:
            info = _from_tags(c, repo, token)
        else:
            raise UpdateError(f"GitHub risponde {r.status_code}.")
    if info is None or not is_newer(info.version):
        return None
    return info


def _from_release(d: dict) -> UpdateInfo:
    tag = d.get("tag_name") or ""
    info = UpdateInfo(version=tag.lstrip("v"), title=d.get("name") or tag, notes=d.get("body") or "",
                      published=(d.get("published_at") or "")[:10], page_url=d.get("html_url") or "",
                      source_url=d.get("zipball_url") or "")
    want = {"darwin": "mac", "win32": "win"}.get(sys.platform, "linux")
    for a in d.get("assets") or []:
        name = (a.get("name") or "")
        low = name.lower()
        if low in ("sha256sums", "sha256sums.txt"):
            info.sums_url = a.get("url") or ""
        elif want in low and low.endswith((".zip", ".tar.gz")):
            info.asset_url, info.asset_name = a.get("url") or "", name
    return info


def _from_tags(c: httpx.Client, repo: str, token: str) -> UpdateInfo | None:
    r = _get(c, f"{API}/repos/{repo}/tags?per_page=50", token)
    if r.status_code == 404:
        raise UpdateError("Non trovo il repo: se è privato serve un token GitHub "
                          "(Impostazioni → Generale → Aggiornamenti).")
    if r.status_code != 200:
        raise UpdateError(f"GitHub risponde {r.status_code}.")
    tags = [t for t in r.json() if re.match(r"^v?\d+(\.\d+)*", t.get("name") or "")]
    if not tags:
        return None
    best = max(tags, key=lambda t: parse_version(t["name"]))
    tag = best["name"]
    notes = ""
    cr = _get(c, f"{API}/repos/{repo}/contents/CHANGELOG.md?ref={tag}", token, raw=True)
    if cr.status_code == 200:
        notes = changelog_section(cr.text, tag)
    return UpdateInfo(version=tag.lstrip("v"), title=f"AllDownload {tag.lstrip('v')}", notes=notes,
                      page_url=f"https://github.com/{repo}/releases/tag/{tag}",
                      source_url=f"{API}/repos/{repo}/zipball/{tag}", from_release=False)


# ---------------------------------------------------------------- scaricare
def download(url: str, token: str = "", progress: Progress | None = None, binary_asset: bool = False) -> bytes:
    h = _headers(token)
    if binary_asset:
        h["Accept"] = "application/octet-stream"
    buf = io.BytesIO()
    with httpx.Client(timeout=60, follow_redirects=True) as c:
        with c.stream("GET", url, headers=h) as r:
            if r.status_code != 200:
                raise UpdateError(f"Download dell'aggiornamento non riuscito (errore {r.status_code}).")
            total = int(r.headers.get("content-length") or 0)
            for chunk in r.iter_bytes(65536):
                buf.write(chunk)
                if progress:
                    progress(buf.tell(), total)
    return buf.getvalue()


def verify_sha256(data: bytes, name: str, sums_text: str) -> None:
    """Se la release ha SHA256SUMS, il file deve combaciare."""
    want = None
    for line in sums_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == name:
            want = parts[0].lower()
    if want and hashlib.sha256(data).hexdigest() != want:
        raise UpdateError("Il file scaricato non corrisponde al controllo SHA-256: aggiornamento annullato.")


# ---------------------------------------------------------------- dove e come installare
def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def install_mode() -> str:
    """«frozen» (app impacchettata), «source» (cartella del codice scrivibile) o «none»."""
    if getattr(sys, "frozen", False):
        return "frozen"
    root = project_root()
    if (root / "pyproject.toml").exists() and (root / "picfinder" / "__init__.py").exists() \
            and os.access(root / "picfinder", os.W_OK):
        return "source"
    return "none"


def _skip(rel: Path) -> bool:
    return bool(rel.parts) and (rel.parts[0] in KEEP or "__pycache__" in rel.parts)


def apply_source(zip_bytes: bytes, root: Path | None = None, backup_base: Path | None = None) -> dict:
    """Mette il codice nuovo al posto di quello vecchio. Ritorna {"backup": cartella, "deps_changed": bool}."""
    root = root or project_root()
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as e:
        raise UpdateError("Il file scaricato è rovinato.") from e
    names = zf.namelist()
    top = names[0].split("/")[0] + "/" if names and "/" in names[0] else ""
    if f"{top}picfinder/__init__.py" not in names:
        raise UpdateError("Il pacchetto scaricato non sembra AllDownload: non installo niente.")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for n in names:                       # estrazione sicura: niente percorsi che escono dalla cartella
            rel = Path(n[len(top):])
            if not n.startswith(top) or not rel.parts or ".." in rel.parts or rel.is_absolute():
                continue
            if n.endswith("/") or _skip(rel):
                continue
            dest = tmp / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(n))
        old_py = (root / "pyproject.toml").read_bytes() if (root / "pyproject.toml").exists() else b""
        new_py = (tmp / "pyproject.toml").read_bytes() if (tmp / "pyproject.toml").exists() else b""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = (backup_base or root / "backup") / f"{__version__}-{stamp}"
        files = [p for p in tmp.rglob("*") if p.is_file()]
        for p in files:                       # 1. copia di sicurezza di quello che cambia
            rel = p.relative_to(tmp)
            cur = root / rel
            if cur.exists():
                (backup / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cur, backup / rel)
        for p in files:                       # 2. file nuovi al loro posto
            rel = p.relative_to(tmp)
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, root / rel)
    log.info("Aggiornamento: %d file sostituiti, copia di prima in %s", len(files), backup)
    return {"backup": backup, "deps_changed": old_py != new_py, "files": len(files)}


def restore_backup(backup: Path, root: Path | None = None) -> None:
    root = root or project_root()
    for p in backup.rglob("*"):
        if p.is_file():
            shutil.copy2(p, root / p.relative_to(backup))


def install_deps(root: Path | None = None) -> None:
    root = root or project_root()
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(root)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise UpdateError("Le librerie nuove non si installano:\n" + (r.stderr or r.stdout)[-800:])


RELAUNCH = r"""
import os, subprocess, sys, time
pid = int(sys.argv[1])
for _ in range(240):                      # aspetta che la vecchia app sia chiusa (max 2 minuti)
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
            if str(pid) not in out:
                break
        else:
            os.kill(pid, 0)
    except OSError:
        break
    time.sleep(0.5)
time.sleep(0.5)
subprocess.Popen([sys.executable, "-m", "picfinder"])
"""


def restart_source() -> None:
    """Riapre l'app quando questa si è chiusa (stesso Python, stesse variabili d'ambiente):
    così il browser interno non trova il profilo ancora occupato."""
    root = project_root()
    kw = {"start_new_session": True} if os.name != "nt" else \
        {"creationflags": getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    subprocess.Popen([sys.executable, "-c", RELAUNCH, str(os.getpid())], cwd=str(root), env=dict(os.environ), **kw)


# ---------------------------------------------------------------- app impacchettata
def frozen_app_path() -> Path:
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for p in exe.parents:
            if p.suffix == ".app":
                return p
    return exe.parent


def apply_frozen(archive: bytes, name: str) -> None:
    """Prepara la sostituzione e la lancia: uno script aspetta che l'app si chiuda, poi copia e riapre."""
    work = Path(tempfile.mkdtemp(prefix="alldownload-update-"))
    arc = work / name
    arc.write_bytes(archive)
    new = work / "new"
    new.mkdir()
    if name.endswith(".zip"):
        if sys.platform == "darwin":          # ditto tiene permessi e collegamenti dentro la .app
            subprocess.run(["ditto", "-x", "-k", str(arc), str(new)], check=True)
        else:
            zipfile.ZipFile(arc).extractall(new)
    else:
        import tarfile
        with tarfile.open(arc) as t:
            t.extractall(new, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(new)
    target = frozen_app_path()
    pid = os.getpid()
    if sys.platform == "darwin":
        apps = list(new.glob("*.app")) or list(new.glob("*/*.app"))
        if not apps:
            raise UpdateError("Nel pacchetto non c'è AllDownload.app.")
        script = work / "update.sh"
        script.write_text(f"""#!/bin/bash
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
rm -rf "{target}.old"; mv "{target}" "{target}.old" && ditto "{apps[0]}" "{target}" && rm -rf "{target}.old" \\
  || {{ rm -rf "{target}"; mv "{target}.old" "{target}"; }}
xattr -dr com.apple.quarantine "{target}" 2>/dev/null
open "{target}"
""")
        script.chmod(0o755)
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)
    elif os.name == "nt":
        src = next((p.parent for p in new.rglob("AllDownload.exe")), new)
        script = work / "update.bat"
        script.write_text(f"""@echo off
:wait
tasklist /FI "PID eq {pid}" | find "{pid}" >nul && (timeout /t 1 >nul & goto wait)
robocopy "{src}" "{target}" /E /NFL /NDL /NJH /NJS >nul
start "" "{target / 'AllDownload.exe'}"
""")
        subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x00000008)   # DETACHED_PROCESS
    else:
        src = next((p.parent for p in new.rglob("AllDownload")), new)
        script = work / "update.sh"
        script.write_text(f"""#!/bin/bash
while kill -0 {pid} 2>/dev/null; do sleep 0.5; done
cp -a "{src}/." "{target}/" && "{target}/AllDownload" &
""")
        script.chmod(0o755)
        subprocess.Popen(["/bin/bash", str(script)], start_new_session=True)
