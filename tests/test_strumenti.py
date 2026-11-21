"""Libreria (cerca nei file scaricati), backup esporta/importa, controllo dei siti."""
import json
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest

from picfinder import backup, library, sitecheck
from picfinder.plugins import user_templates_dir
from picfinder.projects import Project, default_db_path
from picfinder.settings import Settings


def _db(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE history(key TEXT PRIMARY KEY, path TEXT NOT NULL, size INTEGER, updated REAL NOT NULL)")
    con.executemany("INSERT INTO history VALUES (?,?,?,?)", [(str(i), p, s, t) for i, (p, s, t) in enumerate(rows)])
    con.commit()
    con.close()


def test_library_search(tmp_path):
    root = tmp_path / "dl"
    (root / "Vacanze").mkdir(parents=True)
    (root / "Gatti").mkdir()
    a = root / "Vacanze" / "mare 01.jpg"
    b = root / "Gatti" / "micio.mp4"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    gone = root / "Gatti" / "vecchio.png"
    db = tmp_path / "h.db"
    _db(db, [(str(a), 1, 3.0), (str(b), 2, 2.0), (str(gone), 3, 1.0)])
    rows = library.load_rows(db)
    assert [Path(r[0]).name for r in rows] == ["mare 01.jpg", "micio.mp4", "vecchio.png"]
    assert [Path(r[0]).name for r in library.search(rows, "mare")] == ["mare 01.jpg"]
    assert [Path(r[0]).name for r in library.search(rows, kind="video")] == ["micio.mp4"]
    assert len(library.search(rows, folder="gatti")) == 1          # il file sparito non c'è
    assert len(library.search(rows, folder="gatti", existing_only=False)) == 2
    assert library.top_folders(rows, root)[0] == "Gatti"
    assert library.load_rows(tmp_path / "nessuno.db") == []


def test_backup_roundtrip_hides_secrets(tmp_path):
    cfg = Settings.path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps({"language": "en", "github_token": "ghp_SEGRETO", "proxy_mode": "list",
                               "proxies": [{"host": "1.2.3.4", "port": 8080, "password": "pw"}]}))
    db = default_db_path()
    _db(db, [("/x/a.jpg", 1, time.time())])
    tdir = user_templates_dir()
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "mio.etmpl").write_text("<x/>")

    out = tmp_path / "b.zip"
    info = backup.export_zip(out)
    assert set(info["files"]) >= {"settings.json", "picfinder.db", "templates/mio.etmpl"}
    with zipfile.ZipFile(out) as z:
        data = z.read("settings.json").decode()
    assert "ghp_SEGRETO" not in data and "1.2.3.4" not in data and '"language": "en"' in data

    # cambio tutto, poi importo: lingua e template tornano, i segreti di adesso restano
    cfg.write_text(json.dumps({"language": "it", "github_token": "ghp_NUOVO"}))
    (tdir / "mio.etmpl").unlink()
    db.unlink()
    keep = backup.import_zip(out)
    assert keep.exists()
    now = json.loads(cfg.read_text())
    assert now["language"] == "en" and now["github_token"] == "ghp_NUOVO"
    assert (tdir / "mio.etmpl").exists()
    assert library.load_rows(db)[0][0] == "/x/a.jpg"


def test_backup_with_secrets_and_bad_zip(tmp_path):
    Settings.path().parent.mkdir(parents=True, exist_ok=True)
    Settings.path().write_text(json.dumps({"github_token": "ghp_X"}))
    out = tmp_path / "s.zip"
    backup.export_zip(out, include_secrets=True)
    with zipfile.ZipFile(out) as z:
        assert "ghp_X" in z.read("settings.json").decode()
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("ciao.txt", "x")
    with pytest.raises(ValueError):
        backup.import_zip(bad)


def test_sitecheck_one_link_per_site():
    old = Project("a", ["https://www.gofile.io/d/AAA", "https://pixeldrain.com/l/1"], created=1)
    new = Project("b", ["https://gofile.io/d/BBB"], created=5)
    sites = sitecheck.links_by_site([old, new])
    assert sites == {"gofile.io": "https://gofile.io/d/BBB", "pixeldrain.com": "https://pixeldrain.com/l/1"}


def test_sitecheck_reports(monkeypatch, tmp_path):
    async def fake(dest, link, limit=3, timeout=90):
        if "rotto" in link:
            return 0, "pagina non trovata (404)"
        return (0, "") if "vuoto" in link else (7, "")

    monkeypatch.setattr(sitecheck, "_check_one", fake)
    monkeypatch.setattr(sitecheck.plugins, "find_plugin", lambda u: None if "nessuno" in u else object())
    monkeypatch.setattr(sitecheck.plugins, "needs_browser", lambda p: False)
    ps = [Project("x", ["https://ok.example/a", "https://rotto.example/a", "https://vuoto.example/a",
                        "https://nessuno.example/a"])]
    got = {r.site: r.status for r in sitecheck.check_sites(ps, tmp_path)}
    assert got == {"ok.example": "ok", "rotto.example": "error", "vuoto.example": "empty",
                   "nessuno.example": "skipped"}
