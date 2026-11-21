"""Finestra "Template": servizio, tipo, compatibilità, attivo sì/no."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from . import plugins
from .i18n import tr

OK, WARN, ERR = "#16A34A", "#D97706", "#DC2626"


def _label(text: str, name: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(name)
    return lb


class TemplatesDialog(QDialog):
    changed = Signal()
    reloaded = Signal()
    COL_ON, COL_SERVICE, COL_KIND, COL_STATE, COL_ORIGIN = range(5)
    ORIGINS = {"inclusi": "Incluso nell'app", "tuoi": "Aggiunto da te", "python": "Plugin Python"}

    def __init__(self, parent, colors: dict):
        super().__init__(parent)
        self.setWindowTitle("Template")
        self.resize(820, 540)
        self.colors = colors
        self.main = parent
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)

        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label("Template", "title"))
        self.summary = _label("", "subtitle")
        col.addWidget(self.summary)
        lay.addLayout(col)

        box = QFrame()
        box.setObjectName("card")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 8, 12, 8)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Attivo", "Servizio", "Tipo", "Compatibilità", "Origine"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.setStyleSheet("QTreeWidget { outline: 0; }")
        h = self.tree.header()
        h.setSectionResizeMode(self.COL_ON, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(self.COL_SERVICE, QHeaderView.Stretch)
        for c in (self.COL_KIND, self.COL_STATE, self.COL_ORIGIN):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self.on_toggle)
        self.tree.currentItemChanged.connect(self.show_details)
        bl.addWidget(self.tree)
        lay.addWidget(box, 1)

        self.details = QLabel()
        self.details.setObjectName("muted")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details.setMinimumHeight(80)
        self.details.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self.details)

        buttons = QHBoxLayout()
        add = QPushButton("Aggiungi template…")
        add.clicked.connect(self.add_templates)
        open_dir = QPushButton("Apri cartella")
        open_dir.clicked.connect(self.main.open_templates)
        reload_btn = QPushButton("Ricarica")
        reload_btn.clicked.connect(self.reload)
        close = QPushButton("Chiudi", objectName="primary")
        close.clicked.connect(self.accept)
        for b in (add, open_dir, reload_btn):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(close)
        lay.addLayout(buttons)
        self.fill()

    @staticmethod
    def state(entry: dict) -> tuple[str, str]:
        issues = [(lvl, t) for lvl, t in entry["issues"] if lvl != "info"]
        if any(lvl == "hard" for lvl, _ in issues):
            return "✗ " + tr("Parziale"), ERR
        if entry.get("tested"):
            y, _, m = entry["tested"].partition("-")
            return "✓ " + tr("Supportato, provato {d}", d=f"{m}/{y}" if m else y), OK
        if issues:
            return "◐ " + tr("Da provare"), WARN
        return "✓ " + tr("Compatibile"), OK

    def fill(self, keep_key: str | None = None):
        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        entries = plugins.entries()
        current = None
        for e in entries:
            state, color = self.state(e)
            kind = " ".join(tr(w) for w in (e["kind"] or "—").split(" ")) if e["kind"] != "link condiviso" \
                else tr(e["kind"])
            if e["kind"].startswith("plugin Python"):
                kind = tr(e["kind"])
            it = QTreeWidgetItem(["", e["service"], kind, state,
                                  tr(self.ORIGINS.get(e["origin"], e["origin"]))])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(self.COL_ON, Qt.Checked if e["enabled"] else Qt.Unchecked)
            it.setForeground(self.COL_STATE, QColor(color))
            it.setData(self.COL_ON, Qt.UserRole, e)
            it.setToolTip(self.COL_SERVICE, e["title"])
            if not e["enabled"]:
                for c in (self.COL_SERVICE, self.COL_KIND, self.COL_ORIGIN):
                    it.setForeground(c, QColor(self.colors["muted"]))
            self.tree.addTopLevelItem(it)
            if e["key"] == keep_key:
                current = it
        self.tree.setSortingEnabled(True)
        self.tree.sortItems(self.COL_SERVICE, Qt.AscendingOrder)
        self.tree.blockSignals(False)
        on = sum(e["enabled"] for e in entries)
        self.summary.setText(tr("{a} attivi su {b}. Togli la spunta per disattivare un template.", a=on, b=len(entries)))
        self.tree.setCurrentItem(current or self.tree.topLevelItem(0))

    def show_details(self, item, _prev=None):
        if not item:
            self.details.setText("")
            return
        e = item.data(self.COL_ON, Qt.UserRole)
        lines = [f"<b>{e['title']}</b> &nbsp;·&nbsp; {Path(e['path']).name}"]
        if e["patterns"]:
            lines.append(tr("Riconosce gli indirizzi:") + " " + ", ".join(f"<code>{p}</code>" for p in e["patterns"][:4]))
        if e["issues"]:
            lines += [{"hard": "✗ ", "soft": "◐ "}.get(lvl, "ⓘ ") + tr(t) for lvl, t in e["issues"]]
        else:
            lines.append("✓ " + tr("Tutto quello che usa questo template è supportato."))
        self.details.setText("<br>".join(lines))

    def on_toggle(self, item, column):
        if column != self.COL_ON:
            return
        e = item.data(self.COL_ON, Qt.UserRole)
        plugins.set_enabled(e["key"], item.checkState(self.COL_ON) == Qt.Checked)
        self.fill(keep_key=e["key"])
        self.changed.emit()

    def add_templates(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr("Aggiungi template"), str(Path.home()),
                                                "EPF (*.etmpl)")
        if not files:
            return
        dst = plugins.user_templates_dir()
        dst.mkdir(parents=True, exist_ok=True)
        for f in files:
            (dst / Path(f).name).write_bytes(Path(f).read_bytes())
        self.reload()

    def reload(self):
        plugins.reload()
        self.fill()
        self.reloaded.emit()
