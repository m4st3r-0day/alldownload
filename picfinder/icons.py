"""Icone a linea (disegnate qui, 24x24, tratto 1.8): stesso stile su Mac, Windows e Linux.

icon("search", "#4F46E5") -> QIcon nitida anche su schermi Retina.
"""
from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# solo forme semplici: linee, cerchi, rettangoli
PATHS = {
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    "paste": '<rect x="6" y="4.5" width="12" height="16" rx="2"/><path d="M9.5 4.5V3.5h5v1M9.5 10h5M9.5 13.5h5M9.5 17h3"/>',
    "globe": '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 3.6 5.2 3.6 8.5s-1 6.1-3.6 8.5'
             'c-2.6-2.4-3.6-5.2-3.6-8.5s1-6.1 3.6-8.5"/>',
    "folder": '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.2h7a2 2 0 0 1 2 2v7.8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "folder-open": '<path d="M3.5 17.5v-10a2 2 0 0 1 2-2h4l2 2.2h6a2 2 0 0 1 2 2v1"/><path d="M3.5 17.5l2.4-6.3a1.5 1.5 0 0 1 1.4-1h13.2l-2.6 7.3a1.5 1.5 0 0 1-1.4 1H5a1.5 1.5 0 0 1-1.5-1z"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6'
            'M16.8 16.8l1.6 1.6M5.6 18.4l1.6-1.6M16.8 7.2l1.6-1.6"/><circle cx="12" cy="12" r="6.3"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1 8 0v2.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "refresh": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4h-4"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.8h5V7M6.5 7l.9 12.2a1.5 1.5 0 0 0 1.5 1.3h6.2a1.5 1.5 0 0 0 1.5-1.3L17.5 7"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    "pause": '<path d="M9 6v12M15 6v12"/>',
    "play": '<path d="M8 5.5v13l10-6.5z"/>',
    "chart": '<path d="M4.5 19.5h15M7.5 16v-5M12 16V7M16.5 16v-8"/>',
    "edit": '<path d="M5 19l1-4L15.5 5.5a2 2 0 0 1 3 3L9 18z"/><path d="M13.5 7.5l3 3"/>',
    "send": '<path d="M4.5 12l15-7-5 15-3-6z"/><path d="M11.5 14l3-3"/>',
    "download": '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
    "image": '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.6"/>'
             '<path d="M4 17l5-4.5 3.5 3 3-2.5 4.5 4"/>',
    "video": '<rect x="3.5" y="6" width="12.5" height="12" rx="2"/><path d="M16 10.5l4.5-2.5v8l-4.5-2.5"/>',
    "file": '<path d="M7 3.5h6.5l4.5 4.5v11a1.5 1.5 0 0 1-1.5 1.5h-9.5A1.5 1.5 0 0 1 5.5 19V5A1.5 1.5 0 0 1 7 3.5z"/>'
            '<path d="M13.5 3.5V8H18"/>',
    "bolt": '<path d="M13 3.5L5.5 13.5h6l-1 7 7.5-10h-6z"/>',
    "grid": '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    "list": '<path d="M9 7h11M9 12h11M9 17h11"/><circle cx="5" cy="7" r=".6"/><circle cx="5" cy="12" r=".6"/>'
            '<circle cx="5" cy="17" r=".6"/>',
    "layers": '<path d="M12 4l8.5 4.5L12 13 3.5 8.5z"/><path d="M3.5 12.5L12 17l8.5-4.5M3.5 16L12 20.5l8.5-4.5"/>',
    "network": '<circle cx="12" cy="5.5" r="2"/><circle cx="5.5" cy="18.5" r="2"/><circle cx="18.5" cy="18.5" r="2"/>'
               '<path d="M12 7.5v4M12 11.5l-5.2 5.4M12 11.5l5.2 5.4"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
    "terminal": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M7.5 9.5l3 2.5-3 2.5M12.5 15h4"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "chevron-down": '<path d="M6.5 9.5L12 15l5.5-5.5"/>',
    "chevron-up": '<path d="M6.5 14.5L12 9l5.5 5.5"/>',
    "chevron-left": '<path d="M14.5 6.5L9 12l5.5 5.5"/>',
    "chevron-right": '<path d="M9.5 6.5L15 12l-5.5 5.5"/>',
    "sliders": '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    "external": '<path d="M13.5 4.5h6v6M19.5 4.5L11 13M17.5 14v4a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 18V8'
                'A1.5 1.5 0 0 1 6 6.5h4"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5M12 7.8v.2"/>',
    "language": '<path d="M4 6h9M8.5 4v2M6 6c.5 3 2.5 5.5 5.5 7M11 6c-.6 3.3-2.7 6-6 7.5M13 20l3.5-8.5L20 20M14.2 17.2h4.6"/>',
}


def svg(name: str, color: str, stroke: float = 1.8) -> str:
    body = PATHS.get(name, PATHS["file"])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


@lru_cache(maxsize=256)
def icon(name: str, color: str = "#6B7280", size: int = 18) -> QIcon:
    r = QSvgRenderer(QByteArray(svg(name, color).encode()))
    ic = QIcon()
    for scale in (1, 2, 3):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, size * scale, size * scale))
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    return ic


_DIR = Path(tempfile.gettempdir()) / "picfinder-icons"


def icon_file(name: str, color: str) -> str:
    """Percorso di un .svg su disco (per i fogli di stile: QComboBox::down-arrow, ecc.)."""
    _DIR.mkdir(parents=True, exist_ok=True)
    p = _DIR / f"{name}-{color.lstrip('#')}.svg"
    if not p.exists():
        p.write_text(svg(name, color, 2.0), encoding="utf-8")
    return p.as_posix()


def app_icon() -> QIcon:
    """Icona dell'app: quadrato viola con un'immagine e la freccia di download."""
    s = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
         '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
         '<stop offset="0" stop-color="#6366F1"/><stop offset="1" stop-color="#4338CA"/></linearGradient></defs>'
         '<rect x="4" y="4" width="56" height="56" rx="14" fill="url(#g)"/>'
         '<rect x="13" y="15" width="28" height="24" rx="4.5" fill="none" stroke="white" stroke-width="3.2"/>'
         '<circle cx="21" cy="23" r="2.6" fill="white"/>'
         '<path d="M15.5 35l7-6 5 4 4-3 4 3.5" fill="none" stroke="white" stroke-width="3" '
         'stroke-linejoin="round" stroke-linecap="round"/>'
         '<circle cx="43" cy="43" r="11.5" fill="white"/>'
         '<path d="M43 36.5v11.5M38.2 43.5l4.8 4.8 4.8-4.8" fill="none" stroke="#4338CA" stroke-width="3.3" '
         'stroke-linecap="round" stroke-linejoin="round"/></svg>')
    r = QSvgRenderer(QByteArray(s.encode()))
    ic = QIcon()
    for size in (16, 32, 64, 128, 256, 512, 1024):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r.render(p, QRectF(0, 0, size, size))
        p.end()
        ic.addPixmap(pm)
    return ic
