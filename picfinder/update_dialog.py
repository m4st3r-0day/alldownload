"""Finestra «È disponibile una nuova versione»: novità prima di aggiornare, poi installa e riavvia."""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QTextBrowser, QVBoxLayout)

from . import __version__, updater
from .i18n import tr, translate_tree
from .icons import app_icon

log = logging.getLogger("picfinder.update")


class _Bridge(QObject):
    found = Signal(object)            # UpdateInfo o None
    failed = Signal(str)
    progress = Signal(int, int)
    done = Signal(object)             # dict con l'esito dell'installazione


def check_async(token: str, on_found, on_error) -> _Bridge:
    """Controlla in un thread a parte (l'app non si blocca)."""
    b = _Bridge()
    b.found.connect(on_found)
    b.failed.connect(on_error)

    def run():
        try:
            b.found.emit(updater.check(token))
        except updater.UpdateError as e:
            b.failed.emit(tr(str(e)))
        except Exception as e:                       # rete assente, DNS, ...
            b.failed.emit(tr("Non riesco a contattare GitHub: {e}", e=type(e).__name__))
    threading.Thread(target=run, daemon=True).start()
    return b


class UpdateDialog(QDialog):
    skip = Signal(str)

    def __init__(self, parent, info: updater.UpdateInfo, token: str, busy: bool = False):
        super().__init__(parent)
        self.info, self.token, self.busy = info, token, busy
        self.mode = updater.install_mode()
        self.result_info: dict | None = None
        self.setWindowTitle(tr("Aggiornamento"))
        self.resize(560, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 18)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(14)
        ic = QLabel()
        ic.setPixmap(app_icon().pixmap(56, 56))
        ic.setAlignment(Qt.AlignTop)
        head.addWidget(ic)
        txt = QVBoxLayout()
        txt.setSpacing(3)
        t = QLabel(tr("È disponibile AllDownload {v}", v=info.version))
        t.setObjectName("title")
        txt.addWidget(t)
        when = f" · {tr('pubblicata il {d}', d=info.published)}" if info.published else ""
        sub = QLabel(tr("Tu hai la {v}", v=__version__) + when)
        sub.setObjectName("muted")
        txt.addWidget(sub)
        head.addLayout(txt, 1)
        lay.addLayout(head)

        lay.addSpacing(6)
        nl = QLabel(tr("Novità"))
        nl.setObjectName("heading")
        lay.addWidget(nl)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setObjectName("notes")
        self.notes.setMarkdown(info.notes.strip() or tr("Nessuna nota per questa versione."))
        lay.addWidget(self.notes, 1)

        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar(textVisible=False)
        self.bar.hide()
        lay.addWidget(self.bar)

        row = QHBoxLayout()
        self.b_skip = QPushButton(tr("Salta questa versione"), objectName="ghost")
        self.b_skip.clicked.connect(self._skip)
        self.b_later = QPushButton(tr("Più tardi"))
        self.b_later.clicked.connect(self.reject)
        self.b_go = QPushButton(objectName="primary")
        self.b_go.setDefault(True)
        self.b_go.setMinimumWidth(140)
        row.addWidget(self.b_skip)
        row.addStretch()
        row.addWidget(self.b_later)
        row.addWidget(self.b_go)
        lay.addLayout(row)

        can_frozen = self.mode == "frozen" and info.asset_url
        if self.mode == "source" or can_frozen:
            self.b_go.setText(tr("Aggiorna ora"))
            self.b_go.clicked.connect(self._install)
            if busy:
                self.status.setText(tr("C'è un download in corso: l'aggiornamento si installa adesso, "
                                       "il riavvio lo scegli tu alla fine."))
        else:
            self.b_go.setText(tr("Apri la pagina"))
            self.b_go.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(info.page_url)), self.accept()))
            self.status.setText(tr("Questa copia non si può aggiornare da sola: scarica la nuova versione dalla pagina."))
        translate_tree(self)

    # ------------------------------------------------------------------
    def _skip(self):
        self.skip.emit(self.info.version)
        self.reject()

    def _install(self):
        for b in (self.b_go, self.b_later, self.b_skip):
            b.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        self.status.setText(tr("Scarico la versione {v}…", v=self.info.version))
        br = self._bridge = _Bridge()
        br.progress.connect(self._progress)
        br.failed.connect(self._failed)
        br.done.connect(self._done)
        threading.Thread(target=self._work, args=(br,), daemon=True).start()

    def _work(self, br: _Bridge):
        i = self.info
        try:
            if self.mode == "frozen":
                data = updater.download(i.asset_url, self.token, br.progress.emit, binary_asset=True)
                if i.sums_url:
                    sums = updater.download(i.sums_url, self.token, binary_asset=True).decode("utf-8", "replace")
                    updater.verify_sha256(data, i.asset_name, sums)
                br.done.emit({"kind": "frozen", "data": data})
                return
            data = updater.download(i.source_url, self.token, br.progress.emit)
            br.progress.emit(-1, 0)
            res = updater.apply_source(data)
            if res["deps_changed"]:
                br.progress.emit(-2, 0)
                try:
                    updater.install_deps()
                except updater.UpdateError:
                    updater.restore_backup(res["backup"])
                    raise
            br.done.emit(dict(res, kind="source"))
        except updater.UpdateError as e:
            br.failed.emit(tr(str(e)))
        except Exception as e:
            log.exception("Aggiornamento non riuscito")
            br.failed.emit(tr("Aggiornamento non riuscito: {e}", e=f"{type(e).__name__}: {e}"))

    def _progress(self, done: int, total: int):
        if done == -1:
            self.bar.setRange(0, 0)
            self.status.setText(tr("Installo i file nuovi (copia di quelli vecchi in «backup»)…"))
        elif done == -2:
            self.status.setText(tr("Installo le librerie nuove (1-2 minuti)…"))
        elif total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            self.status.setText(tr("Scarico la versione {v}… {a} di {b} MB", v=self.info.version,
                                   a=f"{done / 1e6:.1f}", b=f"{total / 1e6:.1f}"))

    def _failed(self, msg: str):
        log.error("Aggiornamento: %s", msg)
        self.bar.hide()
        self.status.setText("⚠ " + tr(msg))
        self.status.setStyleSheet("color:#DC2626;")
        for b in (self.b_go, self.b_later, self.b_skip):
            b.setEnabled(True)

    def _done(self, res: dict):
        self.result_info = res
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        log.info("Aggiornamento a %s pronto (%s)", self.info.version, res.get("kind"))
        self.status.setStyleSheet("")
        self.status.setText(tr("Fatto. Riavvia AllDownload per usare la versione {v}.", v=self.info.version))
        try:
            self.b_go.clicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.b_go.setText(tr("Riavvia ora"))
        self.b_go.setEnabled(True)
        self.b_go.clicked.connect(self._restart)
        self.b_skip.hide()
        self.b_later.setText(tr("Riavvia dopo"))
        self.b_later.setEnabled(True)

    def _restart(self):
        res = self.result_info or {}
        if res.get("kind") == "frozen":
            updater.apply_frozen(res["data"], self.info.asset_name)
        else:
            updater.restart_source()
        self.accept()
        app = QApplication.instance()
        main = self.parent()
        if main is not None:
            main.close()                 # chiusura normale: salva lo stato e i download in sospeso
        app.quit()
