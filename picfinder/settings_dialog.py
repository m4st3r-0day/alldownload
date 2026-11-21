"""Finestra Impostazioni (Cmd+,): sezioni a sinistra, pagina a destra."""
from __future__ import annotations

import asyncio
import copy

from PySide6.QtCore import QObject, QRect, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox,
    QApplication, QListWidgetItem, QScrollArea, QSizePolicy, QStackedWidget, QTableWidget, QTableWidgetItem,
    QStyle, QStyleOptionButton, QVBoxLayout, QWidget,
)

from .core import USER_AGENT, find_ffmpeg
from .proxies import ProxyPool, mask, parse_proxy_line
from .settings import ProxyEntry, Settings
from .i18n import LANGS, tr, translate_tree
from .icons import icon

OK, WARN, ERR, MUTED = "#16A34A", "#D97706", "#DC2626", "#6B7280"


class WrapCheckBox(QCheckBox):
    """Casella con testo che va a capo: i testi lunghi non vengono più tagliati a destra."""

    GAP = 7

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._text = text
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text
        self.updateGeometry()
        self.update()

    def _ind(self) -> int:
        return self.style().pixelMetric(QStyle.PM_IndicatorWidth, None, self) + self.GAP

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        r = self.fontMetrics().boundingRect(QRect(0, 0, max(40, w - self._ind()), 10000),
                                            Qt.TextWordWrap, self._text)
        return max(r.height(), self.fontMetrics().height()) + 4

    def sizeHint(self) -> QSize:
        w = min(self.fontMetrics().horizontalAdvance(self._text) + self._ind() + 4, 460)
        return QSize(w, self.heightForWidth(w))

    def minimumSizeHint(self) -> QSize:
        return QSize(140, self.fontMetrics().height() + 4)

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, _e):
        p = QPainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        opt.rect = QRect(0, 2, self._ind(), self.fontMetrics().height())
        self.style().drawControl(QStyle.CE_CheckBox, opt, p, self)
        p.setPen(self.palette().color(QPalette.WindowText) if self.isEnabled()
                 else self.palette().color(QPalette.Disabled, QPalette.WindowText))
        p.drawText(QRect(self._ind(), 2, self.width() - self._ind(), self.height() - 2),
                   Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop, self._text)
        p.end()


def _hint(text: str) -> QLabel:
    lb = QLabel(tr(text))
    lb.setWordWrap(True)
    lb.setObjectName("faint")
    lb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return lb


def _title(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("title")
    return lb


def _group(f: QFormLayout, text: str, first: bool = False):
    """Titoletto di gruppo dentro una pagina (es. Velocità, Cartelle)."""
    lb = QLabel(tr(text))
    lb.setObjectName("heading")
    lb.setContentsMargins(0, 2 if first else 16, 0, 2)
    f.addRow(lb)


class _TestWorker(QObject):
    done = Signal()

    def __init__(self, entries, test_url):
        super().__init__()
        self.entries, self.test_url = entries, test_url

    def run(self):
        try:
            asyncio.run(ProxyPool(self.entries, "fastest", self.test_url).test_all())
        finally:
            self.done.emit()


class SettingsDialog(QDialog):
    PAGES = (("Generale", "gear"), ("Download", "download"), ("Orari e limiti", "sliders"), ("Rete e proxy", "network"),
             ("Anteprime", "image"), ("Browser interno", "globe"), ("Registro", "terminal"))

    def __init__(self, parent, settings: Settings, colors: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Impostazioni")
        self.resize(900, 640)
        self.s = copy.deepcopy(settings)
        self.c = colors or {"muted": MUTED, "select": "#EEF0FF", "text": "#14161A", "hover": "#F2F4F7",
                            "accent_text": "#4338CA", "card": "#FFFFFF", "border": "#E5E7EB"}
        self.result_settings: Settings | None = None

        # come Impostazioni di Sistema: barra laterale a tutta altezza, pagina a destra senza riquadri
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 14, 10, 12)
        self.nav = QListWidget()
        self.nav.setFixedWidth(190)
        self.nav.setIconSize(QSize(16, 16))
        self.nav.setFocusPolicy(Qt.NoFocus)
        c = self.c
        self.nav.setStyleSheet(
            f"QListWidget{{border:none; background:transparent; font-size:13px;}}"
            f"QListWidget::item{{padding:5px 8px; border-radius:6px; margin:1px 0; color:{c['text']};}}"
            f"QListWidget::item:hover{{background:{c['hover']};}}"
            f"QListWidget::item:selected{{background:{c.get('accent', '#007AFF')}; color:white;}}")
        sl.addWidget(self.nav, 1)
        reset = QPushButton("Ripristina predefinite")
        reset.setObjectName("ghost")
        reset.clicked.connect(self.reset)
        sl.addWidget(reset)
        lay.addWidget(side)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 20, 16)
        right.setSpacing(12)
        self.pages = QStackedWidget()
        builders = (self._general, self._download, self._limits, self._network, self._previews, self._browser,
                    self._log)
        for (name, ic), build in zip(self.PAGES, builders):
            self.nav.addItem(QListWidgetItem(icon(ic, c["muted"], 16), name))
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
            inner = QWidget()
            il = QVBoxLayout(inner)
            il.setContentsMargins(28, 20, 8, 12)
            il.addWidget(build())
            il.addStretch()
            scroll.setWidget(inner)
            self.pages.addWidget(scroll)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        right.addWidget(self.pages, 1)

        buttons = QHBoxLayout()
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Salva")
        save.setObjectName("primary")
        save.setDefault(True)
        save.setMinimumWidth(90)
        save.clicked.connect(self.save)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        right.addLayout(buttons)
        lay.addLayout(right, 1)
        self.thread: QThread | None = None
        for sb in self.findChildren(QSpinBox):
            sb.setMaximumWidth(200)
        for cb in self.findChildren(QComboBox):
            cb.setMaximumWidth(420)
        translate_tree(self)

    # ---------- pagine ----------
    def _form(self, title: str) -> tuple[QWidget, QFormLayout]:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title(title))
        f = QFormLayout()
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        f.setRowWrapPolicy(QFormLayout.DontWrapRows)
        f.setHorizontalSpacing(18)
        f.setVerticalSpacing(10)
        v.addLayout(f)
        return w, f

    def _general(self):
        w, f = self._form("Generale")
        _group(f, "Aspetto", first=True)
        self.language = QComboBox()
        for k, t in LANGS.items():
            self.language.addItem(t, k)
        self.language.setCurrentIndex(max(0, self.language.findData(self.s.language)))
        f.addRow("Lingua", self.language)
        self.theme = QComboBox()
        for k, t in (("system", "Come il sistema"), ("light", "Chiaro"), ("dark", "Scuro")):
            self.theme.addItem(t, k)
        self.theme.setCurrentIndex(max(0, self.theme.findData(self.s.theme)))
        f.addRow("Tema", self.theme)
        f.addRow("", _hint("Lingua e tema cambiano subito, quando salvi."))
        _group(f, "Download")
        row = QHBoxLayout()
        self.dest = QLineEdit(self.s.dest_dir)
        b = QPushButton("Sfoglia…")
        b.clicked.connect(lambda: self._pick_dir(self.dest))
        row.addWidget(self.dest, 1)
        row.addWidget(b)
        f.addRow("Cartella predefinita", row)
        _group(f, "Quando finisce")
        self.notify = WrapCheckBox("Avvisami quando un download finisce")
        self.notify.setChecked(self.s.notify_when_done)
        f.addRow("", self.notify)
        self.open_done = WrapCheckBox("Apri la cartella quando un download finisce")
        self.open_done.setChecked(self.s.open_folder_when_done)
        f.addRow("", self.open_done)
        self.show_menubar = WrapCheckBox("Icona nella barra dei menu (avanzamento, pausa, stop)")
        self.show_menubar.setChecked(self.s.show_menubar)
        f.addRow("", self.show_menubar)
        _group(f, "Movimento")
        self.reduce_motion = WrapCheckBox("Riduci le animazioni")
        self.reduce_motion.setChecked(self.s.reduce_motion)
        f.addRow("", self.reduce_motion)
        f.addRow("", _hint("Vale anche «Riduci movimento» del sistema. Restano solo le dissolvenze."))
        _group(f, "Aggiornamenti")
        self.check_updates = WrapCheckBox("Controlla gli aggiornamenti all'avvio (una volta al giorno)")
        self.check_updates.setChecked(self.s.check_updates)
        f.addRow("", self.check_updates)
        self.gh_token = QLineEdit(self.s.github_token)
        self.gh_token.setEchoMode(QLineEdit.Password)
        self.gh_token.setPlaceholderText("Solo se il repo è privato")
        f.addRow("Token GitHub", self.gh_token)
        f.addRow("", _hint("Token «fine-grained» di sola lettura: Contents → Read-only, solo sul repo "
                           "alldownload. Resta sul tuo computer, mai nei log."))
        return w

    def _download(self):
        w, f = self._form("Download")
        _group(f, "Velocità", first=True)
        self.parallel = QSpinBox(minimum=1, maximum=16, value=self.s.parallel)
        f.addRow("File insieme (in totale)", self.parallel)
        self.per_host = QSpinBox(minimum=1, maximum=8, value=self.s.per_host)
        f.addRow("Per ogni server", self.per_host)
        f.addRow("", _hint("Se il template indica un limite per server, vale quello del template."))
        self.pauses = QComboBox()
        for key, text in (("full", "Come dice il template (più sicuro)"),
                          ("half", "Dimezzate"),
                          ("min", "Minime (meno di 1 s)")):
            self.pauses.addItem(text, key)
        self.pauses.setCurrentIndex(max(0, self.pauses.findData(self.s.pauses)))
        f.addRow("Pause tra un file e l'altro", self.pauses)
        f.addRow("", _hint("Più corte = più veloce, ma più rischio di blocco. Se un server dice "
                           "«troppe richieste», per lui si torna alle pause piene."))
        self.adaptive = WrapCheckBox("Connessioni adattive (partono piano, salgono se il server risponde bene)")
        self.adaptive.setChecked(self.s.adaptive)
        f.addRow("", self.adaptive)
        f.addRow("", _hint("Il limite imparato per ogni server si ricorda per la volta dopo."))
        self.segments = QSpinBox(minimum=1, maximum=8, value=self.s.segments)
        f.addRow("Pezzi insieme per i file grandi", self.segments)
        f.addRow("", _hint("Solo per file sopra 40 MB e se il server lo permette; contano nel limite per server."))
        self.http2 = WrapCheckBox("HTTP/2 (più file su una connessione)")
        self.http2.setChecked(self.s.http2)
        f.addRow("", self.http2)
        self.speed = QSpinBox(minimum=0, maximum=1_000_000, value=self.s.speed_limit_kbps, suffix=" KB/s",
                              specialValueText="Nessun limite", singleStep=256)
        f.addRow("Limite di velocità", self.speed)
        _group(f, "Errori")
        self.retries = QSpinBox(minimum=1, maximum=10, value=self.s.retries)
        f.addRow("Tentativi per file", self.retries)
        self.timeout = QSpinBox(minimum=5, maximum=300, value=self.s.timeout, suffix=" s")
        f.addRow("Attesa massima risposta", self.timeout)
        _group(f, "Cartelle")
        self.per_link = WrapCheckBox("Una cartella per ogni link (profilo, album, cartella)")
        self.per_link.setChecked(self.s.folder_per_link)
        f.addRow("", self.per_link)
        self.by_type = WrapCheckBox("Dentro, dividi in Foto, Video e Altri")
        self.by_type.setChecked(self.s.split_by_type)
        f.addRow("", self.by_type)
        f.addRow("", _hint("Esempio: AllDownload/mario/Foto. Le chat vanno in Chat/<id>/Foto."))
        _group(f, "Nomi e date dei file")
        self.name_pattern = QLineEdit(self.s.name_pattern)
        self.name_pattern.setPlaceholderText("Vuoto = nome originale · es. {profilo}_{data}_{n}")
        f.addRow("Modello del nome", self.name_pattern)
        self.name_preview = _hint("")
        f.addRow("", self.name_preview)
        f.addRow("", _hint("{nome} originale · {profilo} · {sito} · {data} del post · {ora} · {n} numero · "
                           "{id} codice del link. L'estensione resta quella vera."))
        self.name_pattern.textChanged.connect(self._preview_name)
        self._preview_name()
        self.file_dates = WrapCheckBox("Data del file = data del post (o quella del server)")
        self.file_dates.setChecked(self.s.file_dates)
        f.addRow("", self.file_dates)
        self.save_captions = WrapCheckBox("Salva la didascalia del post in un file .txt accanto")
        self.save_captions.setChecked(self.s.save_captions)
        f.addRow("", self.save_captions)
        _group(f, "Controlli")
        self.verify_files = WrapCheckBox("Controlla che foto e video siano interi (se no, li riscarica)")
        self.verify_files.setChecked(self.s.verify_files)
        f.addRow("", self.verify_files)
        self.reserve_gb = QSpinBox(minimum=0, maximum=500, value=self.s.reserve_gb, suffix=" GB")
        f.addRow("Lascia sempre libero", self.reserve_gb)
        f.addRow("", _hint("Prima di scaricare ti avviso se lo spazio non basta; durante, mi fermo "
                           "invece di riempire il disco."))
        _group(f, "Doppioni")
        self.skip_dl = WrapCheckBox("Non riscaricare i file già scaricati")
        self.skip_dl.setChecked(self.s.skip_downloaded)
        f.addRow("", self.skip_dl)
        f.addRow("", _hint("Vale anche se il sito cambia il link. Se cancelli un file dal disco, "
                           "la volta dopo lo riscarica."))
        self.conflicts = QComboBox()
        for k, t in (("same_size", "Salta se c'è già un file uguale (stessa dimensione)"),
                     ("do_not_save", "Non salvare se il nome esiste già"),
                     ("rename", "Salva con un nome nuovo (nome_001)"),
                     ("overwrite", "Sovrascrivi")):
            self.conflicts.addItem(t, k)
        self.conflicts.setCurrentIndex(max(0, self.conflicts.findData(self.s.default_conflicts)))
        f.addRow("Se il nome esiste già", self.conflicts)
        self.dup_images = QComboBox()
        for k, t in (("off", "Non controllare"), ("mark", "Segnala come «Doppione»"), ("move", "Sposta in _Doppioni")):
            self.dup_images.addItem(t, k)
        self.dup_images.setCurrentIndex(max(0, self.dup_images.findData(self.s.dup_images)))
        f.addRow("Foto uguali con nome diverso", self.dup_images)
        b = QPushButton("Dimentica i file già scaricati…")
        b.setToolTip("Svuota l'elenco dei file già scaricati")
        b.clicked.connect(self._clear_history)
        f.addRow("", b)
        return w

    def _preview_name(self, *_):
        from .postproc import render_name
        pat = self.name_pattern.text().strip()
        if not pat:
            self.name_preview.setText(tr("Esempio: {x}", x="IMG_4821.jpg"))
            return
        ex = render_name(pat, "IMG_4821.jpg", "https://onlyfans.com/123/mario", 7, "mario", 1773480000)
        self.name_preview.setText(tr("Esempio: {x}", x=ex))

    def _limits(self):
        w, f = self._form("Orari e limiti")
        _group(f, "Orari", first=True)
        self.sched = WrapCheckBox("Scarica solo dalle")
        self.sched.setChecked(self.s.schedule_enabled)
        from PySide6.QtWidgets import QTimeEdit
        from PySide6.QtCore import QTime
        self.sched_a = QTimeEdit(QTime.fromString(self.s.schedule_start, "H:mm"))
        self.sched_b = QTimeEdit(QTime.fromString(self.s.schedule_end, "H:mm"))
        for te in (self.sched_a, self.sched_b):
            te.setDisplayFormat("HH:mm")
            te.setMaximumWidth(110)
        row = QHBoxLayout()
        row.addWidget(self.sched)
        row.addWidget(self.sched_a)
        row.addWidget(QLabel("alle"))
        row.addWidget(self.sched_b)
        row.addStretch()
        f.addRow("", row)
        self.battery = WrapCheckBox("Pausa quando il computer va a batteria")
        self.battery.setChecked(self.s.pause_on_battery)
        f.addRow("", self.battery)
        _group(f, "Banda")
        self.share = QSpinBox(minimum=0, maximum=99, value=self.s.bandwidth_share, suffix=" %",
                              specialValueText="Tutta la linea", singleStep=10)
        f.addRow("Usa al massimo", self.share)
        f.addRow("", _hint("Misura la tua linea nei primi 20 secondi, poi lascia libero il resto per te."))
        _group(f, "Limiti dei siti")
        self.warn_req = QSpinBox(minimum=0, maximum=1_000_000, value=self.s.warn_requests, singleStep=500,
                                 specialValueText="Mai")
        row2 = QHBoxLayout()
        row2.addWidget(self.warn_req)
        row2.addWidget(QLabel("richieste al giorno allo stesso sito"))
        row2.addStretch()
        f.addRow("Avvisa dopo", row2)
        f.addRow("", _hint("Molti siti hanno un limite giornaliero: meglio fermarsi prima."))
        _group(f, "Progetti osservati")
        self.watch_min = QSpinBox(minimum=1, maximum=1440, value=self.s.watch_check_minutes, suffix=" min")
        f.addRow("Controlla ogni", self.watch_min)
        f.addRow("", _hint("Tasto destro su un progetto → «Controlla da solo». Si aggiorna solo quando l'app è libera."))
        return w

    def _network(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(_title("Rete e proxy"))
        top = QHBoxLayout()
        top.addWidget(QLabel("Usa i proxy"))
        self.mode = QComboBox()
        for k, t in (("off", "No, connessione diretta"), ("fastest", "Sì: il più veloce che risponde"),
                     ("first", "Sì: in ordine di lista")):
            self.mode.addItem(t, k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(self.s.proxy_mode)))
        top.addWidget(self.mode)
        top.addStretch()
        v.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Attivo", "Nome", "Indirizzo", "Stato"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(190)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setStyleSheet(f"QTableWidget{{border:1px solid {self.c['border']}; border-radius:8px;}}")
        v.addWidget(self.table)
        self._fill_proxies()

        row = QHBoxLayout()
        for text, ic, slot in (("Aggiungi…", "plus", self.add_proxy), ("Rimuovi", "trash", self.remove_proxy),
                               ("", "chevron-up", lambda: self.move_proxy(-1)),
                               ("", "chevron-down", lambda: self.move_proxy(1))):
            b = QPushButton(icon(ic, self.c["muted"], 15), (" " + text) if text else "")
            if not text:
                b.setToolTip("Sposta su" if ic == "chevron-up" else "Sposta giù")
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        b = QPushButton("Lista da link…")
        b.setToolTip("Scarica i proxy da un link (es. Webshare → Proxy list → Download)")
        b.clicked.connect(self.import_list)
        row.addWidget(b)
        self.test_btn = QPushButton("Prova tutti")
        self.test_btn.clicked.connect(self.test_proxies)
        row.addWidget(self.test_btn)
        v.addLayout(row)
        v.addWidget(_hint("Formato: http://host:porta, socks5://utente:password@host:porta, "
                          "oppure ip:porta:utente:password (Webshare)."))
        v.addWidget(_hint("Se un proxy non risponde si passa al prossimo. Se è il sito a rifiutare (403/429) "
                          "il proxy resta: l'app rallenta. Chi gestisce un proxy vede il traffico."))
        v.addSpacing(8)
        f = QFormLayout()
        f.setHorizontalSpacing(18)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.test_url = QLineEdit(self.s.proxy_test_url)
        f.addRow("Indirizzo per la prova", self.test_url)
        self.ua = QLineEdit(self.s.custom_user_agent)
        self.ua.setPlaceholderText(USER_AGENT)
        f.addRow("User-Agent (avanzato)", self.ua)
        v.addLayout(f)
        return w

    def _previews(self):
        w, f = self._form("Anteprime")
        self.auto_thumbs = WrapCheckBox("Mostra le miniature appena trova i file")
        self.auto_thumbs.setChecked(self.s.auto_thumbs)
        f.addRow("", self.auto_thumbs)
        f.addRow("", _hint("Ogni miniatura è una richiesta al sito: su siti severi meglio lasciarla spenta."))
        self.pv_max = QSpinBox(minimum=1, maximum=200, value=self.s.preview_max_mb, suffix=" MB")
        f.addRow("Immagini più grandi di così: niente anteprima", self.pv_max)
        row = QHBoxLayout()
        self.ffmpeg = QLineEdit(self.s.ffmpeg_path)
        found = find_ffmpeg(self.s.ffmpeg_path or None)
        self.ffmpeg.setPlaceholderText(found or "non trovato: brew install ffmpeg")
        b = QPushButton("Sfoglia…")
        b.clicked.connect(self._pick_ffmpeg)
        row.addWidget(self.ffmpeg, 1)
        row.addWidget(b)
        f.addRow("ffmpeg (fotogrammi video)", row)
        f.addRow("", _hint(("✓ " + tr("ffmpeg trovato: {p}", p=found)) if found else
                           "✗ ffmpeg non trovato: le anteprime dei video funzionano solo se il sito dà le miniature."))
        return w

    def _browser(self):
        w, f = self._form("Browser interno")
        self.auto_cont = QSpinBox(minimum=2, maximum=120, value=self.s.browser_auto_continue, suffix=" s")
        f.addRow("Nella coda, continua da solo dopo", self.auto_cont)
        f.addRow("", _hint("Quando aggiorni più progetti in coda, il browser si chiude da solo dopo questo tempo. "
                           "Per pulire login e cookie usa il bottone «Pulisci dati» dentro il browser."))
        return w

    def _log(self):
        w, f = self._form("Registro")
        self.verbose = WrapCheckBox("Registro dettagliato nella finestra")
        self.verbose.setChecked(self.s.verbose_log)
        f.addRow("", self.verbose)
        self.keep = QSpinBox(minimum=1, maximum=200, value=self.s.keep_logs, suffix=" file")
        f.addRow("Tieni gli ultimi", self.keep)
        f.addRow("", _hint("Il file di log è sempre completo, anche senza «dettagliato»."))
        return w

    # ---------- proxy ----------
    def _fill_proxies(self):
        self.table.setRowCount(0)
        for e in self.s.proxies:
            r = self.table.rowCount()
            self.table.insertRow(r)
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            on.setCheckState(Qt.Checked if e.enabled else Qt.Unchecked)
            self.table.setItem(r, 0, on)
            self.table.setItem(r, 1, QTableWidgetItem(e.name))
            addr = QTableWidgetItem(mask(e.url))      # la password non si vede
            addr.setData(Qt.UserRole, e.url)
            addr.setToolTip("Doppio clic per modificare (riscrivi anche la password)" if mask(e.url) != e.url else "")
            self.table.setItem(r, 2, addr)
            if e.ok is None:
                st, col = tr("non provato"), MUTED
            elif e.ok:
                st, col = f"✓ {e.latency_ms:.0f} ms", OK
            else:
                st, col = f"✗ {e.last_error[:40]}", ERR
            it = QTableWidgetItem(st)
            it.setFlags(Qt.ItemIsEnabled)
            it.setForeground(QColor(col))
            it.setToolTip(e.last_error)
            self.table.setItem(r, 3, it)

    def _read_proxies(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 2)
            text = (it.text() if it else "").strip()
            real = it.data(Qt.UserRole) if it else None
            url = real if real and text == mask(real) else text
            if not url:
                continue
            old = next((p for p in self.s.proxies if p.url == url), None)
            e = ProxyEntry(url=url, enabled=self.table.item(r, 0).checkState() == Qt.Checked,
                           name=self.table.item(r, 1).text().strip() if self.table.item(r, 1) else "")
            if old:
                e.latency_ms, e.ok, e.last_error = old.latency_ms, old.ok, old.last_error
            out.append(e)
        self.s.proxies = out

    def add_proxy(self):
        text, ok = QInputDialog.getMultiLineText(
            self, tr("Aggiungi proxy"), tr("Uno per riga (es. socks5://127.0.0.1:1080 oppure http://host:3128):"))
        if not ok:
            return
        self._read_proxies()
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            line = parse_proxy_line(line) or line
            if not any(p.url == line for p in self.s.proxies):
                self.s.proxies.append(ProxyEntry(line))
        self._fill_proxies()

    def _clear_history(self):
        from .projects import History
        h = History()
        n = h.count()
        if QMessageBox.question(self, tr("Doppioni"), tr("Dimentico {n} file già scaricati?", n=n) + "\n"
                                + tr("I file sul disco restano; potranno essere riscaricati.")) == QMessageBox.Yes:
            h.clear()
        h.close()

    def import_list(self):
        from .proxies import apply_list, fetch_list, mask_link
        cur = self.s.proxy_list_url
        text, ok = QInputDialog.getText(
            self, tr("Lista proxy da link"),
            tr("Link della lista (un proxy per riga, anche ip:porta:utente:password).") + "\n"
            + tr("Si riscarica da solo a ogni avvio. Vuoto = togli la lista."),
            QLineEdit.Password if cur else QLineEdit.Normal, cur)
        if not ok:
            return
        self._read_proxies()
        url = text.strip()
        if url and not url.lower().startswith(("http://", "https://")):
            # hanno incollato i proxy, non un link: li aggiungo come lista a mano
            added = [p for p in (parse_proxy_line(x) for x in url.split()) if p]
            for p in added:
                if not any(e.url == p for e in self.s.proxies):
                    self.s.proxies.append(ProxyEntry(p, name="a mano"))
            self._fill_proxies()
            QMessageBox.information(self, tr("Lista proxy"), tr("Non era un link: ho aggiunto {n} proxy dal testo.", n=len(added)))
            return
        self.s.proxy_list_url = url
        if not url:
            self.s.proxies = apply_list(self.s.proxies, [])
            self._fill_proxies()
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            urls = fetch_list(url)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tr("Lista proxy"), tr("Non riesco a scaricare la lista da {u}:", u=mask_link(url)) + f"\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.s.proxies = apply_list(self.s.proxies, urls)
        if self.mode.currentData() == "off" and urls:
            self.mode.setCurrentIndex(self.mode.findData("fastest"))
        self._fill_proxies()
        QMessageBox.information(self, tr("Lista proxy"), tr("Presi {n} proxy. Premi «Prova tutti» per vedere i più veloci.", n=len(urls)))

    def remove_proxy(self):
        self._read_proxies()
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            if r < len(self.s.proxies):
                del self.s.proxies[r]
        self._fill_proxies()

    def move_proxy(self, d: int):
        self._read_proxies()
        r = self.table.currentRow()
        if 0 <= r < len(self.s.proxies) and 0 <= r + d < len(self.s.proxies):
            p = self.s.proxies
            p[r], p[r + d] = p[r + d], p[r]
            self._fill_proxies()
            self.table.selectRow(r + d)

    def test_proxies(self):
        self._read_proxies()
        entries = [p for p in self.s.proxies if p.enabled]
        if not entries:
            QMessageBox.information(self, "Proxy", tr("Aggiungi e spunta almeno un proxy."))
            return
        self.test_btn.setEnabled(False)
        self.test_btn.setText(tr("Provo…"))
        self.thread = QThread()
        self.worker = _TestWorker(entries, self.test_url.text().strip() or Settings().proxy_test_url)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.done.connect(self.thread.quit)
        self.thread.finished.connect(self._tested)
        self.thread.start()

    def _tested(self):
        self._fill_proxies()
        self.test_btn.setEnabled(True)
        self.test_btn.setText(tr("Prova tutti"))

    # ---------- varie ----------
    def _pick_dir(self, edit: QLineEdit):
        d = QFileDialog.getExistingDirectory(self, tr("Scegli cartella"), edit.text())
        if d:
            edit.setText(d)

    def _pick_ffmpeg(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Dov'è ffmpeg?"), "/opt/homebrew/bin")
        if f:
            self.ffmpeg.setText(f)

    def reset(self):
        if QMessageBox.question(self, tr("Impostazioni"), tr("Ripristinare tutte le impostazioni predefinite?") + "\n"
                                + tr("La lista dei proxy resta.")) != QMessageBox.Yes:
            return
        keep = self.s.proxies
        self.result_settings = Settings(proxies=keep)
        self.accept()

    def save(self):
        self._read_proxies()
        s = self.s
        s.dest_dir = self.dest.text().strip() or s.dest_dir
        s.theme = self.theme.currentData()
        s.language = self.language.currentData()
        s.notify_when_done = self.notify.isChecked()
        s.open_folder_when_done = self.open_done.isChecked()
        s.reduce_motion = self.reduce_motion.isChecked()
        s.show_menubar = self.show_menubar.isChecked()
        s.check_updates = self.check_updates.isChecked()
        s.github_token = self.gh_token.text().strip()
        s.parallel, s.per_host = self.parallel.value(), self.per_host.value()
        s.pauses = self.pauses.currentData()
        s.retries, s.timeout = self.retries.value(), self.timeout.value()
        s.speed_limit_kbps = self.speed.value()
        s.default_conflicts = self.conflicts.currentData()
        s.folder_per_link = self.per_link.isChecked()
        s.split_by_type = self.by_type.isChecked()
        s.skip_downloaded = self.skip_dl.isChecked()
        s.adaptive, s.segments, s.http2 = self.adaptive.isChecked(), self.segments.value(), self.http2.isChecked()
        s.dup_images = self.dup_images.currentData()
        s.name_pattern = self.name_pattern.text().strip()
        s.file_dates = self.file_dates.isChecked()
        s.save_captions = self.save_captions.isChecked()
        s.verify_files = self.verify_files.isChecked()
        s.reserve_gb = self.reserve_gb.value()
        s.schedule_enabled = self.sched.isChecked()
        s.schedule_start = self.sched_a.time().toString("HH:mm")
        s.schedule_end = self.sched_b.time().toString("HH:mm")
        s.pause_on_battery = self.battery.isChecked()
        s.bandwidth_share = self.share.value()
        s.warn_requests = self.warn_req.value()
        s.watch_check_minutes = self.watch_min.value()
        s.proxy_mode = self.mode.currentData()
        s.proxy_test_url = self.test_url.text().strip() or Settings().proxy_test_url
        s.clamp()
        s.custom_user_agent = self.ua.text().strip()
        s.auto_thumbs = self.auto_thumbs.isChecked()
        s.preview_max_mb = self.pv_max.value()
        s.ffmpeg_path = self.ffmpeg.text().strip()
        s.browser_auto_continue = self.auto_cont.value()
        s.verbose_log = self.verbose.isChecked()
        s.keep_logs = self.keep.value()
        if s.proxy_mode != "off" and not s.enabled_proxies():
            QMessageBox.warning(self, "Proxy", tr("Hai scelto di usare i proxy ma la lista è vuota: "
                                                  "uso la connessione diretta."))
            s.proxy_mode = "off"
        self.result_settings = s
        self.accept()
