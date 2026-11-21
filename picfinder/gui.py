"""Interfaccia grafica di PicFinder (PySide6).

Flusso: [Cerca file] -> lista con caselle e anteprima -> [Scarica N selezionati].
Con "Scarica tutto subito" cerca e scarica in un colpo solo.
"""
from __future__ import annotations

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

from . import theme
from .theme import *  # noqa: F401,F403
from .widgets import *  # noqa: F401,F403


class MainWindow(QMainWindow):
    COL_NAME, COL_DIR, COL_SIZE, COL_STATUS = range(4)
    IDLE, SCANNING, REVIEW, DOWNLOADING = range(4)

    def __init__(self, transport=None, store: Store | None = None):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1320, 840)
        self.setMinimumSize(1000, 640)
        self.setAcceptDrops(True)
        self.transport = transport          # solo per i test
        self.settings = QSettings("PicFinder", "PicFinder")
        self.cfg = Settings.load()
        motion.set_user_reduce(self.cfg.reduce_motion)
        self.proxy_pool: ProxyPool | None = None
        self.log_lines: list[tuple[int, str]] = []
        from . import logs as _logs
        _logs.KEEP = self.cfg.keep_logs
        self.log_file = setup_file_logging()
        self.log_handler = QtLogHandler()
        self.log_handler.bridge.record.connect(self._append_log)
        logging.getLogger("picfinder").addHandler(self.log_handler)
        dark = self.cfg.theme == "dark" or (self.cfg.theme == "system" and is_dark())
        self.colors = palette_for(dark)
        self.setStyleSheet(stylesheet(self.colors))

        self.store = store or Store()
        self.history = History(self.store.path)
        self.project: Project | None = None
        self.queue: list[int] = []
        self.queue_total = 0
        self.queue_active = False

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        content = QFrame(objectName="plain")
        page = QVBoxLayout(content)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)
        page.addWidget(self._form())
        page.addWidget(QFrame(objectName="sep"))
        page.addWidget(self._results(), 1)
        self._stats()
        self.panel = ProjectsPanel(self.store, self.colors)
        self.panel.setObjectName("flat")
        self.panel.opened.connect(self.open_project)
        self.panel.update_requested.connect(self.update_projects)
        self.panel.new_requested.connect(self.new_project)
        body = QSplitter(Qt.Horizontal)
        body.setChildrenCollapsible(False)
        body.setHandleWidth(0)
        body.addWidget(self._sidebar())
        body.addWidget(content)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([230, 1000])
        outer.addWidget(body, 1)
        self._menus()
        self._status_widgets()
        from .menubar import MenuBarIcon
        self.menubar_icon = MenuBarIcon(self, dark)
        self.menubar_icon.open_window.connect(lambda: (self.showNormal(), self.raise_(), self.activateWindow()))
        self.menubar_icon.pause_toggled.connect(self.toggle_pause)
        self.menubar_icon.stop_requested.connect(
            lambda: self.primary_action() if self.state in (self.SCANNING, self.DOWNLOADING) else None)
        self.menubar_icon.open_folder.connect(self.open_destination)
        self.menubar_icon.quit_requested.connect(self.close)
        self.menubar_icon.show(self.cfg.show_menubar)

        self.statusBar().showMessage(tr("Pronto. Incolla un link o trascinalo nella finestra."))
        self.state = self.IDLE
        self.thread: QThread | None = None
        self._alive: set = set()
        self.worker: Worker | None = None
        self.dl: Downloader | None = None
        self.scanned_links: list[str] = []
        self.known: dict[str, str] = {}
        self.items: dict[str, QTreeWidgetItem] = {}
        self.files: dict[str, RemoteFile] = {}
        self.last_bytes: dict[str, int] = {}
        self.last_paint: dict[str, float] = {}
        self.bytes_window = 0
        self.speed_timer = QTimer(self, interval=1000, timeout=self._tick_speed)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)   # i siti rispondono 429 se chiedi troppe anteprime insieme
        self.pv_signals = PreviewSignals()
        self.pv_signals.loaded.connect(self.on_preview_loaded)
        self.pv_cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.pv_errors: dict[str, str] = {}
        self.pv_source: dict[str, str] = {}
        self.pv_pending: set[str] = set()
        self.reset_counters()
        self.reload_templates()
        self.set_state(self.IDLE)
        if not self.tree.topLevelItemCount():
            self._show_list(False)
        QTimer.singleShot(900, self._offer_pending)
        QTimer.singleShot(5000, lambda: self.check_updates(auto=True))
        self.watch_timer = QTimer(self)                 # 16: progetti osservati
        self.watch_timer.setInterval(max(1, self.cfg.watch_check_minutes) * 60_000)
        self.watch_timer.timeout.connect(self._check_watched)
        self.watch_timer.start()
        QTimer.singleShot(60_000, self._check_watched)
        translate_tree(self)
        from .i18n import language
        if language() == "en":
            self.tabs.setTabText(0, "Files")
        self.setWindowIcon(app_icon())

    # ---------- costruzione interfaccia ----------
    def _sidebar(self) -> QFrame:
        """Colonna a sinistra come le «source list» del Mac: progetti sopra, strumenti in fondo."""
        c = self.colors
        side = card("sidebar")
        side.setMinimumWidth(210)
        v = QVBoxLayout(side)
        v.setContentsMargins(10, 14, 10, 10)
        v.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(8)
        brand.setContentsMargins(6, 0, 0, 0)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(22, 22))
        brand.addWidget(logo)
        brand.addWidget(label(APP_NAME, "appname"))
        brand.addStretch()
        v.addLayout(brand)
        v.addSpacing(10)
        v.addWidget(self.panel, 1)
        v.addSpacing(4)
        self.tpl_badge = QPushButton(icon("layers", c["muted"], 16), "", objectName="side")
        self.tpl_badge.setCursor(Qt.PointingHandCursor)
        self.tpl_badge.clicked.connect(self.show_templates)
        self.net_badge = QPushButton(icon("network", c["muted"], 16), "", objectName="side")
        self.net_badge.setCursor(Qt.PointingHandCursor)
        self.net_badge.clicked.connect(lambda: self.show_settings(page=3))
        gear = QPushButton(icon("gear", c["muted"], 16), " Impostazioni", objectName="side")
        gear.setCursor(Qt.PointingHandCursor)
        gear.setToolTip("Impostazioni (Cmd+,)")
        gear.clicked.connect(self.show_settings)
        for b in (self.tpl_badge, self.net_badge, gear):
            v.addWidget(b)
        ver = label(f"v{__version__}", "version")
        ver.setContentsMargins(8, 4, 0, 0)
        v.addWidget(ver)
        return side

    def _form(self) -> QFrame:
        """Zona in alto: il campo dei link, sotto una riga di azioni (principale a destra, come su Mac)."""
        c = self.colors
        box = QFrame(objectName="plain")
        v = QVBoxLayout(box)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(10)

        self.url = LinksEdit()
        self.url.submit.connect(self.primary_action)
        self.url.textChanged.connect(self.on_url_changed)
        v.addWidget(self.url)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.detected = label("", "detected")
        self.detected.setWordWrap(True)
        row.addWidget(self.detected, 1)
        self.details_btn = QPushButton(icon("sliders", c["muted"], 15), " Opzioni", objectName="ghost")
        self.details_btn.setCheckable(True)
        self.details_btn.setChecked(True)
        self.details_btn.setToolTip("Progetto, password, cartella e opzioni")
        self.details_btn.clicked.connect(self.toggle_details)
        paste = QPushButton(icon("paste", c["muted"], 15), " Incolla")
        paste.setToolTip("Incolla dagli appunti (Cmd+V)")
        paste.clicked.connect(lambda: self.url.add_link(QGuiApplication.clipboard().text()))
        self.browser_btn = QPushButton(icon("globe", c["muted"], 15), " Browser")
        self.browser_btn.setToolTip("Apri il link nel browser interno: fai login o risolvi il controllo "
                                    "«sei umano?», poi premi «Continua»")
        self.browser_btn.clicked.connect(lambda: self.start_scan(force_browser=True))
        self.start = QPushButton("Cerca file", objectName="primary")
        self.start.clicked.connect(self.primary_action)
        self.start.setMinimumWidth(130)
        for b in (self.details_btn, paste, self.browser_btn, self.start):
            b.setFixedHeight(28)
            row.addWidget(b)
        v.addLayout(row)

        # dettagli: modulo come nelle Impostazioni del Mac (etichetta a destra, campo a sinistra)
        self.details = QWidget()
        d = QGridLayout(self.details)
        d.setContentsMargins(0, 6, 0, 0)
        d.setHorizontalSpacing(10)
        d.setVerticalSpacing(8)
        self.title_edit = QLineEdit(placeholderText="Nome, per salvarlo e aggiornarlo")
        self.category = QComboBox()
        self.category.setEditable(True)
        self.category.lineEdit().setPlaceholderText("Nessuna")
        self.save_btn = QPushButton("Salva progetto")
        self.save_btn.setToolTip("Salva link, cartella e opzioni per «Aggiorna» (Cmd/Ctrl+S)")
        self.save_btn.clicked.connect(self.save_project)
        self.password = QLineEdit(placeholderText="Solo se il link è protetto")
        self.password.setEchoMode(QLineEdit.Password)
        default_dest = str(Path.home() / "Downloads" / APP_NAME)
        self.dest = QLineEdit(self.settings.value("dest", "") or self.cfg.dest_dir or default_dest)
        self.dest.addAction(icon("folder", c["faint"], 15), QLineEdit.LeadingPosition)
        browse = QPushButton("Scegli…")
        browse.clicked.connect(self.choose_folder)

        def fld(t):
            lb = label(t, "field")
            lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            return lb
        d.addWidget(fld("Progetto"), 0, 0)
        d.addWidget(self.title_edit, 0, 1)
        d.addWidget(fld("Categoria"), 0, 2)
        d.addWidget(self.category, 0, 3)
        d.addWidget(self.save_btn, 0, 4)
        d.addWidget(fld("Salva in"), 1, 0)
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        dest_row.addWidget(self.dest, 1)
        dest_row.addWidget(browse)
        d.addLayout(dest_row, 1, 1)
        d.addWidget(fld("Password"), 1, 2)
        d.addWidget(self.password, 1, 3, 1, 2)
        d.setColumnStretch(1, 3)
        d.setColumnStretch(3, 2)
        self.direct = QCheckBox("Scarica tutto subito, senza scegliere")
        self.direct.setChecked(self.settings.value("direct", False, type=bool))
        self.direct.toggled.connect(lambda val: (self.settings.setValue("direct", val), self.set_state(self.state)))
        self.all_files = QCheckBox("Tutti i tipi di file (siti senza template)")
        opts = QHBoxLayout()
        opts.setSpacing(20)
        opts.addWidget(self.direct)
        opts.addWidget(self.all_files)
        opts.addStretch()
        d.addLayout(opts, 2, 1, 1, 4)
        v.addWidget(self.details)
        self._details_open = True
        return box

    def toggle_details(self):
        self._details_open = not self.details.isVisible() or self.details.maximumHeight() == 0
        self.details_btn.setChecked(self._details_open)
        motion.set_open(self.details, self._details_open)

    def _stats(self):
        m = self.colors["muted"]
        # «trovati» e «selezionati» sono già nel titolo: qui solo l'esito, e solo quando c'è
        self.s_found = Stat("trovati", None, m)
        self.s_sel = Stat("selezionati", None, m)
        self.s_done = Stat("scaricati", OK, m, hide_zero=True)
        self.s_skip = Stat("già presenti", WARN, m, hide_zero=True)
        self.s_fail = Stat("errori", ERR, m, hide_zero=True)
        for s in (self.s_done, self.s_skip, self.s_fail):
            self.stats_row.addWidget(s)

    def _results(self) -> QFrame:
        c = self.colors
        box = QFrame(objectName="plain")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(20, 14, 20, 16)
        lay.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(14)
        self.progress_text = label("Nessuna ricerca in corso", "heading")
        top.addWidget(self.progress_text)
        top.addStretch()
        self.stats_row = QHBoxLayout()
        self.stats_row.setSpacing(14)
        top.addLayout(self.stats_row)
        self.speed = label("", "muted")
        top.addWidget(self.speed)
        self.pause_btn = QPushButton(icon("pause", c["muted"], 16), " Pausa", objectName="ghost")
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setToolTip("Pausa: i pezzi già scaricati restano; si riprende anche dopo aver chiuso l'app")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.hide()
        top.addWidget(self.pause_btn)
        self.open_dest = QPushButton(icon("folder-open", c["muted"], 15), " Apri cartella", objectName="ghost")
        self.open_dest.clicked.connect(self.open_destination)
        top.addWidget(self.open_dest)
        self.log_btn = QPushButton(icon("list", c["muted"], 15), " Registro", objectName="ghost")
        self.log_btn.setCheckable(True)
        self.log_btn.setToolTip("Mostra il registro di quello che succede (Cmd+L)")
        self.log_btn.toggled.connect(lambda on: self.tabs.setCurrentIndex(1 if on else 0))
        top.addWidget(self.log_btn)
        lay.addLayout(top)

        self.bar = QProgressBar(textVisible=False)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        lay.addWidget(self.bar)

        files_tab = QWidget()
        fl = QVBoxLayout(files_tab)
        fl.setContentsMargins(0, 8, 0, 0)
        fl.setSpacing(8)
        tools = QHBoxLayout()
        tools.setSpacing(0)
        sel_label = label("Seleziona", "field")
        sel_label.setContentsMargins(0, 0, 8, 0)
        tools.addWidget(sel_label)
        self.sel_buttons = [
            QPushButton("Tutti", objectName="segFirst"),
            QPushButton("Nessuno", objectName="seg"),
            QPushButton("Immagini", objectName="seg"),
            QPushButton("Video", objectName="segLast"),
        ]
        rules = (lambda f: True, lambda f: False, lambda f: kind_of(f.name) == "image",
                 lambda f: kind_of(f.name) == "video")
        for b, rule in zip(self.sel_buttons, rules):
            b.clicked.connect(lambda _=False, r=rule: self.select(r))
            b.setFixedHeight(24)
            tools.addWidget(b)
        tools.addSpacing(14)
        self.filter = QLineEdit(objectName="filter", placeholderText="Filtra per nome o cartella…")
        self.filter.setClearButtonEnabled(True)
        self.filter.addAction(icon("search", c["faint"], 14), QLineEdit.LeadingPosition)
        self.filter.textChanged.connect(self.apply_filter)
        self.filter.setMaximumWidth(320)
        self.filter.setFixedHeight(26)
        tools.addStretch()
        tools.addWidget(self.filter, 1)
        tools.addSpacing(14)
        self.thumbs = QCheckBox("Miniature")
        self.thumbs.setChecked(self.cfg.auto_thumbs)
        self.thumbs.setToolTip("Scarica una piccola anteprima di ogni immagine (usa più connessioni)")
        self.thumbs.toggled.connect(self.toggle_thumbs)
        tools.addWidget(self.thumbs)
        tools.addSpacing(8)
        self.grid_btn = QPushButton(icon("grid", c["muted"], 15), "", objectName="iconbtn")
        self.grid_btn.setCheckable(True)
        self.grid_btn.setToolTip("Vista a griglia (barra spaziatrice: anteprima grande)")
        self.grid_btn.toggled.connect(self.toggle_grid)
        tools.addWidget(self.grid_btn)
        QTimer.singleShot(0, lambda: self.grid_btn.setChecked(self.settings.value("grid_view", False, type=bool)))
        self.tools_row = QWidget()
        self.tools_row.setLayout(tools)
        tools.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self.tools_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Nome", "Cartella", "Dimensione", "Stato"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setItemDelegateForColumn(self.COL_STATUS, StatusDelegate(self.tree, c))
        h = self.tree.header()
        h.setSectionResizeMode(self.COL_NAME, QHeaderView.Stretch)
        h.setSectionResizeMode(self.COL_DIR, QHeaderView.Interactive)
        h.setSectionResizeMode(self.COL_SIZE, QHeaderView.Fixed)
        h.setSectionResizeMode(self.COL_STATUS, QHeaderView.Fixed)
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tree.headerItem().setTextAlignment(self.COL_SIZE, Qt.AlignRight | Qt.AlignVCenter)
        self.tree.setColumnWidth(self.COL_DIR, 180)
        self.tree.setColumnWidth(self.COL_SIZE, 92)
        self.tree.setColumnWidth(self.COL_STATUS, 150)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.itemChanged.connect(self.on_item_changed)
        self.tree.currentItemChanged.connect(self.on_current_changed)

        self.preview = PreviewPanel(c)
        self.preview.open_url.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(0)
        from .gridview import GridView
        self.grid = GridView(c)
        self.grid.checked_changed.connect(self._grid_checked)
        self.grid.current_url.connect(lambda u: self.items.get(u) and self.tree.setCurrentItem(self.items[u]))
        self.grid.activated_url.connect(lambda u: self.items.get(u) and self.open_item(self.items[u], 0))
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.tree)
        self.view_stack.addWidget(self.grid)
        split.addWidget(self.view_stack)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([660, 300])
        self.empty = EmptyState(c)
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.empty)
        self.list_stack.addWidget(split)
        QShortcut(QKeySequence(Qt.Key_Space), self.list_stack, activated=self.quick_look,
                  context=Qt.WidgetWithChildrenShortcut)
        frame = QFrame(objectName="listbox")       # lista con bordo sottile, come le tabelle delle Impostazioni
        fr = QVBoxLayout(frame)
        fr.setContentsMargins(1, 1, 1, 1)
        fr.addWidget(self.list_stack)
        fl.addWidget(frame, 1)

        self.log = QPlainTextEdit(readOnly=True, objectName="log")
        log_frame = QFrame(objectName="listbox")
        lfl = QVBoxLayout(log_frame)
        lfl.setContentsMargins(1, 1, 1, 1)
        lfl.addWidget(self.log)
        self.log.setMaximumBlockCount(20000)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        log_box = QWidget()
        lb = QVBoxLayout(log_box)
        lb.setContentsMargins(0, 8, 0, 0)
        lb.setSpacing(8)
        lt = QHBoxLayout()
        lt.setSpacing(6)
        self.verbose = QCheckBox("Dettagliato (ogni richiesta e ogni link scartato)")
        self.verbose.setChecked(self.cfg.verbose_log)
        self.verbose.toggled.connect(self._verbose_changed)
        lt.addWidget(self.verbose)
        lt.addStretch()
        for text, slot in (("Copia", lambda: QGuiApplication.clipboard().setText(
                                "\n".join(l for _, l in self.log_lines))),
                           ("Salva…", self._save_log), ("Cartella log", self._open_log_dir)):
            b = QPushButton(text, objectName="chip")
            b.clicked.connect(slot)
            lt.addWidget(b)
        lb.addLayout(lt)
        lb.addWidget(log_frame, 1)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(files_tab, "File")
        self.tabs.addTab(log_box, "Registro")
        self.tabs.tabBar().hide()               # si passa al registro col pulsante «Registro» in alto
        self.tabs.currentChanged.connect(lambda i: self.log_btn.setChecked(i == 1))
        lay.addWidget(self.tabs, 1)
        return box

    def _show_list(self, on: bool):
        self.list_stack.setCurrentIndex(1 if on else 0)
        self.tools_row.setVisible(on)           # niente controlli che non servono a lista vuota

    # ---------- stati ----------
    def set_state(self, state: int):
        self.state = state
        busy = state in (self.SCANNING, self.DOWNLOADING)
        c = self.colors
        if busy:
            self.start.setText(tr("Interrompi"))
            self.start.setIcon(icon("stop", "#FFFFFF", 16))
            self.start.setObjectName("danger")
            self.start.setEnabled(True)
        elif state == self.REVIEW:
            n = self.selected_count()
            self.start.setText(tr("Scarica {n} file", n=n))
            self.start.setIcon(icon("download", "#FFFFFF", 16))
            self.start.setObjectName("primary")
            self.start.setEnabled(n > 0)
        else:
            direct = self.direct.isChecked()
            self.start.setText(tr("Scarica tutto") if direct else tr("Cerca file"))
            self.start.setIcon(icon("download" if direct else "search", "#FFFFFF", 16))
            self.start.setObjectName("primary")
            self.start.setEnabled(True)
        self.start.setStyle(self.start.style())
        for b in self.sel_buttons:
            b.setEnabled(state == self.REVIEW)
        if hasattr(self, "bar"):
            self.bar.setVisible(busy)
        if hasattr(self, "pause_btn"):
            paused = state == self.REVIEW and getattr(self, "_paused_last", False)
            self.pause_btn.setVisible(state == self.DOWNLOADING or paused)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText(" " + (tr("Riprendi") if paused else tr("Pausa")))
            self.pause_btn.setIcon(icon("play" if paused else "pause", c["muted"], 16))
        if hasattr(self, "browser_btn"):
            self.browser_btn.setEnabled(not busy)
        if hasattr(self, "details") and getattr(self, "_last_state", None) != state:
            # entrando in ricerca i dettagli si chiudono (più spazio alla lista); tornando a riposo si riaprono
            if state == self.SCANNING:
                motion.set_open(self.details, False)
                self.details_btn.setChecked(False)
            elif state == self.IDLE:
                motion.set_open(self.details, getattr(self, "_details_open", True))
                self.details_btn.setChecked(getattr(self, "_details_open", True))
        self._last_state = state
        self._update_menubar()
        if state != self.IDLE or self.tree.topLevelItemCount():
            self._show_list(True)

    def primary_action(self):
        if self.state in (self.SCANNING, self.DOWNLOADING):
            if self.queue_active:
                self.queue.clear()
                self.write_log("Coda interrotta")
            if self.dl:
                self.dl.stop()
            if getattr(self, "fetcher", None) is not None:
                self.fetcher.stop()
                return
            if not any(t.isRunning() for t, _w in self._alive):   # nessun lavoro vivo: sblocca subito
                self.write_log("Interrotto")
                self.set_state(self.IDLE)
                return
            self.start.setText(tr("Interruzione…"))
            self.start.setEnabled(False)
        elif self.state == self.REVIEW:
            self.start_download()
        else:
            self.start_scan()

    def on_url_changed(self, *_):
        self.update_detected()
        if self.state == self.REVIEW and self.url.links() != self.scanned_links:
            self.set_state(self.IDLE)

    # ---------- menu e barra di stato ----------
    def _menus(self):
        mb = self.menuBar()

        def act(menu, text, slot, shortcut=None, role=None, checkable=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if role is not None:
                a.setMenuRole(role)
            a.setCheckable(checkable)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        app_menu = mb.addMenu(APP_NAME)
        act(app_menu, tr("Informazioni su {a}", a=APP_NAME), self.show_about, role=QAction.AboutRole)
        act(app_menu, "Controlla aggiornamenti…", lambda: self.check_updates(auto=False),
            role=QAction.ApplicationSpecificRole)
        act(app_menu, "Impostazioni…", self.show_settings, QKeySequence.Preferences, QAction.PreferencesRole)
        app_menu.addSeparator()
        act(app_menu, "Esci", self.close, QKeySequence.Quit, QAction.QuitRole)

        f = mb.addMenu("File")
        act(f, "Nuovo progetto", self.new_project, QKeySequence.New)
        act(f, "Salva progetto", self.save_project, QKeySequence.Save)
        f.addSeparator()
        act(f, "Cerca file", self.primary_action, "Ctrl+Return")
        act(f, "Apri nel browser interno", lambda: self.start_scan(force_browser=True), "Ctrl+B")
        f.addSeparator()
        act(f, "Apri cartella dei download", self.open_destination, "Ctrl+Shift+D")
        act(f, "Apri cartella dei template", self.open_templates)
        act(f, "Apri cartella dei log", self._open_log_dir)
        f.addSeparator()
        act(f, "Esporta progetti e impostazioni…", self.export_backup)
        act(f, "Importa progetti e impostazioni…", self.import_backup)

        from . import editmenu
        e = mb.addMenu("Modifica")
        editmenu.add_actions(self, e)

        v = mb.addMenu("Vista")
        self.act_verbose = act(v, "Registro dettagliato", lambda on: self.verbose.setChecked(on), checkable=True)
        self.act_verbose.setChecked(self.cfg.verbose_log)
        self.act_thumbs = act(v, "Miniature", lambda on: self.thumbs.setChecked(on), checkable=True)
        self.act_thumbs.setChecked(self.cfg.auto_thumbs)
        v.addSeparator()
        act(v, "Template…", self.show_templates, "Ctrl+T")

        t = mb.addMenu("Strumenti")
        act(t, "Statistiche…", self.show_stats, "Ctrl+I")
        act(t, "Cerca nei file scaricati…", self.show_library, "Ctrl+Shift+F")
        act(t, "Controlla i siti…", self.show_site_check)
        act(t, "Editor dei template…", self.show_template_editor, "Ctrl+E")
        act(t, "Manda ad AllDownload dal browser…", self.show_send_to)
        t.addSeparator()
        act(t, "Pausa / riprendi", self.toggle_pause, "Ctrl+P")

        h = mb.addMenu("Aiuto")
        act(h, "Controlla aggiornamenti…", lambda: self.check_updates(auto=False))
        act(h, "Apri il registro di questa sessione", self._open_current_log)
        act(h, tr("Informazioni su {a}", a=APP_NAME), self.show_about)

    # ---------- aggiornamenti ----------
    def check_updates(self, auto: bool = True):
        """auto: all'avvio, al massimo una volta ogni 20 ore e in silenzio se non c'è niente."""
        import time as _t
        from .update_dialog import check_async
        if auto and (not self.cfg.check_updates or _t.time() - self.cfg.last_update_check < 20 * 3600):
            return
        if getattr(self, "_upd_checking", False):
            return
        self._upd_checking = True
        if not auto:
            self.statusBar().showMessage(tr("Controllo gli aggiornamenti…"))
        self._upd_bridge = check_async(self.cfg.github_token,
                                       lambda info: self._update_found(info, auto),
                                       lambda msg: self._update_error(msg, auto))

    def _update_found(self, info, auto: bool):
        import time as _t
        self._upd_checking = False
        self.cfg.last_update_check = _t.time()
        self.cfg.save()
        if info is None:
            if not auto:
                self.statusBar().showMessage(tr("Hai già l'ultima versione ({v}).", v=__version__), 5000)
                self.toast(tr("Hai già l'ultima versione ({v}).", v=__version__))
            return
        self.write_log(f"Nuova versione disponibile: {info.version} (tu hai {__version__})")
        if auto and info.version == self.cfg.skip_version:
            return
        from .update_dialog import UpdateDialog
        dlg = UpdateDialog(self, info, self.cfg.github_token, busy=self.state != self.IDLE)
        dlg.setStyleSheet(self.styleSheet())
        dlg.skip.connect(self._skip_version)
        dlg.exec()

    def _skip_version(self, v: str):
        self.cfg.skip_version = v
        self.cfg.save()
        self.statusBar().showMessage(tr("Non ti avviso più per la versione {v}.", v=v), 5000)

    def _update_error(self, msg: str, auto: bool):
        self._upd_checking = False
        self.write_log(f"Aggiornamenti: {msg}", logging.WARNING if auto else logging.ERROR)
        if not auto:
            self.statusBar().showMessage(msg, 8000)
            if "token" in msg.lower():
                self._token_help(msg)
            else:
                self.toast(msg, "err")

    TOKEN_URL = ("https://github.com/settings/personal-access-tokens/new?name=AllDownload%20aggiornamenti"
                 "&description=Solo%20lettura%20per%20gli%20aggiornamenti%20di%20AllDownload"
                 "&target_name=m4st3r-0day&expires_in=365&contents=read")

    def _token_help(self, msg: str):
        """Repo privato: spiega in tre passi come creare il token e dove metterlo."""
        box = QMessageBox(QMessageBox.Information, APP_NAME, tr("Per gli aggiornamenti serve un token GitHub"), parent=self)
        box.setInformativeText(tr(
            "Il repo di AllDownload è privato. Una volta sola:\n\n"
            "1. «Crea il token»: si apre GitHub con i campi già pronti (solo lettura dei file).\n"
            "2. In «Repository access» scegli «Only select repositories» → alldownload, poi «Generate token».\n"
            "3. Copia il token e incollalo in Impostazioni → Generale → Aggiornamenti."))
        make = box.addButton(tr("Crea il token"), QMessageBox.AcceptRole)
        sett = box.addButton(tr("Apri le Impostazioni"), QMessageBox.ActionRole)
        box.addButton(tr("Chiudi"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is make:
            QDesktopServices.openUrl(QUrl(self.TOKEN_URL))
        elif box.clickedButton() is sett:
            self.show_settings(page=0)

    def show_library(self):
        from .library import LibraryDialog
        LibraryDialog(self, self.store.path, self.dest.text() or self.cfg.dest_dir, human_size).exec()

    def show_site_check(self):
        from .sitecheck import check_sites
        projects = self.store.list()
        if not projects:
            QMessageBox.information(self, tr("Controlla i siti"), tr("Salva prima almeno un progetto con un link."))
            return
        if self.state != self.IDLE and self.state != self.REVIEW:
            QMessageBox.information(self, tr("Controlla i siti"), tr("Aspetta che finisca la ricerca o il download."))
            return
        self.write_log(tr("Controllo dei siti: cerco (senza scaricare) un link per sito…"))
        self.log_btn.setChecked(True)
        icons = {"ok": "✓", "empty": "○", "error": "✕", "skipped": "–"}

        def done(r):
            extra = tr("{n} file", n=r.found) if r.status == "ok" else tr(r.message or "0 file")
            self.write_log(f"{icons[r.status]} {r.site} ({r.plugin}): {extra}")

        def work():
            res = check_sites(projects, tempfile.mkdtemp(prefix="alldownload-check-"), done)
            ok = sum(r.status == "ok" for r in res)
            bad = sum(r.status in ("error", "empty") for r in res)
            self.write_log(tr("Controllo finito: {ok} siti vanno, {bad} da guardare.", ok=ok, bad=bad))

        threading.Thread(target=work, daemon=True).start()

    def export_backup(self):
        from . import backup
        path, _ = QFileDialog.getSaveFileName(self, tr("Esporta progetti e impostazioni"),
                                              str(Path.home() / f"AllDownload-backup-{time.strftime('%Y%m%d')}.zip"),
                                              "Zip (*.zip)")
        if not path:
            return
        box = QMessageBox(QMessageBox.Question, tr("Esporta"),
                          tr("Mettere anche proxy e token GitHub nel file?"),
                          QMessageBox.Yes | QMessageBox.No, self)
        box.setInformativeText(tr("Se mandi il file a qualcuno, scegli No: sono dati segreti."))
        box.setDefaultButton(QMessageBox.No)
        secrets = box.exec() == QMessageBox.Yes
        try:
            info = backup.export_zip(Path(path), include_secrets=secrets)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, tr("Esporta"), f"{type(e).__name__}: {e}")
            return
        self.toast(tr("Backup salvato ({n} file)", n=len(info["files"])))

    def import_backup(self):
        from . import backup
        path, _ = QFileDialog.getOpenFileName(self, tr("Importa progetti e impostazioni"), str(Path.home()),
                                              "Zip (*.zip)")
        if not path:
            return
        if QMessageBox.question(self, tr("Importa"), tr("I progetti e le impostazioni di adesso saranno sostituiti "
                                                         "(prima ne salvo una copia). Continuare?")) != QMessageBox.Yes:
            return
        try:
            self.store.close()
            keep = backup.import_zip(Path(path))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, tr("Importa"), f"{type(e).__name__}: {e}")
            return
        QMessageBox.information(self, tr("Importa"), tr("Fatto. Riapri {a} per usare i dati importati.\n"
                                                        "Copia di prima: {p}", a=APP_NAME, p=str(keep)))
        self.close()

    def show_stats(self):
        from .tools_dialogs import StatsDialog
        dlg = StatsDialog(self, self.history)
        dlg.setStyleSheet(self.styleSheet())
        dlg.exec()

    def show_template_editor(self, path=None):
        from .tools_dialogs import TemplateEditor
        dlg = TemplateEditor(self, path if isinstance(path, Path) else None)
        dlg.setStyleSheet(self.styleSheet())
        dlg.saved.connect(self.reload_templates)
        dlg.exec()

    def show_send_to(self):
        from .tools_dialogs import SendToDialog
        dlg = SendToDialog(self)
        dlg.setStyleSheet(self.styleSheet())
        dlg.exec()

    def receive_link(self, raw: str):
        """18: link arrivato dal browser (alldownload://add?url=...)."""
        from .tools_dialogs import parse_send_url
        link = parse_send_url(raw) or (raw if raw.startswith(("http://", "https://")) else None)
        if not link:
            return
        self.url.add_link(link)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.statusBar().showMessage(tr("Link ricevuto dal browser: {u}", u=link), 6000)
        self.write_log(f"Link ricevuto dal browser: {link}")

    def _status_widgets(self):
        self.net_label = label("", "muted")
        self.statusBar().addPermanentWidget(self.net_label)
        self._update_net_label()

    def _update_net_label(self):
        c = self.cfg
        if c.proxy_mode != "off" and c.proxy_list_url and not getattr(self, "_list_loaded", False):
            from .proxies import apply_list, fetch_list, mask_link
            self._list_loaded = True                      # una volta per avvio
            try:
                c.proxies = apply_list(c.proxies, fetch_list(c.proxy_list_url))
                c.save()
                self.proxy_pool = None
            except Exception as e:  # noqa: BLE001
                self.write_log(f"Lista proxy {mask_link(c.proxy_list_url)} non scaricata ({e}): "
                               f"uso quella dell'ultima volta", logging.WARNING)
        if c.proxy_mode != "off" and c.enabled_proxies():
            cur = self.proxy_pool.current if self.proxy_pool and self.proxy_pool.current else None
            px = f"proxy: {mask(cur)}" if cur else tr("proxy: {n} in lista", n=len(c.enabled_proxies()))
        else:
            px = tr("connessione diretta")
        speed = f" · max {c.speed_limit_kbps} KB/s" if c.speed_limit_kbps else ""
        self.net_label.setText(tr("{px} · {a} insieme, {b} per server", px=px, a=c.parallel, b=c.per_host) + speed + "  ")
        if hasattr(self, "net_badge"):
            short_px = tr("Proxy") if c.proxy_mode != "off" and c.enabled_proxies() else tr("Diretta")
            self.net_badge.setText(" " + tr("Rete") + ": " + short_px)
            self.net_badge.setToolTip(tr("Rete") + ": " + px)

    def _verbose_changed(self, on: bool):
        self.cfg.verbose_log = on
        self.cfg.save()
        if hasattr(self, "act_verbose"):
            self.act_verbose.setChecked(on)
        self._rerender_log()

    def show_settings(self, page: int = 0):
        if self.state in (self.SCANNING, self.DOWNLOADING):
            self.statusBar().showMessage(tr("Aspetta la fine del lavoro in corso per cambiare le impostazioni."), 4000)
            return
        dlg = SettingsDialog(self, self.cfg, self.colors)
        dlg.setStyleSheet(self.styleSheet())
        if isinstance(page, int) and page:
            dlg.nav.setCurrentRow(page)
        if dlg.exec() and dlg.result_settings is not None:
            old_dest = self.cfg.dest_dir
            old_look = (self.cfg.language, self.cfg.theme)
            self.cfg = dlg.result_settings
            motion.set_user_reduce(self.cfg.reduce_motion)
            if getattr(self, "menubar_icon", None):
                self.menubar_icon.show(self.cfg.show_menubar)
            self.cfg.save()
            self.proxy_pool = None
            if self.dest.text() == old_dest:
                self.dest.setText(self.cfg.dest_dir)
            self.verbose.setChecked(self.cfg.verbose_log)
            self.watch_timer.setInterval(max(1, self.cfg.watch_check_minutes) * 60_000)
            self._update_net_label()
            if (self.cfg.language, self.cfg.theme) != old_look:
                self.apply_look()
            glog.info("Impostazioni salvate in %s", Settings.path())
            self.statusBar().showMessage(tr("Impostazioni salvate."), 3000)
            self.toast(tr("Impostazioni salvate."))

    def apply_look(self):
        """Lingua e tema nuovi subito, senza riavviare."""
        set_language(self.cfg.language)
        dark = self.cfg.theme == "dark" or (self.cfg.theme == "system" and is_dark())
        self.colors.clear()
        self.colors.update(palette_for(dark))          # stesso dizionario: lo vedono anche lista e pannelli
        self.setStyleSheet(stylesheet(self.colors))
        translate_tree(self)
        mb = getattr(self, "menubar_icon", None)
        if mb is not None:
            translate_tree(mb.menu)
            mb.dark_bg = dark
            mb._key = None
            self._update_menubar()
        self.set_state(self.state)                     # testi dei pulsanti che dipendono dallo stato
        self.empty.retranslate()
        self._update_net_label()
        self.reload_templates(reload=False)
        self.panel.refresh(quick=True)
        self.statusBar().showMessage(tr("Pronto. Incolla un link o trascinalo nella finestra."), 4000)
        self.tree.viewport().update()
        self.write_log(f"Aspetto: lingua {self.cfg.language}, tema {self.cfg.theme}")

    def show_about(self):
        from PySide6 import __version__ as qt_ver
        from .logs import log_dir
        from .projects import default_db_path
        box = QMessageBox(self)
        box.setWindowTitle(tr("Informazioni su {a}", a=APP_NAME))
        box.setIconPixmap(app_icon().pixmap(64, 64))
        box.setText(f"<h3 style='margin-bottom:2px'>{APP_NAME} {__version__}</h3>"
                    f"<p>{tr('Scarica foto e video da link condivisi.')}<br>"
                    f"{tr('Legge anche i template .etmpl di Extreme Picture Finder.')}</p>"
                    f"<p style='color:{self.colors['muted']}'>{tr('Per uso personale: i tuoi file o contenuti che hai il diritto di scaricare. Sei tu responsabile di come lo usi.')}</p>"
                    f"<p style='color:{self.colors['muted']}'>Qt / PySide6 {qt_ver} · Python {sys.version.split()[0]}</p>")
        box.setInformativeText(
            f"<b>{tr('Dove sono i tuoi dati')}</b><br>"
            f"{tr('Impostazioni')}: <code>{Settings.path()}</code><br>"
            f"{tr('Progetti')}: <code>{default_db_path()}</code><br>"
            f"Template: <code>{plugins.user_templates_dir()}</code><br>"
            f"{tr('Registri')}: <code>{log_dir()}</code>")
        box.exec()

    def _open_current_log(self):
        if self.log_file:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_file)))

    def toast(self, text: str, tone: str = "ok", ms: int = 3200):
        if not hasattr(self, "_toast"):
            self._toast = motion.Toast(self.centralWidget(), self.colors)
        self._toast.show_message(text, tone, ms)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "_toast"):
            self._toast.reposition()

    def _finished_notice(self):
        n = self.n
        msg = tr("{a} scaricati, {b} già presenti, {c} errori", a=n["done"], b=n["skipped"], c=n["failed"])
        self.toast(msg, "err" if n["failed"] and not n["done"] else ("warn" if n["failed"] else "ok"), 4500)
        title = f"{APP_NAME} — {self.project.title}" if self.project else tr("{a}: download finito", a=APP_NAME)
        if self.cfg.notify_when_done:
            QApplication.alert(self, 0)                 # Dock che rimbalza / barra che lampeggia
            if getattr(self, "menubar_icon", None) and self.menubar_icon.tray.isVisible():
                self.menubar_icon.notify(title, msg)
            elif QSystemTrayIcon.isSystemTrayAvailable():
                if not hasattr(self, "tray"):
                    self.tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull()
                                                else self.style().standardIcon(QStyle.SP_ArrowDown), self)
                    self.tray.setToolTip(APP_NAME)
                    self.tray.messageClicked.connect(lambda: (self.showNormal(), self.raise_(), self.activateWindow()))
                self.tray.show()
                self.tray.showMessage(title, msg, QSystemTrayIcon.Information, 6000)
        if self.cfg.open_folder_when_done and n["done"]:
            self.open_destination()

    # ---------- progetti ----------
    def _fill_project(self, p: Project):
        p.title = self.title_edit.text().strip() or p.title
        p.category = self.category.currentText().strip()
        p.links = self.url.links()
        p.password = self.password.text()
        p.dest = self.dest.text()
        p.all_files = self.all_files.isChecked()

    def _refresh_categories(self):
        cur = self.category.currentText()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems(self.store.categories())
        self.category.setCurrentText(cur)
        self.category.blockSignals(False)

    def open_project(self, p: Project | None):
        if self.state in (self.SCANNING, self.DOWNLOADING):
            return
        self.project = p
        self._refresh_categories()
        self.title_edit.setText(p.title if p else "")
        self.category.setCurrentText(p.category if p else "")
        self.url.setText("\n".join(p.links) if p else "")
        self.password.setText(p.password if p else "")
        if p and p.dest:
            self.dest.setText(p.dest)
        self.all_files.setChecked(p.all_files if p else False)
        self.tree.clear()
        self.grid.clear_all()
        self.items.clear()
        self.files.clear()
        self.preview.clear()
        self._show_list(False)
        self.reset_counters()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.set_state(self.IDLE)
        if p:
            self.setWindowTitle(f"{APP_NAME} — {p.title}")
            self.progress_text.setText(tr("{n} file già scaricati · «Cerca file» mostra i nuovi", n=p.saved))
        else:
            self.setWindowTitle(APP_NAME)
            self.progress_text.setText(tr("Nessuna ricerca in corso"))

    def new_project(self):
        self.panel.select_quick()
        self.title_edit.setFocus()
        self.statusBar().showMessage(tr("Scrivi nome, link e cartella, poi «Salva progetto»."), 5000)

    def save_project(self):
        links = self.url.links()
        if not links:
            self.statusBar().showMessage(tr("Aggiungi almeno un link prima di salvare."), 4000)
            self.url.setFocus()
            return
        p = self.project or Project(title="")
        if not self.title_edit.text().strip():
            first = plugins.find_plugin(links[0])
            base = first.t.service if isinstance(first, EtmplPlugin) else (first.NAME if first else "Progetto")
            self.title_edit.setText(f"{base} {time.strftime('%d-%m %H.%M')}")
        self._fill_project(p)
        new = p.id is None
        self.store.save(p)
        self.project = p
        # i file già scaricati in questa sessione entrano nel progetto appena creato
        if new:
            for url, it in self.items.items():
                path = it.data(self.COL_DIR, Qt.UserRole)
                if path:
                    self.store.record(p.id, url, "done", Path(path).name, path)
        self._refresh_categories()
        self.panel.refresh(select_id=p.id)
        self.setWindowTitle(f"{APP_NAME} — {p.title}")
        self.statusBar().showMessage((tr("Progetto creato: {t}", t=p.title) if new else tr("Progetto salvato: {t}", t=p.title)), 4000)

    # ---------- coda ----------
    def update_projects(self, ids: list[int]):
        if self.state in (self.SCANNING, self.DOWNLOADING):
            self.statusBar().showMessage(tr("Aspetta che finisca il lavoro in corso."), 4000)
            return
        prio = {i: (self.store.get(i).priority if self.store.get(i) else 1) for i in ids}
        self.queue = sorted(ids, key=lambda i: -prio[i])      # 7: prima i progetti con priorità alta
        self.queue_total = len(ids)
        self.queue_active = True
        self.write_log(f"Coda: {len(ids)} progett{'o' if len(ids) == 1 else 'i'} da aggiornare")
        self._queue_next()

    def _check_watched(self):
        """16: se l'app è libera, aggiorna da sola i progetti osservati che sono «scaduti»."""
        if self.state != self.IDLE or self.queue_active:
            return
        due = self.store.due_for_watch()
        if not due:
            return
        self.write_log(f"Controllo automatico: {', '.join(p.title for p in due)}")
        self._watch_run = True
        self.update_projects([p.id for p in due])

    def _queue_next(self):
        if not self.queue:
            if self.queue_active:
                self.queue_active = False
                msg = f"Coda finita: {self.queue_total} progett{'o' if self.queue_total == 1 else 'i'} aggiornat{'o' if self.queue_total == 1 else 'i'}"
                self.write_log(msg)
                self.statusBar().showMessage(msg)
            return
        pid = self.queue.pop(0)
        p = self.store.get(pid)
        if p is None:
            self._queue_next()
            return
        done = self.queue_total - len(self.queue)
        self.panel.refresh(select_id=pid)
        self.open_project(p)
        self.statusBar().showMessage(tr("Coda: progetto {a} di {b} — {t}", a=done, b=self.queue_total, t=p.title))
        self.start_scan(direct=True)

    def _queue_continue(self):
        if self.queue_active:
            QTimer.singleShot(400, self._queue_next)

    # ---------- template ----------
    def reload_templates(self, reload: bool = True):
        if reload:
            plugins.reload()
            for err in plugins.load_errors():
                self.write_log(f"Template non valido: {err}")
            for old in plugins.superseded():
                self.write_log(f"Template più vecchio ignorato: {old}")
        es = plugins.entries()
        on = [e for e in es if e["enabled"]]
        self.tpl_badge.setText(" " + tr("{n} template attivi", n=len(on)))
        self.tpl_badge.setToolTip(tr("Attivi:") + "\n" + "\n".join(
            f"• {e['service']}" + (f" ({e['kind']})" if e["kind"] else "") for e in on)
            + "\n\n" + tr("Clic per vedere e gestire i template"))
        self.update_detected()

    @staticmethod
    def describe(p) -> str:
        if isinstance(p, EtmplPlugin):
            kind = " ".join(tr(w) for w in p.t.kind.split(" ")) if p.t.kind != "link condiviso" else tr(p.t.kind)
            return p.t.service + (f" · {kind}" if kind else "")
        return f"{p.NAME} · " + tr("plugin Python")

    def update_detected(self):
        links = self.url.links()
        if not links:
            self.detected.setText("")
            return
        found = [(u, plugins.find_plugin(u)) for u in links]
        bad = [u for u, p in found if p is None]
        if len(links) == 1:
            p = found[0][1]
            if p is None:
                self.detected.setText("✗ " + tr("Nessun template attivo riconosce questo link"))
            else:
                name = f"   ({p.t.path.name})" if isinstance(p, EtmplPlugin) else ""
                self.detected.setText("✓ " + tr("Servizio: {s}", s=self.describe(p)) + name)
        else:
            services = sorted({self.describe(p) for _, p in found if p})
            text = tr("{n} link", n=len(links)) + " · " + (", ".join(services) if services else tr("nessun servizio"))
            if bad:
                text += "   ✗ " + tr("{n} non riconosciuti", n=len(bad))
            self.detected.setText(("✓ " if not bad else "") + text)
        color = ERR if bad and len(bad) == len(links) else WARN if bad else OK
        self.detected.setStyleSheet(f"color: {color};")

    def show_templates(self):
        dlg = TemplatesDialog(self, self.colors)
        translate_tree(dlg)
        dlg.changed.connect(lambda: self.reload_templates(reload=False))
        dlg.reloaded.connect(lambda: self.reload_templates(reload=True))
        dlg.exec()

    def open_templates(self):
        d = plugins.user_templates_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ---------- azioni semplici ----------
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Cartella di destinazione"), self.dest.text())
        if d:
            self.dest.setText(d)

    def open_destination(self):
        p = Path(self.dest.text()).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def open_item(self, item: QTreeWidgetItem):
        path = item.data(self.COL_DIR, Qt.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        else:
            QDesktopServices.openUrl(QUrl(item.data(self.COL_NAME, Qt.UserRole)))

    def write_log(self, text: str, level: int = logging.INFO):
        glog.log(level, text)

    def _append_log(self, levelno: int, line: str):
        self.log_lines.append((levelno, line))
        if levelno >= logging.INFO or self.verbose.isChecked():
            self.log.appendPlainText(line)

    def _rerender_log(self):
        show_debug = self.verbose.isChecked()
        self.log.setPlainText("\n".join(l for lv, l in self.log_lines if show_debug or lv >= logging.INFO))
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)

    def _save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Salva registro"),
                                              str(Path.home() / time.strftime("picfinder-registro-%Y%m%d-%H%M.txt")),
                                              "Testo (*.txt)")
        if path:
            Path(path).write_text("\n".join(l for _, l in self.log_lines), encoding="utf-8")
            self.statusBar().showMessage(tr("Registro salvato: {p}", p=path), 4000)

    def _open_log_dir(self):
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def reset_counters(self):
        self._pages_seen = 0
        self.n = dict(found=0, done=0, skipped=0, failed=0)
        for s in (self.s_found, self.s_sel, self.s_done, self.s_skip, self.s_fail):
            s.set(0)

    # ---------- selezione ----------
    def all_items(self):
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def selected_count(self) -> int:
        return sum(1 for it in self.all_items() if it.checkState(self.COL_NAME) == Qt.Checked)

    def select(self, rule):
        self.tree.blockSignals(True)
        for it in self.all_items():
            if not it.isHidden():
                f = self.files[it.data(self.COL_NAME, Qt.UserRole)]
                it.setCheckState(self.COL_NAME, Qt.Checked if rule(f) else Qt.Unchecked)
                self._paint_choice(it)
                self.grid.set_checked(f.url, rule(f))
        self.tree.blockSignals(False)
        self.update_selection()

    def apply_filter(self, text: str):
        t = text.strip().lower()
        for it in self.all_items():
            hide = bool(t) and t not in (it.text(self.COL_NAME) + " " + it.text(self.COL_DIR)).lower()
            it.setHidden(hide)
            self.grid.set_hidden(it.data(self.COL_NAME, Qt.UserRole), hide)

    def on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column == self.COL_NAME:
            self.grid.set_checked(item.data(self.COL_NAME, Qt.UserRole), item.checkState(self.COL_NAME) == Qt.Checked)
        if column == self.COL_NAME and self.state == self.REVIEW:
            self._paint_choice(item)
            self.update_selection()

    def _paint_choice(self, item: QTreeWidgetItem):
        if item.checkState(self.COL_NAME) == Qt.Checked:
            self._set_status(item, "Da scaricare")
        elif item.data(self.COL_SIZE, Qt.UserRole):
            self._set_status(item, "Già scaricato")
        else:
            self._set_status(item, "Escluso")

    def update_selection(self):
        n = self.selected_count()
        self.s_sel.set(n)
        if self.state == self.REVIEW:
            self.set_state(self.REVIEW)
            self.progress_text.setText(tr("{a} file trovati · {b} selezionati", a=self.n["found"], b=n))

    # ---------- anteprima ----------
    def on_current_changed(self, item, _prev=None):
        if not item:
            self.preview.clear()
            return
        f = self.files.get(item.data(self.COL_NAME, Qt.UserRole))
        if not f:
            return
        self.grid.select_url(f.url)
        path = item.data(self.COL_DIR, Qt.UserRole)
        k = kind_of(f.name)
        self.preview.show_file(f, f"Salvato in: {path}" if path else "")
        if path and k == "image":
            pix = QPixmap(str(path))
            if not pix.isNull():
                self.preview.set_pixmap(pix)
                return
        if k == "other" and not f.thumb:
            self.preview.set_message(tr("Anteprima non disponibile per questo tipo di file"))
        elif f.url in self.pv_cache:
            self.preview.set_pixmap(self.pv_cache[f.url])
        elif f.url in self.pv_errors:
            self.preview.set_message(tr("Anteprima non disponibile") + f"\n{self.pv_errors[f.url]}")
        else:
            self.preview.set_message(tr("Caricamento fotogramma…") if k == "video" else tr("Caricamento anteprima…"))
            self.request_preview(f, path)

    def request_preview(self, f: RemoteFile, local: str | None = None):
        if f.url in self.pv_pending or f.url in self.pv_cache or not self.dl:
            return
        if local is None and f.url in self.items:
            local = self.items[f.url].data(self.COL_DIR, Qt.UserRole)
        self.pv_pending.add(f.url)
        self.pool.start(PreviewTask(self.dl, f, self.pv_signals, local))

    def on_preview_loaded(self, url: str, data: bytes, error: str, source: str):
        self.pv_pending.discard(url)
        pix = QPixmap()
        f = self.files.get(url)
        if data and pix.loadFromData(data):
            if f and kind_of(f.name) == "video":
                pix = with_play_badge(pix)
            self.pv_cache[url] = pix
            self.pv_source[url] = source
            while len(self.pv_cache) > 300:
                self.pv_cache.popitem(last=False)
            item = self.items.get(url)
            if item and self.thumbs.isChecked():
                item.setIcon(self.COL_NAME, QIcon(pix.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            self.grid.set_pixmap(url, pix)
        else:
            self.pv_errors[url] = error or "formato non leggibile"
        if self.preview.url == url:
            if url in self.pv_cache:
                self.preview.set_pixmap(self.pv_cache[url])
                if f:
                    item = self.items.get(url)
                    path = item.data(self.COL_DIR, Qt.UserRole) if item else None
                    extra = (f"Salvato in: {path}<br>" if path else "") + f"Anteprima: {source}"
                    self.preview.show_file(f, extra)
            else:
                self.preview.set_message(tr("Anteprima non disponibile") + f"\n{self.pv_errors.get(url, '')}")

    # ---------- griglia e anteprima veloce ----------
    def toggle_grid(self, on: bool):
        self.view_stack.setCurrentIndex(1 if on else 0)
        self.settings.setValue("grid_view", on)
        if on:
            for url in self.grid.urls():
                f = self.files.get(url)
                if f is None:
                    continue
                if url in self.pv_cache:
                    self.grid.set_pixmap(url, self.pv_cache[url])
                elif kind_of(f.name) in ("image", "video") or f.thumb:
                    self.request_preview(f)
            cur = self.tree.currentItem()
            if cur is not None:
                self.grid.select_url(cur.data(self.COL_NAME, Qt.UserRole))

    def _grid_checked(self, url: str, checked: bool):
        it = self.items.get(url)
        if it is not None:
            it.setCheckState(self.COL_NAME, Qt.Checked if checked else Qt.Unchecked)

    def quick_look(self):
        """Barra spaziatrice: file già scaricato → Quick Look del Mac; se no anteprima grande."""
        from .gridview import QuickLook, system_quick_look
        cur = self.tree.currentItem()
        if cur is None:
            return
        local = cur.data(self.COL_DIR, Qt.UserRole)
        if local and system_quick_look(str(local)):
            return
        visible = [it for it in self.all_items() if not it.isHidden()]
        entries = []
        for it in visible:
            url = it.data(self.COL_NAME, Qt.UserRole)
            f = self.files.get(url)
            pix = None
            path = it.data(self.COL_DIR, Qt.UserRole)
            if path and f and kind_of(f.name) == "image":
                p = QPixmap(str(path))
                pix = p if not p.isNull() else None
            if pix is None:
                pix = self.pv_cache.get(url)
                if pix is None and f is not None:
                    self.request_preview(f)
            entries.append((it.text(self.COL_NAME), url, pix))
        idx = next((i for i, it in enumerate(visible) if it is cur), 0)
        dlg = QuickLook(self, entries, idx)
        dlg.exec()
        if 0 <= dlg.index < len(visible):
            self.tree.setCurrentItem(visible[dlg.index])

    def toggle_thumbs(self, on: bool):
        self.tree.setIconSize(QSize(48, 48) if on else QSize(16, 16))
        for it in self.all_items():
            url = it.data(self.COL_NAME, Qt.UserRole)
            f = self.files.get(url)
            if not on:
                it.setIcon(self.COL_NAME, QIcon())
            elif f and (kind_of(f.name) in ("image", "video") or f.thumb):
                if url in self.pv_cache:
                    it.setIcon(self.COL_NAME, QIcon(self.pv_cache[url].scaled(
                        96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
                else:
                    self.request_preview(f)

    # ---------- fase 1: cerca ----------
    def _new_downloader(self) -> Downloader:
        c = self.cfg
        if c.proxy_mode != "off" and c.enabled_proxies():
            if self.proxy_pool is None:
                self.proxy_pool = ProxyPool(c.enabled_proxies(), c.proxy_mode, c.proxy_test_url)
            self.proxy_pool.dead.clear()              # a ogni lavoro nuovo si riprova anche chi era caduto
        else:
            self.proxy_pool = None
        return self._post_options(Downloader(self.dest.text(), None if self.all_files.isChecked() else DEFAULT_PATTERNS,
                          transport=self.transport, concurrency=c.parallel, per_host=c.per_host,
                          retries=c.retries, timeout=c.timeout, speed_limit_kbps=c.speed_limit_kbps,
                          default_conflicts=c.default_conflicts, proxy_pool=self.proxy_pool,
                          user_agent=c.custom_user_agent or None, preview_max_mb=c.preview_max_mb,
                          ffmpeg_path=c.ffmpeg_path or None, folder_per_link=c.folder_per_link,
                          split_by_type=c.split_by_type, pause_scale=PAUSE_SCALE.get(c.pauses, 1.0),
                          history=self.history, skip_known=c.skip_downloaded,
                          adaptive=c.adaptive, segments=c.segments, http2=c.http2,
                          schedule=Schedule(c.schedule_enabled, c.schedule_start, c.schedule_end,
                                            c.pause_on_battery) if (c.schedule_enabled or c.pause_on_battery) else None,
                          bandwidth_share=c.bandwidth_share, warn_requests=c.warn_requests,
                          dup_images=c.dup_images))

    def _post_options(self, dl: Downloader) -> Downloader:
        c = self.cfg
        dl.name_pattern, dl.file_dates, dl.save_captions = c.name_pattern, c.file_dates, c.save_captions
        dl.verify_files, dl.reserve_mb = c.verify_files, c.reserve_gb * 1024
        return dl

    def _apply_settings(self, dl: Downloader):
        fresh = self._new_downloader()
        for k in ("history", "skip_known", "adaptive", "segments", "http2", "schedule", "warn_requests",
                  "dup_images", "proxy", "pool", "concurrency", "per_host", "retries", "timeout", "pause_scale",
                  "default_conflicts", "user_agent", "_limiter", "name_pattern", "file_dates", "save_captions",
                  "verify_files", "reserve_mb"):
            if hasattr(fresh, k):
                setattr(dl, k, getattr(fresh, k))

    def _start_worker(self, make_coro, on_result):
        # Il thread vecchio deve finire prima: se Python butta via un QThread/Worker
        # ancora vivo (o con segnali in coda), Qt va in crash (Segmentation fault).
        for t, _w in list(self._alive):                   # solo oggetti ancora vivi
            if t.isRunning():
                t.wait(5000)
        thread, worker = QThread(self), Worker(make_coro)
        self._alive.add((thread, worker))                    # tiene vivi gli oggetti finché Qt li usa
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event.connect(self.on_event)
        self._result_cb = on_result
        worker.result.connect(self._on_worker_result, Qt.QueuedConnection)
        worker.error.connect(self.on_error)
        worker.finished.connect(thread.quit)
        thread.finished.connect(self.on_thread_finished)
        thread.finished.connect(lambda t=thread, w=worker: self._release(t, w))
        self.dl.on_event = lambda k, d, w=worker: w.event.emit(k, d)
        self.thread, self.worker = thread, worker
        thread.start()

    def _release(self, thread, worker):
        """Libera thread e worker solo dopo che Qt ha finito con loro."""
        if self.thread is thread:
            self.thread = self.worker = None
        worker.deleteLater()
        thread.deleteLater()
        QTimer.singleShot(0, lambda: self._alive.discard((thread, worker)))

    def _on_worker_result(self, value):
        """Sempre nel thread dell'interfaccia (connessione in coda)."""
        cb, self._result_cb = getattr(self, "_result_cb", None), None
        if cb:
            cb(value)

    def _browser_sessions(self, links: list[str], force: bool) -> dict | None:
        """Apre il browser interno per i link che lo chiedono. None = l'utente ha annullato tutto."""
        sessions = {}
        for u in links:
            p = plugins.find_plugin(u)
            needs = plugins.needs_browser(p)
            if not (needs or force):
                continue
            try:
                from .browser import open_browser
            except ImportError as e:
                self.write_log(f"Browser interno non disponibile: {e}", logging.ERROR)
                return sessions
            name = self.describe(p) if p else u
            msg = plugins.browser_message(p)
            useful = plugins.browser_useful(p)
            self.statusBar().showMessage(tr("Browser interno: {n}", n=name))
            s = open_browser(self, u, msg, f"{name} — browser interno",
                             auto_continue=self.cfg.browser_auto_continue if self.queue_active else None,
                             useful=useful)
            if s is None:
                self.write_log(f"Browser annullato per {u}", logging.WARNING)
                if len(links) == 1:
                    return None
                continue
            sessions[u] = s
        return sessions

    FAN_SITES = re.compile(r"^https?://([^/]+\.)?(onlyfans\.com|fansly\.com)/", re.I)

    def _fan_site_check(self, links: list[str]) -> bool:
        """OnlyFans/Fansly: i link dei file valgono solo per l'IP del browser interno.
        Con i proxy (IP diversi) arrivano solo errori e attese: meglio la connessione diretta."""
        if not any(self.FAN_SITES.match(u) for u in links):
            return True
        c = self.cfg
        if c.proxy_mode != "off" and c.enabled_proxies():
            box = QMessageBox(QMessageBox.Warning, APP_NAME,
                              tr("Con OnlyFans e Fansly i proxy non funzionano."), parent=self)
            box.setInformativeText(tr(
                "I link dei file valgono solo per l'indirizzo IP del browser interno: con i proxy il sito "
                "risponde con errori o fa aspettare a lungo (timeout). Usa la connessione diretta."))
            off = box.addButton(tr("Disattiva i proxy e continua"), QMessageBox.AcceptRole)
            box.addButton(tr("Continua con i proxy"), QMessageBox.DestructiveRole)
            cancel = box.addButton(tr("Annulla"), QMessageBox.RejectRole)
            box.setDefaultButton(off)
            box.exec()
            if box.clickedButton() is cancel:
                return False
            if box.clickedButton() is off:
                c.proxy_mode = "off"
                c.save()
                self.write_log("OnlyFans/Fansly: proxy disattivati, uso la connessione diretta")
                self._update_net_label()
        if not c.fan_tip_shown:
            c.fan_tip_shown = True
            c.save()
            QMessageBox.information(self, APP_NAME, tr("OnlyFans e Fansly: come usarli") + "\n\n" + tr(
                "1. Si apre il browser interno: fai login la prima volta, aspetta che si vedano i contenuti, "
                "poi «Continua download».\n"
                "2. Funziona con i profili (Media) e con le chat (anche le foto e i video sbloccati).\n"
                "3. Niente proxy: i link valgono solo per il tuo IP, con i proxy vai in timeout.\n"
                "4. Se usi una VPN, scegli un server e non cambiarlo durante ricerca e download "
                "(e non cambiarlo spesso: il sito può chiederti di nuovo il login).\n"
                "5. Solo il tuo account e i contenuti a cui sei abbonato."))
        return True

    def start_scan(self, direct: bool | None = None, force_browser: bool = False):
        links = self.url.links()
        if not links:
            self.statusBar().showMessage(tr("Inserisci un link."), 3000)
            self.url.setFocus()
            self._queue_continue()
            return
        ok = [u for u in links if plugins.find_plugin(u)]
        if not ok:
            self.statusBar().showMessage(tr("Nessun template attivo riconosce questi link."), 5000)
            self._queue_continue()
            return
        if not self._fan_site_check(ok):
            self._queue_continue()
            return
        sessions = self._browser_sessions(ok, force_browser)
        if sessions is None:
            self.statusBar().showMessage(tr("Ricerca annullata."), 4000)
            self._queue_continue()
            return
        if self.project:                       # salva le modifiche fatte al progetto
            self._fill_project(self.project)
            self.store.save(self.project)
        self.known = self.store.known_paths(self.project.id) if self.project else {}
        self.settings.setValue("dest", self.dest.text())
        self.tree.clear()
        self.grid.clear_all()
        self.items.clear()
        self.files.clear()
        self.preview.clear()
        self.pv_cache.clear()
        self.pv_errors.clear()
        self.reset_counters()
        self.bar.setRange(0, 0)
        self.progress_text.setText(tr("Ricerca dei file…"))
        self.write_log(("Aggiorna: " + self.project.title) if self.project else f"Ricerca: {', '.join(ok)}")
        for u in links:
            if u not in ok:
                self.write_log(f"⚠ Nessun template per: {u}")
        self.scanned_links = links
        self.dl = self._new_downloader()
        direct = self.direct.isChecked() if direct is None else direct
        password = self.password.text() or None
        if direct:
            # 5: cerca e scarica insieme: ogni file parte appena trovato
            self._streaming = True
            self.to_download = 0
            self.set_state(self.DOWNLOADING)
            self.speed_timer.start()
            self._start_worker(lambda: self.dl.scan_and_download(ok, password, sessions), lambda stats: None)
            return
        self._streaming = False
        self.set_state(self.SCANNING)
        self._start_worker(lambda: self.dl.scan_many(ok, password, sessions),
                           lambda files: self.on_scanned(files, direct))

    def on_scanned(self, files: list, direct: bool):
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        if self.dl and self.dl._stop:
            self.progress_text.setText(tr("Ricerca interrotta: {n} file trovati", n=len(files)))
        if not files:
            self.progress_text.setText(tr("Nessun file trovato"))
            self._next_state = self.IDLE
            return
        new = self.selected_count()
        if self.project:
            self.write_log(f"{len(files)} file trovati, {new} nuovi")
        if direct and not self.dl._stop:
            if new == 0:
                self.progress_text.setText(tr("{n} file trovati · nessun file nuovo", n=len(files)))
                if self.project:
                    self.store.touch(self.project.id)
                self._next_state = self.REVIEW
                return
            self._next_state = "download"
            return
        self._next_state = self.REVIEW

    # ---------- fase 2: scarica ----------
    def start_download(self):
        chosen = [self.files[it.data(self.COL_NAME, Qt.UserRole)] for it in self.all_items()
                  if it.checkState(self.COL_NAME) == Qt.Checked]
        if not chosen:
            return
        if self._refresh_if_expired(chosen):
            return
        if not self._enough_space(chosen):
            return
        for it in self.all_items():
            if it.checkState(self.COL_NAME) == Qt.Checked:
                self._set_status(it, "In attesa")
        self.n.update(done=0, skipped=0, failed=0)
        for s in (self.s_done, self.s_skip, self.s_fail):
            s.set(0)
        self.dl.dest = Path(self.dest.text())
        self._apply_settings(self.dl)                # le impostazioni cambiate dopo la ricerca valgono subito
        self.dl._stop = False
        self.bar.setRange(0, len(chosen))
        self.bar.setValue(0)
        self.to_download = len(chosen)
        self.progress_text.setText(tr("{a} di {b} file", a=0, b=len(chosen)))
        self._streaming = False
        self._paused_last = False
        self.set_state(self.DOWNLOADING)
        self.speed_timer.start()
        self._start_worker(lambda: self.dl.download(chosen), lambda stats: None)

    def _enough_space(self, chosen: list) -> bool:
        """11: prima di partire: lo spazio basta? (con le dimensioni note; le altre non si sanno ancora)"""
        from .postproc import free_bytes
        free = free_bytes(Path(self.dest.text()))
        if free is None:
            return True
        need = sum(f.size or 0 for f in chosen)
        unknown = sum(1 for f in chosen if not f.size)
        reserve = self.cfg.reserve_gb * 1024 ** 3
        if free - need >= reserve:
            return True
        txt = tr("Spazio libero: {f}. Servono almeno {n}{u}, e vuoi lasciare libero {r}.",
                 f=human_size(free), n=human_size(need),
                 u=tr(" (più {k} file di cui non so la grandezza)", k=unknown) if unknown else "",
                 r=f"{self.cfg.reserve_gb} GB")
        ans = QMessageBox.warning(self, APP_NAME, tr("Lo spazio su disco potrebbe non bastare.") + "\n\n" + txt
                                  + "\n\n" + tr("Scarico lo stesso? Mi fermo da solo prima di riempire il disco."),
                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return ans == QMessageBox.Yes

    def _refresh_if_expired(self, chosen: list) -> bool:
        """14: link firmati scaduti → rifà la ricerca (anche col browser) e riscarica gli stessi file."""
        old = [f for f in chosen if expired(f.url)]
        if not old or getattr(self, "_reselect", None):
            return False
        ans = QMessageBox.question(
            self, APP_NAME, tr("{n} link sono scaduti (il sito li firma per poco tempo).", n=len(old)) + "\n"
            + tr("Rifaccio la ricerca e poi scarico gli stessi file?"))
        if ans != QMessageBox.Yes:
            return False
        self._reselect = {file_key(f.url) for f in chosen}
        self.write_log(f"Link scaduti: rifaccio la ricerca per {len(self._reselect)} file")
        self.start_scan(direct=False)
        return True

    def toggle_pause(self):
        """7: pausa (tiene i pezzi già scaricati) / riprendi."""
        if self.state == self.DOWNLOADING and self.dl:
            self.write_log("Pausa…")
            self.pause_btn.setEnabled(False)
            self.dl.pause()
        elif self.state == self.REVIEW and getattr(self, "_paused_last", False):
            self.start_download()

    @staticmethod
    def _finished_texts() -> set:
        return {tr("Completato"), tr("Già presente"), tr("Doppione"), tr("Già scaricato")}

    def _pending_path(self) -> Path:
        from .netpolicy import data_dir
        return data_dir() / "download_in_sospeso.json"

    def _save_pending(self):
        """7: file scelti e non ancora finiti → si riprendono anche dopo aver chiuso l'app."""
        todo = []
        for it in self.all_items():
            if it.checkState(self.COL_NAME) != Qt.Checked:
                continue
            if it.text(self.COL_STATUS) in self._finished_texts():
                continue
            f = self.files.get(it.data(self.COL_NAME, Qt.UserRole))
            if f:
                todo.append({"url": f.url, "name": f.name, "subdir": f.subdir, "size": f.size, "headers": f.headers,
                             "fixed_name": f.fixed_name, "opts": f.opts, "thumb": f.thumb})
        path = self._pending_path()
        if not todo:
            path.unlink(missing_ok=True)
            return
        import json
        data = {"dest": self.dest.text(), "project": self.project.id if self.project else None,
                "links": self.url.links(), "files": todo, "ts": time.time()}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, default=list), encoding="utf-8")
            self.write_log(f"{len(todo)} file in sospeso: si possono riprendere anche dopo")
        except (OSError, TypeError) as e:
            glog.warning("download in sospeso non salvato: %s", e)

    def _offer_pending(self):
        import json
        path = self._pending_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        files = data.get("files") or []
        if not files:
            path.unlink(missing_ok=True)
            return
        ans = QMessageBox.question(self, APP_NAME, tr("C'è un download in sospeso: {n} file. Riprendo?", n=len(files)))
        path.unlink(missing_ok=True)
        if ans != QMessageBox.Yes:
            return
        if data.get("project"):
            p = self.store.get(data["project"])
            if p:
                self.open_project(p)
        self.url.setText("\n".join(data.get("links") or []))
        if data.get("dest"):
            self.dest.setText(data["dest"])
        self.dl = self._new_downloader()
        self.reset_counters()
        for x in files:
            if isinstance(x.get("opts"), dict) and isinstance(x["opts"].get("delay"), list):
                x["opts"]["delay"] = tuple(x["opts"]["delay"])
            self.on_event("found", {"file": RemoteFile(**x)})
        self.set_state(self.REVIEW)
        self.update_selection()
        self.start_download()

    def on_thread_finished(self):
        self._update_net_label()
        nxt = getattr(self, "_next_state", None)
        self._next_state = None
        self.speed_timer.stop()
        self.speed.setText("")
        if self.state == self.SCANNING:
            if nxt == "download":
                self.state = self.REVIEW
                self.start_download()
                return
            if nxt == self.REVIEW and getattr(self, "_reselect", None):
                keys, self._reselect = self._reselect, None
                self.tree.blockSignals(True)
                for it in self.all_items():
                    f = self.files.get(it.data(self.COL_NAME, Qt.UserRole))
                    it.setCheckState(self.COL_NAME, Qt.Checked if f and file_key(f.url) in keys else Qt.Unchecked)
                self.tree.blockSignals(False)
                self.state = self.REVIEW
                self.update_selection()
                self.start_download()
                return
            if nxt == self.REVIEW:
                self.set_state(self.REVIEW)
                self.update_selection()
                if self.tree.topLevelItemCount() and not self.tree.currentItem():
                    self.tree.setCurrentItem(self.tree.topLevelItem(0))
                if self.queue_active:
                    if self.project:
                        self.panel.refresh(select_id=self.project.id)
                    self._queue_continue()
                return
            self.set_state(self.IDLE)
            self._queue_continue()
        elif self.state == self.DOWNLOADING:
            if self._retry_in_browser():
                return
            self._download_complete()

    def _retry_in_browser(self) -> bool:
        """File rifiutati perché legati all'IP del browser: li scarica il browser interno stesso."""
        failed = list(getattr(self.dl, "ip_failed", []) or []) if self.dl else []
        if not failed or (self.dl and self.dl._stop):
            return False
        try:
            from .browser import BrowserFetcher
        except ImportError:
            return False
        self.dl.ip_failed = []
        self.write_log(f"Riprovo {len(failed)} file col browser interno (stessa rete del login)…")
        self.progress_text.setText(tr("Browser interno: {n} file…", n=len(failed)))
        delay = next((d for _f, _p, d in failed if d), None)
        items = [(f, f.url, p) for f, p, _d in failed]
        self.fetcher = BrowserFetcher(items, delay, self)
        self.fetcher.result.connect(self._browser_result)
        self.fetcher.finished.connect(self._browser_finished)
        self.fetcher.start()
        return True

    def _browser_result(self, f, ok: bool, info: str):
        if ok:
            self.n["failed"] = max(0, self.n["failed"] - 1)
            self.s_fail.set(self.n["failed"])
            self.write_log(f"✓ (browser) {info}")
            self.history.add(file_key(f.url), info, Path(info).stat().st_size if Path(info).exists() else None)
            self.on_event("done", {"file": f, "path": Path(info)})
        else:
            self.write_log(f"✗ (browser) {f.name}: {info}", logging.ERROR)

    def _browser_finished(self):
        self.fetcher = None
        self._download_complete()

    def _download_complete(self):
        # si può ancora scegliere altri file e scaricarli
        if getattr(self, "_paused_last", False):
            self._save_pending()
            for it in self.all_items():                  # restano spuntati solo quelli da finire
                if it.text(self.COL_STATUS) in self._finished_texts() and it.checkState(self.COL_NAME) == Qt.Checked:
                    self.tree.blockSignals(True)
                    it.setCheckState(self.COL_NAME, Qt.Unchecked)
                    self.tree.blockSignals(False)
        else:
            self._pending_path().unlink(missing_ok=True)
        self.set_state(self.REVIEW)
        self.update_selection()
        self.progress_text.setText(tr("Fatto: {a} scaricati, {b} già presenti, {c} errori",
                                       a=self.n["done"], b=self.n["skipped"], c=self.n["failed"]))
        if self.project:
            self.store.touch(self.project.id)
            self.panel.refresh(select_id=self.project.id)
        if not self.queue_active or not self.queue:
            self._finished_notice()
        self._queue_continue()

    # ---------- eventi dal motore ----------
    def _set_status(self, item: QTreeWidgetItem, text: str, color: str | None = None):
        item.setText(self.COL_STATUS, tr(text))
        tone = {OK: "ok", WARN: "warn", ERR: "err", self.colors["accent"]: "run"}.get(color or "", "")
        item.setData(self.COL_STATUS, Qt.UserRole + 1, tone)

    def on_event(self, kind: str, d: dict):
        f = d.get("file")
        item = self.items.get(f.url) if f is not None else None

        if kind == "page":
            self._pages_seen = getattr(self, "_pages_seen", 0) + 1
            self.progress_text.setText(tr("Analisi pagine… {p} viste, {n} file trovati",
                                          p=self._pages_seen, n=self.n["found"]))
        elif kind == "link":
            self.progress_text.setText(tr("Link {a} di {b}…", a=d["index"], b=d["total"]))
        elif kind == "found":
            if f.url in self.items:
                return
            old = f.url in self.known
            if not old and self.cfg.skip_downloaded:
                before = self.history.get(file_key(f.url))
                if before and Path(before).exists():
                    old = True
                    self.known[f.url] = before
            item = QTreeWidgetItem([f.name, f.subdir or "/", human_size(f.size), ""])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setTextAlignment(self.COL_SIZE, Qt.AlignRight | Qt.AlignVCenter)
            self.tree.blockSignals(True)
            item.setCheckState(self.COL_NAME, Qt.Unchecked if old else Qt.Checked)
            self.tree.blockSignals(False)
            item.setToolTip(self.COL_NAME, f.url)
            item.setData(self.COL_NAME, Qt.UserRole, f.url)
            item.setData(self.COL_SIZE, Qt.UserRole, old)
            if old and self.known.get(f.url) and Path(self.known[f.url]).exists():
                item.setData(self.COL_DIR, Qt.UserRole, self.known[f.url])
            self._set_status(item, "Già scaricato" if old else "Da scaricare")
            self.tree.addTopLevelItem(item)
            self._show_list(True)
            self.items[f.url] = item
            self.files[f.url] = f
            self.grid.add(f.url, f.name, not old)
            if self.grid_btn.isChecked() and kind_of(f.name) in ("image", "video"):
                self.request_preview(f)
            self.n["found"] = len(self.items)
            self.s_found.set(len(self.items))
            self.s_sel.set(self.selected_count())
            if getattr(self, "_streaming", False) and self.state == self.DOWNLOADING:
                self.to_download = len(self.items)
                self.bar.setRange(0, max(1, self.to_download))
            else:
                self.progress_text.setText(tr("Ricerca dei file… {n} trovati", n=len(self.items)))
            if self.thumbs.isChecked() and kind_of(f.name) in ("image", "video"):
                self.request_preview(f)
            if self.filter.text():
                self.apply_filter(self.filter.text())
        elif kind == "progress" and item:
            got, total = d["bytes"], d["total"]
            self.bytes_window += got - self.last_bytes.get(f.url, 0)
            self.last_bytes[f.url] = got
            now = time.monotonic()
            if now - self.last_paint.get(f.url, 0) > 0.15:
                self.last_paint[f.url] = now
                text = f"{got * 100 // total} %" if total else human_size(got)
                self._set_status(item, f"↓ {text}", self.colors["accent"])
                if total and item.text(self.COL_SIZE) == "—":
                    item.setText(self.COL_SIZE, human_size(total))
        elif kind in ("done", "skipped", "failed"):
            if self.project and f is not None:
                p = d.get("path")
                size = Path(p).stat().st_size if p and Path(p).exists() else None
                self.store.record(self.project.id, f.url, kind, Path(p).name if p else f.name,
                                  str(p or ""), size)
            self.n[kind] += 1
            {"done": self.s_done, "skipped": self.s_skip, "failed": self.s_fail}[kind].set(self.n[kind])
            completed = self.n["done"] + self.n["skipped"] + self.n["failed"]
            motion.animate_value(self.bar, completed)
            self._update_menubar()
            self.progress_text.setText(tr("{a} di {b} file", a=completed, b=getattr(self, "to_download", completed)))
            if item:
                text, color = {"done": ("Completato", OK), "skipped": ("Già presente", WARN),
                               "failed": ("Errore", ERR)}[kind]
                self._set_status(item, text, color)
                if "path" in d:
                    item.setData(self.COL_DIR, Qt.UserRole, str(d["path"]))
                    if item.text(self.COL_SIZE) == "—":
                        try:
                            item.setText(self.COL_SIZE, human_size(Path(d["path"]).stat().st_size))
                        except OSError:
                            pass
                    if Path(d["path"]).name != item.text(self.COL_NAME):
                        item.setText(self.COL_NAME, Path(d["path"]).name)
        elif kind == "filtered":
            if item:
                self._set_status(item, "Filtrato", WARN)
        elif kind == "retry" and item:
            self._set_status(item, tr("Nuovo tentativo {n}", n=d["attempt"]), WARN)
        elif kind == "duplicate" and item:
            self._set_status(item, "Doppione", WARN)
            item.setToolTip(self.COL_STATUS, tr("Uguale a: {p}", p=d.get("of", "")))
        elif kind == "waiting":
            why = d.get("reason", "")
            m = re.search(r"\((\d+:\d+)–(\d+:\d+)\)", why)
            why = tr("fuori dall'orario dei download ({a}–{b})", a=m.group(1), b=m.group(2)) if m else tr(why)
            self.progress_text.setText(tr("In pausa: {r}", r=why))
        elif kind == "disk_full":
            self.statusBar().showMessage(d.get("message", ""), 15000)
            self.toast(tr("Disco quasi pieno: download fermato"), "err", 8000)
        elif kind == "host_paused":
            self.statusBar().showMessage(d.get("message", ""), 10000)
        elif kind == "finished":
            self._paused_last = bool(d.get("paused"))
            msg = tr("Fatto: {a} scaricati, {b} già presenti, {c} errori", a=d["done"], b=d["skipped"], c=d["failed"])
            self.statusBar().showMessage(tr("In pausa") if self._paused_last else msg)

    def on_error(self, msg: str):
        self.write_log(msg, logging.ERROR)
        self.statusBar().showMessage(msg)
        self.progress_text.setText(msg)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)

    def _tick_speed(self):
        self.speed.setText(f"{human_size(self.bytes_window)}/s" if self.bytes_window else "")
        self.bytes_window = 0
        self._update_menubar()

    def _update_menubar(self):
        mb = getattr(self, "menubar_icon", None)
        if mb is None:
            return
        n = getattr(self, "n", {})
        done = n.get("done", 0) + n.get("skipped", 0) + n.get("failed", 0)
        paused = self.state == self.REVIEW and getattr(self, "_paused_last", False)
        mb.update(busy=self.state == self.DOWNLOADING, done=done, total=getattr(self, "to_download", 0) or 0,
                  paused=paused, speed=self.speed.text() if hasattr(self, "speed") else "",
                  scanning=self.state == self.SCANNING, found=n.get("found", 0))
        self._update_badge(done)

    def _update_badge(self, done: int):
        """Numero sull'icona nel Dock: file che mancano mentre scarica."""
        left = max(0, (getattr(self, "to_download", 0) or 0) - done) if self.state == self.DOWNLOADING else 0
        if left == getattr(self, "_badge", 0):
            return
        self._badge = left
        try:
            QGuiApplication.setBadgeNumber(left)
        except Exception:  # noqa: BLE001 - non c'è su tutte le piattaforme
            pass

    # ---------- trascina e rilascia ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasText() or e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        text = md.urls()[0].toString() if md.hasUrls() else md.text()
        if text.strip().endswith(".etmpl") and md.hasUrls() and md.urls()[0].isLocalFile():
            self.install_template(Path(md.urls()[0].toLocalFile()))
        else:
            self.url.add_link(text)

    def install_template(self, src: Path):
        dst_dir = plugins.user_templates_dir()
        dst_dir.mkdir(parents=True, exist_ok=True)
        (dst_dir / src.name).write_bytes(src.read_bytes())
        self.write_log(f"Template installato: {src.name}")
        self.reload_templates()

    def closeEvent(self, e):
        logging.getLogger("picfinder").removeHandler(self.log_handler)
        self.settings.setValue("dest", self.dest.text())
        downloading = self.state == self.DOWNLOADING
        if self.dl:
            if downloading:
                self.dl.pause()                 # 7: i pezzi restano, al prossimo avvio si riprende
            else:
                self.dl.stop()
        for t, _w in list(self._alive):
            if t.isRunning():
                t.quit()
                t.wait(5000)
        if downloading:
            self._save_pending()
        self.pool.clear()
        self.pool.waitForDone(5000)                   # anteprime in corso finiscono prima di chiudere
        super().closeEvent(e)


def _crash_log():
    """Se Qt o Python vanno in crash (Segmentation fault), il punto esatto finisce in log/crash.log."""
    import faulthandler
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        fh = open(d / "crash.log", "a", buffering=1)
        fh.write(f"\n=== avvio {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        faulthandler.enable(fh, all_threads=True)
        return fh
    except OSError:
        return None


class _App(QApplication):
    """18: il Mac passa all'app i link alldownload:// (segnalibro o estensione del browser).
    Niente installEventFilter sull'app: un filtro Python globale vede ogni evento di ogni oggetto
    (anche quelli interni del browser) e con PySide6 6.12 fa cadere l'app su macOS (SIGSEGV in
    Shiboken::Graph::identifyType). event() qui riceve solo gli eventi dell'app stessa."""
    on_link = None
    _pending: list[str] = []

    def event(self, ev):
        if ev.type() == QEvent.FileOpen:
            u = ev.url().toString() if not ev.url().isEmpty() else ev.file()
            if u:
                if self.on_link:
                    self.on_link(u)
                else:
                    self._pending.append(u)
                return True
        return super().event(ev)


def main() -> int:
    _crash_fh = _crash_log()  # noqa: F841
    # niente messaggi «js: …» delle pagine web nel Terminale (sono errori dei siti, non dell'app;
    # quelli utili finiscono già nel registro) e niente avvisi sui caratteri
    rules = os.environ.get("QT_LOGGING_RULES", "")
    os.environ["QT_LOGGING_RULES"] = ";".join(x for x in (rules, "js=false", "js.*=false", "qt.qpa.fonts=false",
                                                                  "qt.accessibility.table=false") if x)
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    try:
        from . import browser  # noqa: F401  (QtWebEngine va caricato prima di QApplication)
    except ImportError:
        pass
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or _App(sys.argv)
    try:                                   # colore scelto in Impostazioni di Sistema (prima di Fusion)
        role = getattr(QPalette.ColorRole, "Accent", QPalette.ColorRole.Highlight)
        theme.SYSTEM_ACCENT = app.palette().color(role).name()
    except Exception:
        theme.SYSTEM_ACCENT = None
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    from .i18n import set_language
    set_language(Settings.load().language)
    w = MainWindow()
    if isinstance(app, _App):
        app.on_link = w.receive_link
        for u in app._pending:
            QTimer.singleShot(500, lambda u=u: w.receive_link(u))
    for a in sys.argv[1:]:
        if a.lower().startswith("alldownload:"):
            QTimer.singleShot(500, lambda a=a: w.receive_link(a))
    w.show()
    code = app.exec()
    try:
        from . import browser
        browser.shutdown()
    except ImportError:
        pass
    del w
    # Chiusura "dura": evita il crash di QtWebEngine quando Python smonta tutto alla fine.
    logging.shutdown()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
