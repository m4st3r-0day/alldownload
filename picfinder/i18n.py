"""Lingue dell'interfaccia: italiano (testo di partenza) e inglese.

- tr("Testo {n}", n=3): traduce e riempie i segnaposto.
- translate_tree(widget): traduce i testi fissi già messi nei widget (etichette, bottoni,
  suggerimenti, tendine, schede, intestazioni, menu). Così il codice resta leggibile in italiano.
Il registro tecnico (log) resta in italiano.
"""
from __future__ import annotations

LANGS = {"system": "Come il sistema", "it": "Italiano", "en": "English"}
_lang = "it"


def set_language(code: str) -> str:
    """code: system | it | en. Restituisce la lingua usata davvero."""
    global _lang
    if code == "system":
        try:
            from PySide6.QtCore import QLocale
            code = "it" if QLocale.system().name().lower().startswith("it") else "en"
        except Exception:  # noqa: BLE001
            code = "it"
    _lang = code if code in ("it", "en") else "it"
    return _lang


def language() -> str:
    return _lang


def tr(text: str, **kw) -> str:
    if _lang == "en":
        from .lang_en import EN
        text = EN.get(text, text)
    return text.format(**kw) if kw else text


_REV: dict | None = None


def _t(s: str) -> str:
    """Testo fisso nella lingua attuale. Funziona nei due sensi, così la lingua cambia senza riavviare."""
    if not s:
        return s
    from .lang_en import EN
    if _lang == "en":
        return EN.get(s, s)
    global _REV
    if _REV is None:
        _REV = {}
        for k, v in EN.items():
            _REV.setdefault(v, k)
    return _REV.get(s, s)


def translate_tree(root) -> None:
    """Traduce i testi fissi di una finestra e di tutti i suoi figli nella lingua attuale."""
    if root is None:
        return
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit, QListWidget,
                                   QMenu, QPlainTextEdit, QTabWidget, QTableWidget, QTreeWidget, QWidget)
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        QWebEngineView = None
    skip = set()
    if QWebEngineView is not None:
        for v in root.findChildren(QWebEngineView):          # dentro la pagina web non si tocca niente
            skip.update(id(c) for c in v.findChildren(QWidget))
            skip.add(id(v))
    widgets = [w for w in [root] + root.findChildren(QWidget) if id(w) not in skip]
    for w in widgets:
        if w.windowTitle():
            w.setWindowTitle(_t(w.windowTitle()))
        if w.toolTip():
            w.setToolTip(_t(w.toolTip()))
        if isinstance(w, (QLabel, QAbstractButton)) and not isinstance(w, QComboBox):
            if w.text():
                w.setText(_t(w.text()))
        if isinstance(w, QGroupBox) and w.title():
            w.setTitle(_t(w.title()))
        if isinstance(w, (QLineEdit, QPlainTextEdit)) and w.placeholderText():
            w.setPlaceholderText(_t(w.placeholderText()))
        if isinstance(w, QComboBox):
            for i in range(w.count()):
                w.setItemText(i, _t(w.itemText(i)))
            if w.isEditable() and w.lineEdit() and w.lineEdit().placeholderText():
                w.lineEdit().setPlaceholderText(_t(w.lineEdit().placeholderText()))
        if isinstance(w, QTabWidget):
            for i in range(w.count()):
                w.setTabText(i, _t(w.tabText(i)))
        if isinstance(w, QTreeWidget):
            h = w.headerItem()
            for i in range(h.columnCount()):
                h.setText(i, _t(h.text(i)))
        if isinstance(w, QTableWidget):
            for i in range(w.columnCount()):
                it = w.horizontalHeaderItem(i)
                if it:
                    it.setText(_t(it.text()))
        if isinstance(w, QListWidget):
            for i in range(w.count()):
                w.item(i).setText(_t(w.item(i).text()))
        if isinstance(w, QMenu):
            w.setTitle(_t(w.title()))
        for a in w.actions():
            if a.text():
                a.setText(_t(a.text()))
            if a.toolTip() and a.toolTip() != a.text():
                a.setToolTip(_t(a.toolTip()))
            if a.menu():
                a.menu().setTitle(_t(a.menu().title()))
                for b in a.menu().actions():
                    if b.text():
                        b.setText(_t(b.text()))
