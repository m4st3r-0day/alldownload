"""Prove della finestra principale senza schermo (offscreen): si apre, cambia stato, lingua e tema, griglia."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from picfinder import i18n  # noqa: E402
from picfinder.core import RemoteFile  # noqa: E402
from picfinder.projects import Store  # noqa: E402


@pytest.fixture
def win(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    from picfinder import gui
    monkeypatch.setattr(gui.MainWindow, "check_updates", lambda self, auto=True: None)
    w = gui.MainWindow(store=Store(tmp_path / "p.db"))
    w.cfg.show_menubar = False
    yield w
    w.store.close()
    w.deleteLater()
    app.processEvents()
    i18n.set_language("it")


def test_window_states(win):
    for s in (win.SCANNING, win.REVIEW, win.DOWNLOADING, win.IDLE):
        win.set_state(s)
        assert win.state == s


def test_language_and_theme_switch_live(win):
    win.cfg.language = "en"
    win.cfg.theme = "dark"
    win.apply_look()
    titles = [m.title() for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu()))]
    assert "Tools" in titles
    dark_bg = win.colors["bg"]
    win.cfg.language = "it"
    win.cfg.theme = "light"
    win.apply_look()
    assert "Strumenti" in [m.title() for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu()))]
    assert win.colors["bg"] != dark_bg


def test_grid_follows_list(win):
    f = RemoteFile(url="https://x.example/a.jpg", name="a.jpg")
    win.files[f.url] = f
    win.grid.add(f.url, f.name, True)
    win.toggle_grid(True)
    assert win.view_stack.currentIndex() == 1
    win.grid.set_checked(f.url, False)
    assert win.grid.urls() == [f.url]
    win.grid.clear_all()
    assert win.grid.urls() == []
    win.toggle_grid(False)
    assert win.view_stack.currentIndex() == 0


def test_badge_only_while_downloading(win, monkeypatch):
    seen = []
    from picfinder import gui
    monkeypatch.setattr(gui.QGuiApplication, "setBadgeNumber", staticmethod(lambda n: seen.append(n)))
    win.to_download = 10
    win.state = win.DOWNLOADING
    win._update_badge(3)
    win.state = win.REVIEW
    win._update_badge(10)
    assert seen == [7, 0]


def test_library_dialog_opens(win, tmp_path):
    from picfinder.library import LibraryDialog
    d = LibraryDialog(win, tmp_path / "nulla.db", str(tmp_path), lambda n: "1 KB")
    assert d.list.topLevelItemCount() == 0
    d.deleteLater()
