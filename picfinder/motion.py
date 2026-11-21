"""Movimento sobrio: animazioni brevi, interrompibili, senza rimbalzi.

Regole (dalla skill apple-design):
- durate corte (150–260 ms), curva ease-out: parte subito, si ferma morbida;
- ogni animazione riparte dal valore attuale, così si può interrompere;
- con «Riduci movimento» niente spostamenti: solo dissolvenze o cambi istantanei.
"""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt, QTimer,
                            QAbstractAnimation)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

FAST, NORMAL = 160, 240
_user_pref = False
_system_pref: bool | None = None


def set_user_reduce(on: bool) -> None:
    global _user_pref
    _user_pref = bool(on)


def _system_reduce() -> bool:
    global _system_pref
    if _system_pref is None:
        _system_pref = False
        if sys.platform == "darwin":
            try:
                out = subprocess.run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                                     capture_output=True, text=True, timeout=1).stdout.strip()
                _system_pref = out == "1"
            except Exception:
                pass
    return _system_pref


def reduce_motion() -> bool:
    return _user_pref or _system_reduce()


def _anim(target, prop: bytes, end, ms: int, curve=QEasingCurve.OutCubic) -> QPropertyAnimation:
    a = QPropertyAnimation(target, prop, target)
    a.setDuration(ms)
    a.setEasingCurve(curve)
    a.setEndValue(end)
    return a


def animate_value(bar, value: int) -> None:
    """Barra di avanzamento che scorre al nuovo valore invece di saltare."""
    old = getattr(bar, "_value_anim", None)
    if old is not None:
        old.stop()
    if reduce_motion() or bar.maximum() <= bar.minimum() or value < bar.value():
        bar.setValue(value)
        return
    a = _anim(bar, b"value", value, NORMAL)
    bar._value_anim = a
    a.start()


def set_open(widget: QWidget, show: bool) -> None:
    """Apre/chiude un pannello facendo scorrere l'altezza. Interrompibile."""
    old = getattr(widget, "_open_anim", None)
    if old is not None and old.state() == QAbstractAnimation.Running:
        old.stop()
    if reduce_motion() or not widget.window().isVisible():
        widget.setMaximumHeight(16777215)
        widget.setVisible(show)
        return
    full = widget.sizeHint().height()
    if show:
        start = 0 if not widget.isVisible() else widget.height()
        widget.setMaximumHeight(start)
        widget.setVisible(True)
        a = _anim(widget, b"maximumHeight", full, NORMAL)
        a.finished.connect(lambda: widget.setMaximumHeight(16777215))
    else:
        widget.setMaximumHeight(widget.height())
        a = _anim(widget, b"maximumHeight", 0, FAST, QEasingCurve.InOutCubic)
        a.finished.connect(lambda: (widget.setVisible(False), widget.setMaximumHeight(16777215)))
    widget._open_anim = a
    a.start()


class Toast(QWidget):
    """Avviso breve in basso al centro della finestra. Sparisce da solo; un clic lo chiude."""

    def __init__(self, parent: QWidget, colors: dict):
        super().__init__(parent)
        self.colors = colors
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 9, 16, 9)
        lay.setSpacing(9)
        self.dot = QLabel(objectName="toastDot")
        self.dot.setFixedSize(8, 8)
        self.text = QLabel(objectName="toastText")
        lay.addWidget(self.dot)
        lay.addWidget(self.text)
        self.fx = QGraphicsOpacityEffect(self)
        self.fx.setOpacity(0.0)
        self.setGraphicsEffect(self.fx)
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self.dismiss)
        self.group: QParallelAnimationGroup | None = None
        self.hide()

    def mousePressEvent(self, e):
        self.dismiss()

    def _place(self, lift: int = 0) -> QPoint:
        p = self.parentWidget()
        self.adjustSize()
        bottom = p.height() - 46
        return QPoint((p.width() - self.width()) // 2, bottom - self.height() + lift)

    def show_message(self, text: str, tone: str = "ok", ms: int = 3200) -> None:
        dot = {"ok": "#16A34A", "warn": "#D97706", "err": "#DC2626"}.get(tone, self.colors["accent"])
        self.dot.setStyleSheet(f"background:{dot}; border-radius:4px;")
        self.text.setText(text)
        self._run(True)
        self.timer.start(ms if tone != "err" else ms * 2)

    def dismiss(self) -> None:
        if self.isVisible():
            self._run(False)

    def _run(self, show: bool) -> None:
        if self.group:
            self.group.stop()
        end_pos = self._place()
        if show:
            self.raise_()
            self.show()
            if not (self.fx.opacity() > 0):
                self.move(self._place(0 if reduce_motion() else 8))
        g = QParallelAnimationGroup(self)
        g.addAnimation(_anim(self.fx, b"opacity", 1.0 if show else 0.0, NORMAL if show else FAST))
        if not reduce_motion():
            g.addAnimation(_anim(self, b"pos", end_pos if show else self._place(6), NORMAL if show else FAST))
        if not show:
            g.finished.connect(self.hide)
        self.group = g
        g.start()

    def reposition(self) -> None:
        if self.isVisible():
            self.move(self._place())
