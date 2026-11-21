"""Barra laterale dei progetti: categorie, contatori, nuovo/elimina, coda di aggiornamento."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from .projects import Project, Store
from .i18n import tr
from .icons import icon

QUICK = ("quick", None)


def when(ts: float | None) -> str:
    if not ts:
        return tr("mai aggiornato")
    d = time.time() - ts
    if d < 120:
        return tr("aggiornato ora")
    if d < 3600:
        return tr("aggiornato {n} min fa", n=int(d // 60))
    if d < 86400:
        return tr("aggiornato {n} h fa", n=int(d // 3600))
    return tr("aggiornato il {d}", d=time.strftime("%d/%m/%Y", time.localtime(ts)))


class ProjectsPanel(QFrame):
    opened = Signal(object)        # Project oppure None (= download rapido)
    update_requested = Signal(list)  # lista di id da aggiornare in coda
    new_requested = Signal()

    def __init__(self, store: Store, colors: dict):
        super().__init__()
        self.setObjectName("flat")
        self.store = store
        self.colors = colors
        self.setMinimumWidth(220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setContentsMargins(8, 0, 0, 0)
        t = QLabel("Progetti")
        t.setObjectName("section")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setIndentation(14)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemSelectionChanged.connect(self._on_selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self._update_selected())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        lay.addWidget(self.tree, 1)

        self.hint = QLabel("")
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

        row = QHBoxLayout()
        row.setSpacing(2)
        b_new = QPushButton(icon("plus", colors["muted"], 15), "", objectName="iconbtn")
        b_new.setToolTip("Nuovo progetto vuoto")
        b_new.clicked.connect(self.new_requested.emit)
        row.addWidget(b_new)
        self.b_update = QPushButton(icon("refresh", colors["muted"], 14), " Aggiorna", objectName="ghost")
        self.b_update.setToolTip("Scarica solo i file nuovi dei progetti selezionati (anche intere categorie), "
                                 "uno dopo l'altro")
        self.b_update.clicked.connect(self._update_selected)
        self.b_delete = QPushButton(icon("minus", colors["muted"], 15), "", objectName="iconbtn")
        self.b_delete.setToolTip("Elimina il progetto (i file scaricati restano sul disco)")
        self.b_delete.clicked.connect(self._delete_selected)
        row.addWidget(self.b_delete)
        row.addStretch()
        row.addWidget(self.b_update)
        lay.addLayout(row)
        self._muting = False
        self.refresh()

    # ---------- contenuto ----------
    def refresh(self, select_id: int | None = None, quick: bool = False):
        self._muting = True
        current = select_id if select_id is not None else self.current_id()
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        q = QTreeWidgetItem([tr("Download rapido")])
        q.setIcon(0, icon("bolt", self.colors.get("accent", "#007AFF"), 16))
        q.setData(0, Qt.UserRole, QUICK)
        q.setToolTip(0, tr("Scarica senza salvare un progetto"))
        self.tree.addTopLevelItem(q)

        projects = self.store.list()
        cats: dict[str, QTreeWidgetItem] = {}
        target = None
        for p in projects:
            cat = p.category or tr("Senza categoria")
            if cat not in cats:
                c = QTreeWidgetItem([cat])
                c.setData(0, Qt.UserRole, ("cat", cat))
                c.setFont(0, bold)
                c.setForeground(0, QColor(self.colors["muted"]))
                self.tree.addTopLevelItem(c)
                c.setExpanded(True)
                cats[cat] = c
            text = f"{p.title}  ({p.saved}" + (f"/-{p.failed}" if p.failed else "") + ")"
            it = QTreeWidgetItem([text])
            if p.watch_hours:
                it.setIcon(0, icon("eye", self.colors["muted"], 14))
            elif p.priority == 2:
                it.setIcon(0, icon("chevron-up", "#D97706", 14))
            elif p.priority == 0:
                it.setIcon(0, icon("chevron-down", self.colors["muted"], 14))
            it.setData(0, Qt.UserRole, ("prj", p.id))
            it.setToolTip(0, f"{p.title}\n" + tr("{a} link · {b} file salvati", a=len(p.links), b=p.saved)
                             + (" · " + tr("{n} non salvati", n=p.failed) if p.failed else "")
                             + f"\n{when(p.last_run)}"
                             + (("\n" + tr("Controllato da solo ogni {n} h", n=p.watch_hours)) if p.watch_hours else "")
                             + ("\n" + tr("Priorità alta") if p.priority == 2 else
                                "\n" + tr("Priorità bassa") if p.priority == 0 else ""))
            cats[cat].addChild(it)
            if p.id == current:
                target = it
        for c in cats.values():
            c.setText(0, f"{c.text(0)}  ·  {c.childCount()}")
        self.tree.setCurrentItem(q if quick or target is None else target)
        self._muting = False
        self._update_hint()
        if not projects:
            self.hint.setText(tr("Nessun progetto salvato. Apri «Opzioni», scrivi un nome e premi «Salva progetto»."))

    def current_id(self) -> int | None:
        it = self.tree.currentItem()
        if it:
            kind, val = it.data(0, Qt.UserRole)
            if kind == "prj":
                return val
        return None

    def selected_ids(self) -> list[int]:
        ids: list[int] = []
        for it in self.tree.selectedItems():
            kind, val = it.data(0, Qt.UserRole)
            if kind == "prj" and val not in ids:
                ids.append(val)
            elif kind == "cat":
                for i in range(it.childCount()):
                    pid = it.child(i).data(0, Qt.UserRole)[1]
                    if pid not in ids:
                        ids.append(pid)
        return ids

    def select_quick(self):
        self.refresh(quick=True)
        self.opened.emit(None)

    # ---------- eventi ----------
    def _update_hint(self):
        ids = self.selected_ids()
        self.b_update.setEnabled(bool(ids))
        self.b_delete.setEnabled(bool(ids))
        if len(ids) > 1:
            self.hint.setText(tr("{n} progetti selezionati: «Aggiorna» li scarica uno dopo l'altro.", n=len(ids)))
        elif len(ids) == 1:
            p = self.store.get(ids[0])
            self.hint.setText(when(p.last_run) if p else "")
        else:
            self.hint.setText("")

    def _on_selection(self):
        if self._muting:
            return
        self._update_hint()
        items = self.tree.selectedItems()
        if len(items) != 1:
            return
        kind, val = items[0].data(0, Qt.UserRole)
        if kind == "quick":
            self.opened.emit(None)
        elif kind == "prj":
            self.opened.emit(self.store.get(val))

    def _context_menu(self, pos):
        ids = self.selected_ids()
        if not ids:
            return
        m = QMenu(self)
        pr = m.addMenu(tr("Priorità nella coda"))
        for val, text in ((2, "Alta"), (1, "Normale"), (0, "Bassa")):
            a = pr.addAction(tr(text))
            a.triggered.connect(lambda _=False, v=val: self._set_all(ids, "priority", v))
        wt = m.addMenu(tr("Controlla da solo"))
        for val, text in ((0, "Mai"), (1, "Ogni ora"), (6, "Ogni 6 ore"), (12, "Ogni 12 ore"), (24, "Ogni giorno")):
            a = wt.addAction(tr(text))
            a.triggered.connect(lambda _=False, v=val: self._set_all(ids, "watch", v))
        m.addSeparator()
        m.addAction(icon("refresh", self.colors["muted"], 14), tr("Aggiorna"), self._update_selected)
        m.addAction(icon("trash", self.colors["muted"], 14), tr("Elimina"), self._delete_selected)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _set_all(self, ids: list[int], what: str, val: int):
        for i in ids:
            (self.store.set_priority if what == "priority" else self.store.set_watch)(i, val)
        self.refresh(select_id=ids[0])

    def _update_selected(self):
        ids = self.selected_ids()
        if ids:
            self.update_requested.emit(ids)

    def _delete_selected(self):
        ids = self.selected_ids()
        if not ids:
            return
        names = [self.store.get(i).title for i in ids]
        msg = tr("Eliminare il progetto «{n}»?", n=names[0]) if len(ids) == 1 else \
            tr("Eliminare {n} progetti?", n=len(ids)) + "\n\n" + "\n".join("• " + n for n in names[:10])
        if QMessageBox.question(self, tr("Elimina progetto"),
                                msg + "\n\n" + tr("I file già scaricati restano sul disco.")) != QMessageBox.Yes:
            return
        for i in ids:
            self.store.delete(i)
        self.select_quick()
