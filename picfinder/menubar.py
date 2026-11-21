"""Icona nella barra dei menu (Mac) / area di notifica (Windows, Linux).

Mostra quanto manca, e permette pausa, ripresa e stop senza aprire la finestra.
Sul Mac l'icona è «template» (solo forma): il sistema la colora da solo per il tema chiaro o scuro.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .i18n import tr


def _pen(col, w: float) -> QPen:
    pen = QPen(col, w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _draw(progress: float | None, paused: bool, dark_bg: bool) -> QIcon:
    """Freccia giù dentro un cerchio; se scarica, l'anello si riempie con l'avanzamento."""
    icon = QIcon()
    for scale in (1, 2):
        s = 18 * scale
        pm = QPixmap(s, s)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor("#000000") if sys.platform == "darwin" else QColor("#FFFFFF" if dark_bg else "#1D1D1F")
        r = QRectF(2, 2, 14, 14)
        if progress is None:
            p.setPen(QPen(col, 1.6))
            p.drawEllipse(r)
        else:
            faint = QColor(col)
            faint.setAlphaF(0.3)
            p.setPen(QPen(faint, 2))
            p.drawEllipse(r)
            p.setPen(_pen(col, 2))
            p.drawArc(r, 90 * 16, -int(360 * 16 * max(0.02, min(progress, 1.0))))
        p.setPen(_pen(col, 1.6))
        if paused:                                  # due barrette = pausa
            p.drawLine(QPointF(7.2, 6.5), QPointF(7.2, 11.5))
            p.drawLine(QPointF(10.8, 6.5), QPointF(10.8, 11.5))
        else:                                       # freccia giù
            p.drawLine(QPointF(9, 5.5), QPointF(9, 12))
            path = QPainterPath(QPointF(6.2, 9.4))
            path.lineTo(9, 12.2)
            path.lineTo(11.8, 9.4)
            p.drawPath(path)
        p.end()
        icon.addPixmap(pm)
    icon.setIsMask(sys.platform == "darwin")
    return icon


class MenuBarIcon(QObject):
    open_window = Signal()
    pause_toggled = Signal()
    stop_requested = Signal()
    open_folder = Signal()
    quit_requested = Signal()

    def __init__(self, parent, dark_bg: bool = False):
        super().__init__(parent)
        self.dark_bg = dark_bg
        self.tray = QSystemTrayIcon(parent)
        self.menu = QMenu()
        self.status = QAction(tr("Nessun download in corso"), self.menu)
        self.status.setEnabled(False)
        self.menu.addAction(self.status)
        self.menu.addSeparator()
        self.a_pause = self.menu.addAction(tr("Pausa"), self.pause_toggled.emit)
        self.a_stop = self.menu.addAction(tr("Interrompi"), self.stop_requested.emit)
        self.menu.addSeparator()
        self.menu.addAction(tr("Apri AllDownload"), self.open_window.emit)
        self.menu.addAction(tr("Apri cartella dei download"), self.open_folder.emit)
        self.menu.addSeparator()
        self.menu.addAction(tr("Esci"), self.quit_requested.emit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self._key = None
        self.update(busy=False)

    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self, on: bool = True):
        self.tray.setVisible(on and self.available())

    def _activated(self, reason):
        # sul Mac un clic apre il menu; su Windows/Linux il clic sinistro apre la finestra
        if sys.platform != "darwin" and reason == QSystemTrayIcon.Trigger:
            self.open_window.emit()

    def update(self, busy: bool, done: int = 0, total: int = 0, paused: bool = False, speed: str = "",
               scanning: bool = False, found: int = 0):
        if scanning:
            text = tr("Cerco file… {n} trovati", n=found)
            prog = None
        elif busy or paused:
            text = tr("{a} di {b} file", a=done, b=total) + (f" · {speed}" if speed and not paused else "")
            if paused:
                text = tr("In pausa") + " · " + text
            prog = (done / total) if total else 0.0
        else:
            text, prog = tr("Nessun download in corso"), None
        self.status.setText(text)
        self.tray.setToolTip(f"AllDownload — {text}")
        self.a_pause.setText(tr("Riprendi") if paused else tr("Pausa"))
        self.a_pause.setEnabled(busy or paused)
        self.a_stop.setEnabled(busy or scanning)
        key = (None if prog is None else round(prog * 40), paused)
        if key != self._key:                        # ridisegna solo se cambia qualcosa di visibile
            self._key = key
            self.tray.setIcon(_draw(prog, paused, self.dark_bg))

    def notify(self, title: str, msg: str, ms: int = 6000):
        if self.tray.isVisible():
            self.tray.showMessage(title, msg, QSystemTrayIcon.Information, ms)
