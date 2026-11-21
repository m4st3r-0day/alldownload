"""Finto server Koofr per i test (3 livelli di cartelle, password opzionale)."""
import json
import re
from urllib.parse import unquote

import httpx
import pytest

BASE = "https://app.koofr.net"
LINK = f"{BASE}/links/abc-123"

TREE = {
    "/": [("foto1.jpg", "file"), ("note.txt", "file"), ("Vacanze", "dir")],
    "/Vacanze": [("mare.png", "file"), ("2024", "dir")],
    "/Vacanze/2024": [("video.mp4", "file"), ("Agosto", "dir")],
    "/Vacanze/2024/Agosto": [("tramonto è.jpeg", "file")],
}


def norm(path: str) -> str:
    p = re.sub("/+", "/", path)          # Koofr accetta anche "//nome"
    return p.rstrip("/") or "/"


def make_transport(password=None, log=None):
    def handler(req: httpx.Request):
        if log is not None:
            log.append(str(req.url))
        p = req.url.path
        if p == "/api/v2/public/links/abc-123":
            if password and req.url.params.get("password") != password:
                return httpx.Response(401)
            return httpx.Response(200, json={"id": "abc-123", "name": "Foto di Anna"})
        if p == "/api/v2/public/links/abc-123/bundle":
            if password and req.url.params.get("password") != password:
                return httpx.Response(401)
            path = norm(req.url.params["path"])
            if path not in TREE:
                return httpx.Response(404)
            files = [{"name": n, "type": t, "size": len(n.encode()) if t == "file" else 0}
                     for n, t in TREE[path]]
            body = json.dumps({"file": {"name": path, "type": "dir"}, "files": files},
                              separators=(",", ":"))
            return httpx.Response(200, content=body.encode(),
                                  headers={"content-type": "application/json"})
        if p.startswith("/content/links/abc-123/files/get/"):
            assert req.headers["Referer"] == LINK
            name = unquote(p.rsplit("/", 1)[1])
            return httpx.Response(200, content=name.encode())
        return httpx.Response(404)
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def no_user_templates(tmp_path, monkeypatch):
    """I test non devono leggere i template installati sul PC."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from picfinder import plugins
    plugins.reload()
