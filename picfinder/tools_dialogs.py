"""Finestre di strumenti: statistiche (20), editor dei template (22), «Manda ad AllDownload» (18)."""
from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QUrl

from . import plugins
from .i18n import tr, translate_tree


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def _table(headers: list[str], rows: list[tuple]) -> QTableWidget:
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            it = QTableWidgetItem(str(v))
            if c:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, c, it)
    return t


# ---------------------------------------------------------------- 20: statistiche
class StatsDialog(QDialog):
    def __init__(self, parent, history):
        super().__init__(parent)
        self.setWindowTitle(tr("Statistiche"))
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)
        st = history.stats()
        cards = QHBoxLayout()
        for title, value in ((tr("File scaricati"), f"{st['files']:,}".replace(",", ".")),
                             (tr("Spazio usato"), _size(st["size"])),
                             (tr("Ultimi 7 giorni"), f"{st['week']:,}".replace(",", ".")),
                             (tr("Siti diversi"), str(len(st["by_site"])))):
            box = QWidget()
            box.setObjectName("statcard")
            v = QVBoxLayout(box)
            v.setContentsMargins(14, 10, 14, 10)
            a = QLabel(value)
            f = a.font()
            f.setPointSizeF(f.pointSizeF() * 1.6)
            f.setBold(True)
            a.setFont(f)
            b = QLabel(title)
            b.setObjectName("muted")
            v.addWidget(a)
            v.addWidget(b)
            cards.addWidget(box)
        lay.addLayout(cards)
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(_table([tr("Sito"), tr("File"), tr("Spazio")],
                           [(s, n, _size(z)) for s, n, z in st["by_site"][:200]]), tr("Per sito"))
        tabs.addTab(_table([tr("Sito"), tr("Richieste oggi")], history.requests_by_site()), tr("Richieste oggi"))
        tabs.addTab(_table([tr("Sito"), tr("Errori (30 giorni)")], history.failures_by_site()), tr("Errori"))
        try:
            from .netpolicy import SiteMemory
            mem = SiteMemory().data
            rows = [(h, v.get("limit", "?"), v.get("throttled", 0),
                     time.strftime("%d/%m %H:%M", time.localtime(v["last_throttle"])) if v.get("last_throttle") else "—")
                    for h, v in sorted(mem.items())]
        except Exception:  # noqa: BLE001
            rows = []
        tabs.addTab(_table([tr("Server"), tr("Connessioni"), tr("«Troppe richieste»"), tr("Ultima volta")], rows),
                    tr("Limiti imparati"))
        lay.addWidget(tabs, 1)
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        translate_tree(self)


# ---------------------------------------------------------------- 22: editor dei template
class _TestWorker(QObject):
    done = Signal(list, str)

    def __init__(self, text: str, url: str):
        super().__init__()
        self.text, self.url = text, url

    def run(self):
        from .core import Downloader
        from .etmpl import EtmplPlugin, Template
        lines: list[str] = []

        class H(logging.Handler):
            def emit(self, rec):
                lines.append(self.format(rec))
        h = H()
        h.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        h.setLevel(logging.DEBUG)
        lg = logging.getLogger("picfinder")
        old = lg.level
        lg.addHandler(h)
        lg.setLevel(logging.DEBUG)
        files: list = []
        try:
            tmp = Path(tempfile.mkdtemp()) / "prova.etmpl"
            tmp.write_text(self.text, encoding="utf-8")
            plugin = EtmplPlugin(Template.load(tmp))
            if plugin.t.needs_browser():
                lines.append(tr("Questo template usa il browser interno: provalo dalla finestra principale."))
            else:
                dl = Downloader(tempfile.mkdtemp(), None)
                files = asyncio.run(dl.scan(self.url, plugin=plugin))
        except Exception as e:  # noqa: BLE001
            lines.append(f"ERRORE  {e}")
        finally:
            lg.removeHandler(h)
            lg.setLevel(old)
        self.done.emit(files, "\n".join(lines[-3000:]))


class TemplateEditor(QDialog):
    saved = Signal()

    def __init__(self, parent, path: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Editor dei template"))
        self.resize(1100, 720)
        self.path = path
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        top = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.addItem(tr("— nuovo template —"), "")
        for d in plugins.template_dirs():
            for f in sorted(d.glob("*.etmpl")) if d.is_dir() else []:
                self.pick.addItem(f"{f.stem}  ({tr('tuo') if d == plugins.user_templates_dir() else tr('incluso')})",
                                  str(f))
        self.pick.currentIndexChanged.connect(self._load_selected)
        top.addWidget(QLabel(tr("Template")))
        top.addWidget(self.pick, 1)
        b_open = QPushButton(tr("Apri file…"))
        b_open.clicked.connect(self._open_file)
        top.addWidget(b_open)
        lay.addLayout(top)

        split = QSplitter(Qt.Vertical)
        self.edit = QPlainTextEdit()
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.Monospace)
        self.edit.setFont(mono)
        self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.edit.setPlaceholderText(tr("[Settings]\nManualLogin=False\n[TargetFiles]\nFile000=*.jpg\n[StartingURLTemplates]\nURL000=sito\\.com/album/"))
        split.addWidget(self.edit)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 6, 0, 0)
        trow = QHBoxLayout()
        self.test_url = QLineEdit(placeholderText=tr("Link di prova"))
        self.test_btn = QPushButton(tr("Prova"))
        self.test_btn.setObjectName("primary")
        self.test_btn.clicked.connect(self.run_test)
        trow.addWidget(self.test_url, 1)
        trow.addWidget(self.test_btn)
        bl.addLayout(trow)
        self.result = QPlainTextEdit(readOnly=True, objectName="log")
        self.result.setLineWrapMode(QPlainTextEdit.NoWrap)
        bl.addWidget(self.result, 1)
        split.addWidget(bottom)
        split.setSizes([430, 250])
        lay.addWidget(split, 1)

        row = QHBoxLayout()
        self.info = QLabel("")
        self.info.setObjectName("muted")
        row.addWidget(self.info, 1)
        save_as = QPushButton(tr("Salva come…"))
        save_as.clicked.connect(lambda: self.save(ask=True))
        save = QPushButton(tr("Salva"))
        save.setObjectName("primary")
        save.clicked.connect(lambda: self.save(ask=False))
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        row.addWidget(save_as)
        row.addWidget(save)
        lay.addLayout(row)
        self.thread: QThread | None = None
        if path:
            i = self.pick.findData(str(path))
            if i >= 0:
                self.pick.setCurrentIndex(i)
            else:
                self._load(path)
        translate_tree(self)

    def _load_selected(self):
        p = self.pick.currentData()
        if p:
            self._load(Path(p))
        else:
            self.path = None
            self.edit.clear()

    def _load(self, p: Path):
        self.path = p
        raw = p.read_bytes()
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                self.edit.setPlainText(raw.decode(enc))
                break
            except UnicodeDecodeError:
                continue
        self.info.setText(str(p))

    def _open_file(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Apri template"), str(Path.home()), "EPF (*.etmpl)")
        if f:
            self._load(Path(f))

    def save(self, ask: bool):
        user_dir = plugins.user_templates_dir()
        user_dir.mkdir(parents=True, exist_ok=True)
        target = self.path
        if ask or target is None or user_dir not in target.parents:
            # i template inclusi non si modificano: si salva una copia tra i tuoi
            name = (target.name if target else "nuovo.etmpl")
            f, _ = QFileDialog.getSaveFileName(self, tr("Salva template"), str(user_dir / name), "EPF (*.etmpl)")
            if not f:
                return
            target = Path(f)
        try:
            from .etmpl import Template
            tmp = Path(tempfile.mkdtemp()) / "check.etmpl"
            tmp.write_text(self.edit.toPlainText(), encoding="utf-8")
            Template.load(tmp)
        except Exception as e:  # noqa: BLE001
            if QMessageBox.question(self, tr("Template"), tr("Il template ha un errore:") + f"\n{e}\n\n"
                                    + tr("Salvo lo stesso?")) != QMessageBox.Yes:
                return
        target.write_text(self.edit.toPlainText(), encoding="utf-8")
        self.path = target
        self.info.setText(tr("Salvato: {p}", p=target))
        self.saved.emit()

    def run_test(self):
        url = self.test_url.text().strip()
        if not url or self.thread is not None:
            return
        self.result.setPlainText(tr("Provo…"))
        self.test_btn.setEnabled(False)
        self.thread = QThread(self)
        self.worker = _TestWorker(self.edit.toPlainText(), url)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.done.connect(self._tested, Qt.QueuedConnection)
        self.worker.done.connect(self.thread.quit)
        self.thread.start()

    def _tested(self, files: list, log_text: str):
        self.thread.wait(2000)
        self.thread = None
        self.test_btn.setEnabled(True)
        head = tr("{n} file trovati", n=len(files)) + "\n" + "\n".join(
            f"  {f.subdir + '/' if f.subdir else ''}{f.name}" for f in files[:300])
        self.result.setPlainText(head + "\n\n—— " + tr("registro") + " ——\n" + log_text)


# ---------------------------------------------------------------- 18: manda ad AllDownload dal browser
BOOKMARKLET = "javascript:location.href='alldownload://add?url='+encodeURIComponent(location.href)"


def extension_dir() -> Path:
    import sys
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for p in (base / "extension", Path(__file__).resolve().parent.parent / "extension"):
        if p.is_dir():
            return p
    return base / "extension"


class SendToDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(tr("Manda ad AllDownload dal browser"))
        self.resize(620, 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        t = QLabel(tr("Manda la pagina che stai guardando ad AllDownload con un clic."))
        t.setObjectName("heading")
        lay.addWidget(t)
        a = QLabel(tr("Safari, Chrome, Firefox: crea un segnalibro e come indirizzo incolla questo testo. "
                      "Quando sei su una pagina, clicca il segnalibro: il link arriva nell'app."))
        a.setWordWrap(True)
        lay.addWidget(a)
        bm = QLineEdit(BOOKMARKLET)
        bm.setReadOnly(True)
        row = QHBoxLayout()
        row.addWidget(bm, 1)
        cp = QPushButton(tr("Copia"))
        cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(BOOKMARKLET))
        row.addWidget(cp)
        lay.addLayout(row)
        lay.addSpacing(8)
        b = QLabel(tr("Chrome, Edge, Brave: estensione con il menu «Manda ad AllDownload» (anche sui link). "
                      "Vai su chrome://extensions, accendi «Modalità sviluppatore», «Carica estensione non pacchettizzata» "
                      "e scegli questa cartella."))
        b.setWordWrap(True)
        lay.addWidget(b)
        op = QPushButton(tr("Apri la cartella dell'estensione"))
        op.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(extension_dir()))))
        lay.addWidget(op, 0, Qt.AlignLeft)
        note = QLabel(tr("Funziona con l'app installata (AllDownload.app): il Mac le passa i link alldownload://."))
        note.setObjectName("faint")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()
        close = QPushButton(tr("Chiudi"))
        close.clicked.connect(self.accept)
        r2 = QHBoxLayout()
        r2.addStretch()
        r2.addWidget(close)
        lay.addLayout(r2)
        translate_tree(self)


def parse_send_url(raw: str) -> str | None:
    """alldownload://add?url=<link> → link."""
    from urllib.parse import parse_qs, unquote, urlsplit
    if not raw or not raw.lower().startswith("alldownload:"):
        return None
    q = parse_qs(urlsplit(raw).query)
    link = (q.get("url") or [""])[0]
    if not link:
        rest = raw.split(":", 1)[1].lstrip("/")
        link = unquote(rest.split("add/", 1)[-1]) if rest else ""
    return link if link.startswith(("http://", "https://")) else None
