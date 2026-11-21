"""Progetti salvati (SQLite).

Un progetto ricorda: titolo, categoria, uno o più link, password, cartella, opzioni,
e quali file sono già stati scaricati. Così "Aggiorna" scarica solo i file nuovi,
anche se nel frattempo hai cancellato quelli vecchi dal disco.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .plugins import user_templates_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    links TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '',
    dest TEXT NOT NULL DEFAULT '',
    all_files INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    last_run REAL
);
CREATE TABLE IF NOT EXISTS files (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    size INTEGER,
    status TEXT NOT NULL,          -- done | skipped | failed
    updated REAL NOT NULL,
    PRIMARY KEY (project_id, url)
);
CREATE INDEX IF NOT EXISTS files_project ON files(project_id, status);
CREATE TABLE IF NOT EXISTS requests (
    day TEXT NOT NULL, site TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, site)
);
CREATE TABLE IF NOT EXISTS failures (
    ts REAL NOT NULL, site TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS phash (
    hash INTEGER NOT NULL, path TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS history (
    key TEXT PRIMARY KEY,          -- core.file_key(url): uguale anche se il link viene rifirmato
    path TEXT NOT NULL,
    size INTEGER,
    updated REAL NOT NULL
);
"""


@dataclass
class Project:
    title: str
    links: list[str] = field(default_factory=list)
    category: str = ""
    password: str = ""
    dest: str = ""
    all_files: bool = False
    id: int | None = None
    created: float = 0.0
    last_run: float | None = None
    saved: int = 0      # file salvati
    failed: int = 0     # file falliti (ultimo stato)
    priority: int = 1   # 7: 2 alta · 1 normale · 0 bassa (ordine nella coda)
    watch_hours: int = 0  # 16: controlla da solo ogni N ore (0 = mai)


def default_db_path() -> Path:
    return user_templates_dir().parent / "picfinder.db"


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(projects)")}
        with self.db:
            if "priority" not in cols:
                self.db.execute("ALTER TABLE projects ADD COLUMN priority INTEGER NOT NULL DEFAULT 1")
            if "watch_hours" not in cols:
                self.db.execute("ALTER TABLE projects ADD COLUMN watch_hours INTEGER NOT NULL DEFAULT 0")

    def close(self):
        self.db.close()

    def set_priority(self, project_id: int, priority: int) -> None:
        with self.db:
            self.db.execute("UPDATE projects SET priority = ? WHERE id = ?", (int(priority), project_id))

    def set_watch(self, project_id: int, hours: int) -> None:
        with self.db:
            self.db.execute("UPDATE projects SET watch_hours = ? WHERE id = ?", (int(hours), project_id))

    def due_for_watch(self) -> list[Project]:
        """16: progetti osservati il cui ultimo controllo è più vecchio del loro intervallo."""
        now = time.time()
        return [p for p in self.list()
                if p.watch_hours and (not p.last_run or now - p.last_run >= p.watch_hours * 3600)]

    # ---------- progetti ----------
    def _project(self, r: sqlite3.Row) -> Project:
        return Project(id=r["id"], title=r["title"], category=r["category"],
                       links=[x for x in r["links"].splitlines() if x.strip()],
                       password=r["password"], dest=r["dest"], all_files=bool(r["all_files"]),
                       created=r["created"], last_run=r["last_run"],
                       saved=r["saved"] or 0, failed=r["failed"] or 0,
                       priority=r["priority"] if "priority" in r.keys() else 1,
                       watch_hours=r["watch_hours"] if "watch_hours" in r.keys() else 0)

    _SELECT = """
        SELECT p.*,
               (SELECT COUNT(*) FROM files f WHERE f.project_id = p.id AND f.status IN ('done','skipped')) AS saved,
               (SELECT COUNT(*) FROM files f WHERE f.project_id = p.id AND f.status = 'failed') AS failed
        FROM projects p
    """

    def list(self) -> list[Project]:
        rows = self.db.execute(self._SELECT + " ORDER BY lower(p.category), lower(p.title)").fetchall()
        return [self._project(r) for r in rows]

    def get(self, project_id: int) -> Project | None:
        r = self.db.execute(self._SELECT + " WHERE p.id = ?", (project_id,)).fetchone()
        return self._project(r) if r else None

    def categories(self) -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT category FROM projects WHERE category != '' ORDER BY lower(category)")]

    def save(self, p: Project) -> int:
        links = "\n".join(x.strip() for x in p.links if x.strip())
        with self.db:
            if p.id is None:
                cur = self.db.execute(
                    "INSERT INTO projects (title, category, links, password, dest, all_files, created) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (p.title, p.category, links, p.password, p.dest, int(p.all_files), time.time()))
                p.id = cur.lastrowid
            else:
                self.db.execute(
                    "UPDATE projects SET title=?, category=?, links=?, password=?, dest=?, all_files=? WHERE id=?",
                    (p.title, p.category, links, p.password, p.dest, int(p.all_files), p.id))
        return p.id

    def delete(self, project_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def touch(self, project_id: int) -> None:
        with self.db:
            self.db.execute("UPDATE projects SET last_run = ? WHERE id = ?", (time.time(), project_id))

    def find(self, title_or_category: str) -> list[Project]:
        """Progetti con quel titolo, oppure tutti quelli di quella categoria."""
        key = title_or_category.strip().lower()
        return [p for p in self.list() if p.title.lower() == key or p.category.lower() == key]

    # ---------- file ----------
    def record(self, project_id: int, url: str, status: str, name: str = "", path: str = "",
               size: int | None = None) -> None:
        with self.db:
            # un file già salvato resta "salvato" anche se un nuovo tentativo fallisce
            self.db.execute(
                """INSERT INTO files (project_id, url, name, path, size, status, updated)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(project_id, url) DO UPDATE SET
                     name = CASE WHEN excluded.status = 'failed' AND files.status != 'failed'
                                 THEN files.name ELSE excluded.name END,
                     path = CASE WHEN excluded.path != '' THEN excluded.path ELSE files.path END,
                     size = COALESCE(excluded.size, files.size),
                     status = CASE WHEN excluded.status = 'failed' AND files.status != 'failed'
                                   THEN files.status ELSE excluded.status END,
                     updated = excluded.updated""",
                (project_id, url, name, path, size, status, time.time()))

    def known_urls(self, project_id: int) -> set[str]:
        """Indirizzi già scaricati (o già presenti): "Aggiorna" li salta."""
        return {r[0] for r in self.db.execute(
            "SELECT url FROM files WHERE project_id = ? AND status IN ('done','skipped')", (project_id,))}

    def known_paths(self, project_id: int) -> dict[str, str]:
        return {r[0]: r[1] for r in self.db.execute(
            "SELECT url, path FROM files WHERE project_id = ? AND status IN ('done','skipped')", (project_id,))}

    def files(self, project_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT url, name, path, size, status, updated FROM files WHERE project_id = ? ORDER BY updated",
            (project_id,))]

    def forget_file(self, project_id: int, url: str) -> None:
        """Per riscaricare un file: lo toglie dall'elenco dei già scaricati."""
        with self.db:
            self.db.execute("DELETE FROM files WHERE project_id = ? AND url = ?", (project_id, url))


class History:
    """Tutti i file scaricati, con o senza progetto: così non si riscaricano.
    Usabile dal thread dei download (connessione propria + lucchetto)."""

    def __init__(self, path: str | Path | None = None):
        import threading
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self.lock:
            r = self.db.execute("SELECT path FROM history WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def add(self, key: str, path: str, size: int | None = None) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO history (key, path, size, updated) VALUES (?,?,?,?)",
                            (key, path, size, time.time()))

    def count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM history").fetchone()[0]

    # --- 12: richieste per sito al giorno
    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d")

    def add_requests(self, site: str, n: int) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO requests (day, site, n) VALUES (?,?,?) "
                            "ON CONFLICT(day, site) DO UPDATE SET n = n + excluded.n", (self._today(), site, n))

    def requests_today(self, site: str) -> int:
        with self.lock:
            r = self.db.execute("SELECT n FROM requests WHERE day = ? AND site = ?", (self._today(), site)).fetchone()
        return r[0] if r else 0

    def requests_by_site(self, day: str | None = None) -> list[tuple[str, int]]:
        with self.lock:
            return self.db.execute("SELECT site, n FROM requests WHERE day = ? ORDER BY n DESC",
                                   (day or self._today(),)).fetchall()

    # --- 20: errori
    def add_failure(self, site: str, reason: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO failures (ts, site, reason) VALUES (?,?,?)", (time.time(), site, reason))

    def failures_by_site(self, days: int = 30) -> list[tuple[str, int]]:
        with self.lock:
            return self.db.execute("SELECT site, COUNT(*) FROM failures WHERE ts > ? GROUP BY site "
                                   "ORDER BY 2 DESC", (time.time() - days * 86400,)).fetchall()

    # --- 15: impronte delle foto
    def hashes(self) -> list[tuple[int, str]]:
        with self.lock:
            rows = self.db.execute("SELECT hash, path FROM phash").fetchall()
        return [(h + 2 ** 64 if h < 0 else h, p) for h, p in rows]

    def add_hash(self, h: int, path: str) -> None:
        if h >= 2 ** 63:
            h -= 2 ** 64                       # SQLite: interi con segno a 64 bit
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO phash (hash, path) VALUES (?,?)", (h, path))

    # --- 20: statistiche
    def stats(self) -> dict:
        with self.lock:
            files, size = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM history").fetchone()
            rows = self.db.execute("SELECT key, size, updated FROM history").fetchall()
        by_site: dict[str, list[int]] = {}
        week = time.time() - 7 * 86400
        recent = 0
        for key, sz, upd in rows:
            site = key.split("/", 1)[0]
            v = by_site.setdefault(site, [0, 0])
            v[0] += 1
            v[1] += sz or 0
            if upd and upd > week:
                recent += 1
        top = sorted(((k, v[0], v[1]) for k, v in by_site.items()), key=lambda x: -x[1])
        return {"files": files, "size": size, "week": recent, "by_site": top}

    def clear(self) -> None:
        with self.lock, self.db:
            self.db.execute("DELETE FROM history")

    def close(self):
        self.db.close()
