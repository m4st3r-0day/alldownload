"""Cerca nei file già scaricati (per nome, cartella/profilo, tipo, data).

Legge lo storico dei download (tabella «history»): ogni file scaricato, con percorso, grandezza e data.
Doppio clic = mostra il file nel Finder / in Esplora risorse.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .core import kind_of
from .i18n import tr, translate_tree


def load_rows(db_path: Path, limit: int = 100_000) -> list[tuple[str, int | None, float]]:
    """[(percorso, grandezza, data)] dal più recente."""
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error:
        return []
    try:
        return con.execute("SELECT path, size, updated FROM history ORDER BY updated DESC LIMIT ?",
                           (limit,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()


def search(rows, text: str = "", kind: str = "all", folder: str = "", existing_only: bool = True) -> list:
    """Filtra le righe. kind: all | image | video | other."""
    words = [w for w in text.lower().split() if w]
    out = []
    for path, size, ts in rows:
        p = Path(path)
        low = str(p).lower()
        if words and not all(w in low for w in words):
            continue
        if kind != "all" and kind_of(p.name) != kind:
            continue
        if folder and folder.lower() not in [x.lower() for x in p.parts]:
            continue
        if existing_only and not p.exists():
            continue
        out.append((path, size, ts))
    return out


def top_folders(rows, root: Path | None) -> list[str]:
    """Le cartelle sotto la cartella dei download (di solito profili o album)."""
    seen = {}
    for path, _s, _t in rows:
        p = Path(path)
        try:
            rel = p.relative_to(root) if root else None
        except ValueError:
            rel = None
        name = rel.parts[0] if rel is not None and len(rel.parts) > 1 else (p.parent.parent.name if root is None else "")
        if name:
            seen[name] = seen.get(name, 0) + 1
    return [k for k, _ in sorted(seen.items(), key=lambda kv: -kv[1])]


def reveal(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(Path(path))])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))


class _Row(QTreeWidgetItem):
    """Ordina grandezza e data per numero, non per testo."""
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col in (2, 3):
            return (self.data(col, Qt.UserRole) or 0) < (other.data(col, Qt.UserRole) or 0)
        return self.text(col).lower() < other.text(col).lower()


class LibraryDialog(QDialog):
    def __init__(self, parent, db_path: Path, dest_root: str | None, human_size):
        super().__init__(parent)
        self.setWindowTitle(tr("Cerca nei file scaricati"))
        self.resize(920, 600)
        self.human_size = human_size
        self.rows = load_rows(db_path)
        self.root = Path(dest_root) if dest_root else None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        self.q = QLineEdit(placeholderText=tr("Nome del file, cartella, profilo…"))
        self.q.setObjectName("filter")
        self.q.setClearButtonEnabled(True)
        self.kind = QComboBox()
        for k, t in (("all", "Tutti i tipi"), ("image", "Foto"), ("video", "Video"), ("other", "Altri")):
            self.kind.addItem(tr(t), k)
        self.folder = QComboBox()
        self.folder.addItem(tr("Tutte le cartelle"), "")
        for f in top_folders(self.rows, self.root):
            self.folder.addItem(f, f)
        self.gone = QCheckBox(tr("Anche spostati o cancellati"))
        bar.addWidget(self.q, 1)
        bar.addWidget(self.kind)
        bar.addWidget(self.folder)
        bar.addWidget(self.gone)
        lay.addLayout(bar)
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr("Nome"), tr("Cartella"), tr("Dimensione"), tr("Scaricato")])
        self.list.setRootIsDecorated(False)
        self.list.setAlternatingRowColors(True)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(3, Qt.DescendingOrder)        # i più recenti in alto
        h = self.list.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        self.list.setColumnWidth(1, 260)
        self.list.setColumnWidth(2, 90)
        self.list.setColumnWidth(3, 140)
        self.list.itemDoubleClicked.connect(lambda it, _c: reveal(it.data(0, Qt.UserRole)))
        lay.addWidget(self.list, 1)
        foot = QHBoxLayout()
        self.count = QLabel(objectName="muted")
        show = QPushButton(tr("Mostra nel Finder") if sys.platform == "darwin" else tr("Mostra nella cartella"))
        show.clicked.connect(self._reveal_selected)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.accept)
        foot.addWidget(self.count, 1)
        foot.addWidget(show)
        foot.addWidget(close)
        lay.addLayout(foot)
        self._timer = QTimer(self, singleShot=True, interval=180, timeout=self.refresh)
        self.q.textChanged.connect(lambda _t: self._timer.start())
        for w in (self.kind, self.folder):
            w.currentIndexChanged.connect(lambda _i: self.refresh())
        self.gone.toggled.connect(lambda _b: self.refresh())
        translate_tree(self)
        self.refresh()

    def refresh(self):
        res = search(self.rows, self.q.text(), self.kind.currentData(), self.folder.currentData() or "",
                     existing_only=not self.gone.isChecked())
        self.list.setSortingEnabled(False)
        self.list.clear()
        items = []
        for path, size, ts in res[:5000]:
            p = Path(path)
            rel = p.parent
            if self.root is not None:
                try:
                    rel = p.parent.relative_to(self.root)
                except ValueError:
                    pass
            it = _Row([p.name, str(rel), self.human_size(size), time.strftime("%d/%m/%Y %H:%M",
                                                                                         time.localtime(ts))])
            it.setData(0, Qt.UserRole, path)
            it.setToolTip(0, path)
            it.setData(2, Qt.UserRole, size or 0)
            it.setData(3, Qt.UserRole, ts)
            items.append(it)
        self.list.addTopLevelItems(items)
        self.list.setSortingEnabled(True)
        extra = tr(" (ne mostro 5000)") if len(res) > 5000 else ""
        self.count.setText(tr("{n} file", n=len(res)) + extra)

    def _reveal_selected(self):
        for it in self.list.selectedItems()[:10]:
            reveal(it.data(0, Qt.UserRole))
