"""Anteprime: fotogrammi dei video con ffmpeg, miniature del sito."""
import subprocess
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from picfinder.core import Downloader, RemoteFile, find_ffmpeg, kind_of, video_frame

needs_ffmpeg = pytest.mark.skipif(not find_ffmpeg(), reason="ffmpeg non installato")


@pytest.fixture
def video(tmp_path):
    out = tmp_path / "clip.mp4"
    subprocess.run([find_ffmpeg(), "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=5:size=320x240:rate=10",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)
    return out


def test_tipi():
    assert kind_of("a.MP4") == "video" and kind_of("b.jpeg") == "image" and kind_of("c.zip") == "other"


@needs_ffmpeg
def test_fotogramma_da_file(video):
    data = video_frame(str(video))
    assert data[:2] == b"\xff\xd8"           # JPEG


@needs_ffmpeg
def test_fotogramma_da_indirizzo_con_referer(video):
    seen = {}

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen["referer"] = self.headers.get("Referer")
            super().do_GET()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(H, directory=str(video.parent)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/clip.mp4"
        data, source = Downloader(video.parent).preview_bytes(
            RemoteFile(url=url, name="clip.mp4", headers={"Referer": "https://sito.example/pagina"}))
        assert data[:2] == b"\xff\xd8" and "ffmpeg" in source
        assert seen["referer"] == "https://sito.example/pagina"
    finally:
        srv.shutdown()


def test_miniatura_del_sito_ha_la_precedenza(tmp_path):
    calls = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, content=b"\xff\xd8thumb")
    dl = Downloader(tmp_path, transport=httpx.MockTransport(handler))
    f = RemoteFile(url="https://x/api/file/1?download", name="v.mp4", thumb="https://x/api/file/1/thumbnail")
    data, source = dl.preview_bytes(f)
    assert data == b"\xff\xd8thumb" and calls == ["https://x/api/file/1/thumbnail"] and source == "miniatura del sito"
