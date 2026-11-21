import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from picfinder.menubar import MenuBarIcon, _draw  # noqa: E402


def test_icona_e_menu():
    app = QApplication.instance() or QApplication([])
    for args in ((None, False, False), (0.5, False, True), (1.0, True, False)):
        assert not _draw(*args).isNull()
    w = QWidget()
    mb = MenuBarIcon(w)
    mb.update(busy=True, done=3, total=10, speed="2 MB/s")
    assert "3" in mb.status.text() and "10" in mb.status.text()
    assert mb.a_pause.isEnabled() and mb.a_stop.isEnabled()
    mb.update(busy=False, paused=True, done=3, total=10)
    assert mb.a_pause.text() in ("Riprendi", "Resume")
    mb.update(busy=False)
    assert not mb.a_stop.isEnabled()
    app.processEvents()
