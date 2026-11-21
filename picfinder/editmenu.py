"""Menu Modifica (Taglia, Copia, Incolla, Seleziona tutto) che funziona ovunque, anche nel browser interno.

Sul Mac le scorciatoie Cmd+C / Cmd+V passano dal menu Modifica: senza, nelle pagine web
del browser interno copia e incolla non funzionano.
"""
from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QWidget

from .i18n import tr

KINDS = (("cut", "Taglia", QKeySequence.Cut), ("copy", "Copia", QKeySequence.Copy),
         ("paste", "Incolla", QKeySequence.Paste), ("selectAll", "Seleziona tutto", QKeySequence.SelectAll))


def _web_view(w: QWidget | None):
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        return None
    while w is not None:
        if isinstance(w, QWebEngineView):
            return w
        w = w.parentWidget()
    return None


def do(kind: str) -> None:
    w = QApplication.focusWidget()
    view = _web_view(w)
    if view is not None:
        from PySide6.QtWebEngineCore import QWebEnginePage
        act = {"cut": QWebEnginePage.Cut, "copy": QWebEnginePage.Copy, "paste": QWebEnginePage.Paste,
               "selectAll": QWebEnginePage.SelectAll}[kind]
        view.page().triggerAction(act)
        return
    fn = getattr(w, kind, None) if w is not None else None
    if callable(fn):
        fn()


def add_actions(target, menu=None) -> list[QAction]:
    """Aggiunge le azioni a un menu (finestra principale) o direttamente a una finestra (browser)."""
    out = []
    for kind, text, key in KINDS:
        a = QAction(tr(text), target)
        a.setShortcut(QKeySequence(key))
        a.triggered.connect(lambda _=False, k=kind: do(k))
        (menu or target).addAction(a)
        out.append(a)
    return out
