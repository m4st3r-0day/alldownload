"""Pezzi della finestra principale: lista con stato, anteprima, campo link, schermata vuota, worker."""

import asyncio
import logging
import os
import re
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QEvent, QObject, QPoint, QRunnable, QSettings, QSize, Qt, QThread, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QGuiApplication, QIcon, QKeySequence, QPainter, QPalette,
                           QPixmap, QPolygon, QShortcut)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QMessageBox,
    QSystemTrayIcon,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QPlainTextEdit,
    QProgressBar, QPushButton, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QStyle, QStyledItemDelegate,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__, plugins
from .core import DEFAULT_PATTERNS, Downloader, FfmpegMissing, PluginError, RemoteFile, file_key, kind_of
from .etmpl import EtmplPlugin
from .proxies import ProxyPool, mask
from .settings import Settings, PAUSE_SCALE
from .settings_dialog import SettingsDialog
from .logs import log_dir, setup_file_logging
from .projects import History, Project, Store
from .projects_panel import ProjectsPanel
from .templates_dialog import TemplatesDialog
from .netpolicy import Schedule, expired
from .i18n import set_language, tr, translate_tree
from .icons import app_icon, icon
from . import motion

from .theme import *  # noqa: F401,F403
from .theme import ACCENT, STATUS_COLORS, card, human_size, label, small_button, with_play_badge


class Worker(QObject):
    """Esegue una coroutine del Downloader in un thread separato."""
    event = Signal(str, dict)
    result = Signal(object)
    error = Signal(str)
    finished = Signal()

    def __init__(self, make_coro):
        super().__init__()
        self.make_coro = make_coro

    def run(self):
        try:
            self.result.emit(asyncio.run(self.make_coro()))
        except PluginError as e:
            self.error.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.error.emit(f"Errore imprevisto: {e}")
        self.finished.emit()


class LogBridge(QObject):
    record = Signal(int, str)


class QtLogHandler(logging.Handler):
    """Manda i messaggi del registro alla finestra (anche dai thread di download)."""
    MARK = {logging.DEBUG: "·", logging.INFO: " ", logging.WARNING: "⚠", logging.ERROR: "✗"}

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.bridge = LogBridge()

    def emit(self, record):
        try:
            line = f"{time.strftime('%H:%M:%S', time.localtime(record.created))} " \
                   f"{self.MARK.get(record.levelno, ' ')} {record.getMessage()}"
            self.bridge.record.emit(record.levelno, line)
        except Exception:  # noqa: BLE001
            pass


class PreviewSignals(QObject):
    loaded = Signal(str, bytes, str, str)   # url, dati, errore, fonte


class PreviewTask(QRunnable):
    def __init__(self, dl: Downloader, f: RemoteFile, signals: PreviewSignals, local: str | None = None):
        super().__init__()
        self.dl, self.f, self.signals, self.local = dl, f, signals, local

    def run(self):
        try:
            data, source = self.dl.preview_bytes(self.f, self.local)
            self.signals.loaded.emit(self.f.url, data, "", source)
        except FfmpegMissing as e:
            self.signals.loaded.emit(self.f.url, b"", str(e), "")
        except Exception as e:  # noqa: BLE001
            logging.getLogger("picfinder").debug("anteprima non riuscita per %s: %s", self.f.name, e)
            self.signals.loaded.emit(self.f.url, b"", str(e) or e.__class__.__name__, "")


class Stat(QLabel):
    """Numero piccolo con etichetta: «14 trovati». Colore solo sul numero."""

    def __init__(self, title: str, color: str | None = None, muted: str = "#667085", hide_zero: bool = False):
        super().__init__()
        self.setObjectName("stat")
        self.title, self.color, self.muted, self.hide_zero = title, color, muted, hide_zero
        self.set(0)

    def set(self, n: int):
        if self.hide_zero:
            self.setVisible(bool(n))
        col = self.color if (self.color and n) else None
        num = f"<span style='font-weight:600;{f' color:{col};' if col else ''}'>{n}</span>"
        self.setText(f"{num}&nbsp;{tr(self.title)}")


class StatusDelegate(QStyledItemDelegate):
    """Colonna Stato come nel Finder: un pallino colorato e il testo normale (niente «pillole»)."""

    def __init__(self, parent, colors: dict):
        super().__init__(parent)
        self.colors = colors

    def paint(self, painter, option, index):
        text = index.data(Qt.DisplayRole) or ""
        tone = index.data(Qt.UserRole + 1) or ""
        self.initStyleOption(option, index)
        option.text = ""
        st = option.widget.style() if option.widget else QApplication.style()
        st.drawControl(QStyle.CE_ItemViewItem, option, painter, option.widget)
        if not text:
            return
        selected = bool(option.state & QStyle.State_Selected) and bool(option.state & QStyle.State_Active)
        tones = dict(STATUS_COLORS, run=self.colors["accent"])
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        r = option.rect
        x = r.x() + 8
        if tone:
            d = 7
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#FFFFFF") if selected else QColor(tones.get(tone, self.colors["muted"])))
            painter.drawEllipse(x, r.y() + (r.height() - d) // 2, d, d)
            x += d + 7
        painter.setPen(QColor("#FFFFFF") if selected else
                       QColor(self.colors["text"] if tone else self.colors["muted"]))
        painter.drawText(x, r.y(), r.right() - x, r.height(), Qt.AlignVCenter | Qt.AlignLeft,
                         option.fontMetrics.elidedText(text, Qt.ElideRight, r.right() - x))
        painter.restore()


# ---------------------------------------------------------------- campo link (uno o più)
class LinksEdit(QPlainTextEdit):
    submit = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("big")
        self.setPlaceholderText("Incolla uno o più link, uno per riga")
        self.setTabChangesFocus(True)
        self.setFixedHeight(72)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.submit.emit()
            return
        super().keyPressEvent(e)

    def links(self) -> list[str]:
        out = []
        for line in self.toPlainText().splitlines():
            line = line.strip()
            if line and line not in out:
                out.append(line)
        return out

    def text(self) -> str:
        return self.toPlainText()

    def setText(self, text: str):
        self.setPlainText(text)

    def add_link(self, link: str):
        for line in link.splitlines():
            line = line.strip()
            if not line or line in self.links():
                continue
            cur = self.toPlainText().rstrip()
            self.setPlainText(f"{cur}\n{line}" if cur else line)


# ---------------------------------------------------------------- lista vuota
class EmptyState(QWidget):
    @staticmethod
    def help_text() -> str:
        mod = "⌘" if sys.platform == "darwin" else "Ctrl+"
        return (tr("Poi premi Invio o «Cerca file». Puoi anche trascinare un link nella finestra.")
                + f"\n{mod}V " + tr("incolla") + f" · {mod}B " + tr("browser interno")
                + f" · {mod}, " + tr("impostazioni"))

    def retranslate(self):
        self.text.setText(self.help_text())

    def __init__(self, colors: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.addStretch(2)
        ic = QLabel(alignment=Qt.AlignCenter)
        ic.setPixmap(icon("image", colors["faint"], 44).pixmap(44, 44))
        lay.addWidget(ic)
        lay.addSpacing(8)
        self.title = label("Incolla un link per iniziare", "emptyTitle")
        self.title.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.title)
        self.text = label(self.help_text(), "emptyText")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        lay.addWidget(self.text)
        lay.addStretch(3)


# ---------------------------------------------------------------- pannello anteprima
class PreviewPanel(QFrame):
    open_url = Signal(str)

    def __init__(self, colors: dict):
        super().__init__()
        self.setObjectName("preview")
        self.setMinimumWidth(240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(6)
        self.image = QLabel(alignment=Qt.AlignCenter, objectName="pvImage")
        self.image.setMinimumHeight(140)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image.setWordWrap(True)
        self.name = label("", "pvName")
        self.name.setWordWrap(True)
        self.info = label("", "muted")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.browser = QPushButton(icon("external", colors["muted"]), " Apri nel browser", objectName="ghost")
        self.browser.setCursor(Qt.PointingHandCursor)
        self.browser.clicked.connect(lambda: self.open_url.emit(self.url))
        lay.addWidget(self.image, 1)
        sep = QFrame(objectName="sep")
        lay.addWidget(sep)
        lay.addSpacing(4)
        for w in (self.name, self.info):
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            lay.addWidget(w)
        lay.addWidget(self.browser, 0, Qt.AlignLeft)
        self.url = ""
        self._pix: QPixmap | None = None
        self.clear()

    def clear(self):
        self.url = ""
        self._pix = None
        self.image.setPixmap(QPixmap())
        self.image.setText(tr("Seleziona un file per vedere l'anteprima"))
        self.name.setText("")
        self.info.setText("")
        self.browser.hide()

    def show_file(self, f: RemoteFile, extra: str = ""):
        self.url = f.url
        self.name.setText(f.name)
        rows = [(tr("Cartella"), f.subdir or "/"), (tr("Dimensione"), human_size(f.size))]
        html = "".join(f"<tr><td style='padding-right:10px'>{k}</td><td>{v}</td></tr>" for k, v in rows)
        self.info.setText(f"<table>{html}</table>" + (f"<div style='margin-top:4px'>{extra}</div>" if extra else ""))
        self.browser.show()

    def set_message(self, text: str):
        self._pix = None
        self.image.setPixmap(QPixmap())
        self.image.setText(text)

    def set_pixmap(self, pix: QPixmap):
        self._pix = pix
        self._fit()

    def _fit(self):
        if self._pix and not self._pix.isNull():
            self.image.setPixmap(self._pix.scaled(self.image.size() - QSize(4, 4),
                                                  Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()


# ---------------------------------------------------------------- finestra principale
