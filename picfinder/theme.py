"""Colori, tema chiaro/scuro e foglio di stile (look da app Mac)."""

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


APP_NAME = "AllDownload"
# Colori neutri presi dalle app del Mac (Finder, Note): contenuto chiaro, barra laterale un filo più scura.
# Il colore principale NON è fisso: è quello scelto dall'utente in Impostazioni di Sistema → Aspetto.
SYSTEM_ACCENT: str | None = None          # letto in main() prima di setStyle("Fusion")
LIGHT = dict(bg="#FFFFFF", card="#FFFFFF", sidebar="#F2F2F4", border="#E5E5E8", strong="#D1D1D6",
             text="#1D1D1F", muted="#6E6E73", faint="#A1A1A6", input="#FFFFFF", alt="#F7F7F9",
             hover="#EDEDF0", control="#FFFFFF", tip_bg="#2C2C2E", tip_text="#FFFFFF")
DARK = dict(bg="#1E1E1F", card="#1E1E1F", sidebar="#262628", border="#333336", strong="#48484B",
            text="#F2F2F7", muted="#98989F", faint="#636368", input="#2A2A2C", alt="#222224",
            hover="#2E2E31", control="#3A3A3C", tip_bg="#E9E9EE", tip_text="#1D1D1F")


def _mix(a: QColor, b: QColor, t: float) -> str:
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def palette_for(dark: bool) -> dict:
    """Neutri + colore principale del sistema, con le sue varianti (premuto, selezione, testo)."""
    c = dict(DARK if dark else LIGHT)
    acc = QColor(SYSTEM_ACCENT or ("#0A84FF" if dark else "#007AFF"))
    if acc.saturationF() < 0.15:                  # accento «grafite»: resta grigio, ma leggibile
        acc = QColor("#8E8E93")
    bg, black, white = QColor(c["card"]), QColor("#000000"), QColor("#FFFFFF")
    c["accent"] = acc.name()
    c["accent_hover"] = _mix(acc, white if dark else black, 0.10)
    c["accent_press"] = _mix(acc, black, 0.22)
    c["accent_text"] = _mix(acc, white, 0.25) if dark else _mix(acc, black, 0.12)
    c["select"] = _mix(bg, acc, 0.28 if dark else 0.16)      # riga scelta, finestra non attiva
    c["select_strong"] = acc.name()                          # riga scelta, finestra attiva
    return c


ACCENT = "#007AFF"
OK, WARN, ERR = "#16A34A", "#D97706", "#DC2626"
STATUS_COLORS = {"ok": OK, "warn": WARN, "err": ERR}
glog = logging.getLogger("picfinder.gui")


def with_play_badge(pix: QPixmap) -> QPixmap:
    """Disegna il simbolo ▶ al centro (per le anteprime dei video)."""
    out = QPixmap(pix)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    r = max(14, min(out.width(), out.height()) // 6)
    cx, cy = out.width() // 2, out.height() // 2
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 150))
    p.drawEllipse(cx - r, cy - r, 2 * r, 2 * r)
    p.setBrush(QColor(255, 255, 255, 235))
    p.drawPolygon(QPolygon([QPoint(cx - r // 3, cy - r // 2), QPoint(cx - r // 3, cy + r // 2),
                            QPoint(cx + r // 2, cy)]))
    p.end()
    return out


def is_dark() -> bool:
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorScheme"):
        return hints.colorScheme() == Qt.ColorScheme.Dark
    return QGuiApplication.palette().color(QPalette.Window).lightness() < 128


def stylesheet(c: dict) -> str:
    """Stile «da Mac»: niente schede flottanti su sfondo grigio, niente etichette MAIUSCOLE,
    angoli 6 px come i controlli di macOS, linee sottili al posto dei bordi, colore di sistema."""
    from .icons import icon_file
    down = icon_file("chevron-down", c["muted"])
    up = icon_file("chevron-up", c["muted"])
    closed = icon_file("chevron-right", c["faint"])
    check = icon_file("check", "#FFFFFF")
    return f"""
    QMainWindow, QWidget#root, QDialog {{ background: {c['bg']}; }}
    QWidget {{ color: {c['text']}; font-size: 13px; }}
    QFrame#card {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 10px; }}
    QFrame#plain {{ background: {c['bg']}; border: none; }}
    QFrame#listbox {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 8px; }}
    QFrame#sidebar {{ background: {c['sidebar']}; border: none; border-right: 1px solid {c['border']}; }}
    QFrame#sidebar QTreeWidget, QFrame#sidebar QFrame#card {{ background: transparent; border: none; }}
    QFrame#preview {{ background: {c['bg']}; border: none; border-left: 1px solid {c['border']}; }}
    QFrame#sep {{ background: {c['border']}; max-height: 1px; min-height: 1px; border: none; }}
    QFrame#vsep {{ background: {c['border']}; max-width: 1px; min-width: 1px; border: none; }}
    QWidget#toast {{ background: {c['tip_bg']}; border-radius: 17px; }}
    QLabel#toastText {{ color: {c['tip_text']}; font-size: 13px; font-weight: 500; background: transparent; }}

    QLabel#appname {{ font-size: 13px; font-weight: 600; }}
    QLabel#version {{ color: {c['faint']}; font-size: 11px; }}
    QLabel#title {{ font-size: 20px; font-weight: 700; letter-spacing: -0.4px; }}
    QLabel#subtitle, QLabel#muted {{ color: {c['muted']}; }}
    QLabel#faint {{ color: {c['faint']}; font-size: 12px; }}
    QLabel#section {{ font-size: 11px; font-weight: 600; color: {c['faint']}; letter-spacing: 0.2px; }}
    QLabel#field {{ color: {c['muted']}; font-size: 13px; }}
    QLabel#heading {{ font-size: 15px; font-weight: 600; letter-spacing: -0.2px; }}
    QLabel#detected {{ font-size: 12px; color: {c['muted']}; }}
    QLabel#pvName {{ font-weight: 600; font-size: 13px; }}
    QLabel#pvImage {{ color: {c['faint']}; }}
    QLabel#emptyTitle {{ font-size: 17px; font-weight: 600; letter-spacing: -0.3px; }}
    QLabel#emptyText {{ color: {c['muted']}; line-height: 140%; }}
    QLabel#stat {{ color: {c['muted']}; font-size: 12px; }}
    QLabel#banner {{ background: {c['alt']}; color: {c['text']}; border: 1px solid {c['border']};
                     border-radius: 8px; padding: 9px 12px; }}

    QToolTip {{ background: {c['tip_bg']}; color: {c['tip_text']}; border: none; padding: 5px 8px;
                border-radius: 6px; font-size: 12px; }}

    QLineEdit, QComboBox, QSpinBox {{ background: {c['input']}; border: 1px solid {c['strong']};
                border-radius: 6px; padding: 4px 8px; min-height: 18px;
                selection-background-color: {c['accent']}; selection-color: white; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {c['faint']}; background: {c['alt']}; }}
    QLineEdit#filter {{ background: {c['alt']}; border: 1px solid transparent; border-radius: 7px; padding: 4px 8px; }}
    QLineEdit#filter:focus {{ background: {c['input']}; border: 1px solid {c['accent']}; }}
    QPlainTextEdit#big {{ background: {c['input']}; border: 1px solid {c['strong']}; border-radius: 8px;
                          padding: 6px 8px; font-size: 13px; }}
    QTextBrowser {{ background: {c['alt']}; color: {c['text']}; border: 1px solid {c['border']};
                    border-radius: 8px; padding: 8px 10px; }}
    QPlainTextEdit#big:focus {{ border: 1px solid {c['accent']}; }}

    QComboBox {{ padding-right: 26px; }}
    QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 24px;
                            border: none; background: transparent; }}
    QComboBox::down-arrow {{ image: url({down}); width: 11px; height: 11px; }}
    QComboBox QAbstractItemView {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 8px;
                                   padding: 4px; outline: 0; selection-background-color: {c['accent']};
                                   selection-color: white; }}
    QSpinBox {{ padding-right: 22px; }}
    QSpinBox::up-button, QSpinBox::down-button {{ subcontrol-origin: border; width: 20px; border: none;
                                                  background: transparent; }}
    QSpinBox::up-button {{ subcontrol-position: top right; margin-top: 2px; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; margin-bottom: 2px; }}
    QSpinBox::up-arrow {{ image: url({up}); width: 9px; height: 9px; }}
    QSpinBox::down-arrow {{ image: url({down}); width: 9px; height: 9px; }}

    QPushButton {{ background: {c['control']}; border: 1px solid {c['strong']}; border-radius: 6px;
                   padding: 4px 12px; min-height: 18px; }}
    QPushButton:hover {{ background: {c['hover']}; }}
    QPushButton:pressed {{ background: {c['border']}; }}
    QPushButton:disabled {{ color: {c['faint']}; border-color: {c['border']}; background: transparent; }}
    QPushButton:focus {{ outline: none; }}
    QPushButton#primary {{ background: {c['accent']}; color: white; border: 1px solid {c['accent']};
                           font-weight: 500; padding: 4px 16px; }}
    QPushButton#primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
    QPushButton#primary:pressed {{ background: {c['accent_press']}; border-color: {c['accent_press']}; }}
    QPushButton#primary:disabled {{ background: {c['alt']}; border-color: {c['border']}; color: {c['faint']}; }}
    QPushButton#danger {{ background: {c['control']}; color: {ERR}; border: 1px solid {c['strong']}; font-weight: 500; }}
    QPushButton#danger:hover {{ background: {c['hover']}; }}
    QPushButton#danger:pressed {{ background: {c['border']}; }}
    QPushButton#ghost, QPushButton#iconbtn {{ background: transparent; border: 1px solid transparent; color: {c['muted']}; }}
    QPushButton#ghost:hover, QPushButton#iconbtn:hover {{ background: {c['hover']}; color: {c['text']}; }}
    QPushButton#ghost:pressed, QPushButton#iconbtn:pressed {{ background: {c['border']}; }}
    QPushButton#ghost:checked {{ background: {c['hover']}; color: {c['text']}; }}
    QPushButton#iconbtn {{ padding: 4px; min-width: 18px; }}
    QPushButton#link {{ border: none; background: transparent; color: {c['accent_text']}; padding: 2px 4px; }}
    QPushButton#link:hover {{ text-decoration: underline; }}
    QPushButton#link:pressed {{ color: {c['accent_press']}; }}
    QPushButton#chip, QPushButton#small {{ background: {c['control']}; border: 1px solid {c['strong']};
                        border-radius: 6px; padding: 2px 10px; min-height: 16px; font-size: 12px; }}
    QPushButton#chip:hover, QPushButton#small:hover {{ background: {c['hover']}; }}
    QPushButton#chip:pressed, QPushButton#small:pressed {{ background: {c['border']}; }}
    QPushButton#chip:disabled {{ color: {c['faint']}; }}
    QPushButton#badge {{ background: transparent; color: {c['accent_text']}; border: none; border-radius: 6px;
                         padding: 2px 6px; min-height: 16px; font-size: 12px; font-weight: 500; }}
    QPushButton#badge:hover {{ background: {c['hover']}; }}
    QPushButton#seg {{ background: {c['control']}; border: 1px solid {c['strong']}; border-radius: 0;
                       border-left: none; padding: 2px 11px; min-height: 16px; font-size: 12px; }}
    QPushButton#segFirst {{ background: {c['control']}; border: 1px solid {c['strong']};
                       border-top-left-radius: 6px; border-bottom-left-radius: 6px;
                       border-top-right-radius: 0; border-bottom-right-radius: 0;
                       padding: 2px 11px; min-height: 16px; font-size: 12px; }}
    QPushButton#segLast {{ background: {c['control']}; border: 1px solid {c['strong']}; border-left: none;
                       border-top-right-radius: 6px; border-bottom-right-radius: 6px;
                       border-top-left-radius: 0; border-bottom-left-radius: 0;
                       padding: 2px 11px; min-height: 16px; font-size: 12px; }}
    QPushButton#seg:hover, QPushButton#segFirst:hover, QPushButton#segLast:hover {{ background: {c['hover']}; }}
    QPushButton#seg:pressed, QPushButton#segFirst:pressed, QPushButton#segLast:pressed {{ background: {c['border']}; }}
    QPushButton#seg:disabled, QPushButton#segFirst:disabled, QPushButton#segLast:disabled {{ color: {c['faint']}; background: transparent; }}
    QPushButton#side {{ background: transparent; border: none; border-radius: 6px; padding: 5px 8px;
                        text-align: left; color: {c['text']}; }}
    QPushButton#side:hover {{ background: {c['hover']}; }}
    QPushButton#side:pressed {{ background: {c['border']}; }}
    QFrame#flat {{ background: transparent; border: none; }}

    QCheckBox {{ color: {c['text']}; spacing: 7px; }}
    QCheckBox:disabled {{ color: {c['faint']}; }}
    QCheckBox::indicator, QTreeView::indicator, QTableView::indicator {{ width: 14px; height: 14px;
        border: 1px solid {c['strong']}; border-radius: 4px; background: {c['input']}; }}
    QCheckBox::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked {{
        background: {c['accent']}; border-color: {c['accent']}; image: url({check}); }}

    QProgressBar {{ background: {c['border']}; border: none; border-radius: 1px; max-height: 3px; min-height: 3px; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 1px; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar {{ qproperty-drawBase: 0; }}
    QTabBar::tab {{ background: {c['control']}; color: {c['text']}; padding: 3px 16px; min-height: 16px;
                    border: 1px solid {c['strong']}; border-left: none; font-size: 12px; }}
    QTabBar::tab:first {{ border-left: 1px solid {c['strong']}; border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
    QTabBar::tab:last {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
    QTabBar::tab:hover {{ background: {c['hover']}; }}
    QTabBar::tab:selected {{ background: {c['accent']}; border-color: {c['accent']}; color: white; }}

    QTreeWidget, QTableWidget, QListWidget {{ background: {c['card']}; border: none; outline: 0;
                                              alternate-background-color: {c['alt']}; }}
    QTreeWidget::item, QTableWidget::item {{ padding: 3px 2px; border: none; }}
    QTreeWidget::item:selected:active, QTableWidget::item:selected:active, QListWidget::item:selected:active {{
        background: {c['select_strong']}; color: white; }}
    QTreeWidget::item:selected:!active, QTableWidget::item:selected:!active, QListWidget::item:selected:!active {{
        background: {c['select']}; color: {c['text']}; }}
    QFrame#sidebar QTreeWidget::item {{ padding: 4px 2px; border-radius: 6px; }}
    QFrame#sidebar QTreeWidget::item:hover {{ background: {c['hover']}; }}
    QFrame#sidebar QTreeWidget {{ show-decoration-selected: 0; }}
    QFrame#sidebar QTreeWidget::item:selected {{ background: {c['select']}; color: {c['text']}; }}
    QFrame#sidebar QTreeWidget::branch, QFrame#sidebar QTreeWidget::branch:selected,
    QFrame#sidebar QTreeWidget::branch:hover {{ background: {c['sidebar']}; }}
    QFrame#sidebar QTreeWidget::branch:has-children:closed {{ image: url({closed}); }}
    QFrame#sidebar QTreeWidget::branch:has-children:open {{ image: url({down}); }}
    QHeaderView {{ background: {c['card']}; border: none; }}
    QHeaderView::section {{ background: {c['card']}; color: {c['muted']}; border: none;
                            border-bottom: 1px solid {c['border']}; border-right: 1px solid {c['border']};
                            padding: 4px 8px; font-size: 12px; font-weight: 500; }}
    QHeaderView::section:last {{ border-right: none; }}
    QPlainTextEdit#log {{ background: {c['card']}; border: none; font-family: Menlo, Consolas, "DejaVu Sans Mono", monospace;
                          font-size: 11px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle {{ background: {c['strong']}; border-radius: 3px; min-height: 28px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {c['faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QMenuBar {{ background: {c['bg']}; }}
    QMenu {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 4px 22px 4px 10px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {c['accent']}; color: white; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 4px 6px; }}

    QSplitter::handle {{ background: {c['border']}; }}
    QStatusBar {{ background: {c['bg']}; color: {c['muted']}; font-size: 11px; border-top: 1px solid {c['border']}; }}
    QStatusBar::item {{ border: none; }}
    """


def human_size(n: float | None) -> str:
    if not n:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def card(name: str = "card") -> QFrame:
    f = QFrame()
    f.setObjectName(name)
    return f


def label(text: str, name: str | None = None) -> QLabel:
    lb = QLabel(text)
    if name:
        lb.setObjectName(name)
    return lb


def small_button(text: str, slot) -> QPushButton:
    b = QPushButton(text, objectName="small")
    b.clicked.connect(slot)
    return b


# ---------------------------------------------------------------- lavoro in background
