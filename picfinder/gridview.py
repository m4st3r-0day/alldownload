"""Vista a griglia delle anteprime e «anteprima veloce» con la barra spaziatrice (come il Finder)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QLabel, QListView, QListWidget, QListWidgetItem,
                               QVBoxLayout)

from .i18n import tr

ROLE_URL = Qt.UserRole


class GridView(QListWidget):
    """Griglia di miniature, una casella per file. Le spunte vanno d'accordo con la lista."""
    checked_changed = Signal(str, bool)
    current_url = Signal(str)
    activated_url = Signal(str)

    def __init__(self, colors: dict):
        super().__init__()
        self.setObjectName("grid")
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(160, 120))
        self.setGridSize(QSize(190, 158))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setTextElideMode(Qt.ElideMiddle)
        self._items: dict[str, QListWidgetItem] = {}
        self._placeholder = self._make_placeholder(colors)
        self.itemChanged.connect(self._on_changed)
        self.currentItemChanged.connect(lambda it, _p: it and self.current_url.emit(it.data(ROLE_URL)))
        self.itemDoubleClicked.connect(lambda it: self.activated_url.emit(it.data(ROLE_URL)))

    @staticmethod
    def _make_placeholder(colors: dict) -> QIcon:
        pm = QPixmap(160, 120)
        pm.fill(Qt.transparent)
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(colors.get("alt", "#F2F2F4")))
        p.drawRoundedRect(2, 2, 156, 116, 8, 8)
        p.end()
        return QIcon(pm)

    def add(self, url: str, name: str, checked: bool):
        if url in self._items:
            return
        it = QListWidgetItem(self._placeholder, name)
        it.setData(ROLE_URL, url)
        it.setToolTip(name)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        self.blockSignals(True)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.blockSignals(False)
        self.addItem(it)
        self._items[url] = it

    def set_checked(self, url: str, checked: bool):
        it = self._items.get(url)
        if it is not None and (it.checkState() == Qt.Checked) != checked:
            self.blockSignals(True)
            it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
            self.blockSignals(False)

    def set_pixmap(self, url: str, pix: QPixmap):
        it = self._items.get(url)
        if it is not None and not pix.isNull():
            it.setIcon(QIcon(pix.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    def set_hidden(self, url: str, hidden: bool):
        it = self._items.get(url)
        if it is not None:
            it.setHidden(hidden)

    def select_url(self, url: str):
        it = self._items.get(url)
        if it is not None and self.currentItem() is not it:
            self.blockSignals(True)
            self.setCurrentItem(it)
            self.blockSignals(False)
            self.scrollToItem(it)

    def urls(self) -> list[str]:
        return list(self._items)

    def clear_all(self):
        self.clear()
        self._items.clear()

    def _on_changed(self, it: QListWidgetItem):
        self.checked_changed.emit(it.data(ROLE_URL), it.checkState() == Qt.Checked)


class QuickLook(QDialog):
    """Anteprima grande. Spazio o Esc chiude, frecce = file prima/dopo."""

    def __init__(self, parent, entries: list[tuple[str, str, QPixmap | None]], index: int):
        super().__init__(parent)
        self.entries, self.index = entries, index
        self.setWindowTitle(tr("Anteprima"))
        self.setStyleSheet("QDialog{background:#111214;} QLabel{color:#E5E5EA;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 14)
        self.title = QLabel(alignment=Qt.AlignCenter)
        self.image = QLabel(alignment=Qt.AlignCenter)
        self.image.setMinimumSize(320, 240)
        lay.addWidget(self.title)
        lay.addWidget(self.image, 1)
        scr = parent.screen().availableGeometry() if parent is not None and parent.screen() else None
        self.resize(int(scr.width() * 0.7), int(scr.height() * 0.75)) if scr else self.resize(1000, 720)
        for key, step in ((Qt.Key_Right, 1), (Qt.Key_Down, 1), (Qt.Key_Left, -1), (Qt.Key_Up, -1)):
            QShortcut(QKeySequence(key), self, activated=lambda s=step: self.move_by(s))
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.accept)
        self.show_current()

    def move_by(self, step: int):
        if self.entries:
            self.index = (self.index + step) % len(self.entries)
            self.show_current()

    def show_current(self):
        name, _url, pix = self.entries[self.index]
        self.title.setText(f"{name}   ·   {self.index + 1}/{len(self.entries)}")
        if pix is None or pix.isNull():
            self.image.setPixmap(QPixmap())
            self.image.setText(tr("Anteprima non ancora pronta"))
        else:
            self.image.setText("")
            self.image.setPixmap(pix.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.entries:
            self.show_current()


def system_quick_look(path: str) -> bool:
    """Mac: il vero «Quick Look» di sistema per un file già scaricato."""
    if sys.platform != "darwin" or not path or not Path(path).exists():
        return False
    try:
        subprocess.Popen(["qlmanage", "-p", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False
