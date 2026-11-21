"""Browser interno: cattura vera con QtWebEngine su un sito locale."""
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

try:
    from PySide6.QtCore import QCoreApplication, Qt
    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    from picfinder import browser
    from PySide6.QtWidgets import QApplication
except ImportError:                                   # QtWebEngine non installato
    browser = None

SITE = Path(__file__).parent / "sito_prova"


@pytest.mark.skipif(browser is None, reason="QtWebEngine non disponibile")
def test_cattura_intestazioni_risposte_cookie_e_pagina():
    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length", 0)))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":1}')

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=str(SITE)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app = QApplication.instance() or QApplication([])
    try:
        s = browser.open_browser(None, f"http://127.0.0.1:{srv.server_port}/index.html", auto_continue=2)
    finally:
        srv.shutdown()
        app.processEvents()
        browser.shutdown()
    assert s is not None
    get = next(r for r in s.requests if r.method == "GET" and "/api/data.json" in r.url)
    post = next(r for r in s.requests if r.method == "POST")
    assert get.headers["authorization"] == "Bearer SEGRETO" and get.headers["x-website-token"] == "WT1"
    assert get.text and '"foto.jpg"' in get.text and get.status == 200
    assert post.headers["sign"] == "FIRMA" and post.body == '{"id":5}'
    assert any(c.name == "sessione" and c.value == "abc123" for c in s.cookies)
    assert '/files/foto.jpg' in s.html                       # pagina costruita dal JavaScript
    assert s.header_for(r"/api/", "authorization") == "Bearer SEGRETO"
