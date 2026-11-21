import json
import os
import struct

from picfinder import postproc as pp


def test_parse_date():
    assert pp.parse_date(1773480000) == 1773480000
    assert pp.parse_date(1773480000000) == 1773480000
    assert pp.parse_date("2026-03-14T09:20:00+00:00") == 1773480000
    assert pp.parse_date("Sat, 14 Mar 2026 09:20:00 GMT") == 1773480000
    assert pp.parse_date("ciao") is None and pp.parse_date(True) is None and pp.parse_date(5) is None


def test_json_meta_eredita_dal_post():
    data = {"list": [{"id": 1, "rawText": "Ciao <br/>a tutti", "postedAt": "2026-03-14T09:20:00+00:00",
                      "media": [{"id": 9, "files": {"full": {"url": "https://cdn.x/a.jpg"}},
                                 "source": {"source": "https://cdn.x/a.jpg"}},
                                {"id": 10, "createdAt": "2026-03-15T00:00:00Z",
                                 "files": {"full": {"url": "https://cdn.x/b.mp4"}}}]}]}
    m = pp.json_meta(json.dumps(data))
    assert m["https://cdn.x/a.jpg"]["date"] == 1773480000
    assert m["https://cdn.x/a.jpg"]["caption"] == "Ciao \na tutti"
    assert m["https://cdn.x/b.mp4"]["date"] == pp.parse_date("2026-03-15T00:00:00Z")


def test_render_name():
    n = pp.render_name("{profilo}_{data}_{n}", "IMG 1.JPG", "https://onlyfans.com/x", 7, "mario", 1773480000)
    assert n.startswith("mario_2026-03-1") and n.endswith("_0007.JPG")
    assert pp.render_name("{sito}/{nome}", "a.png", "https://www.bunkr.cr/f/1", 1) == "bunkr_a.png"
    assert pp.render_name("", "a.png", "u", 1) == "a.png"


def test_finalize(tmp_path):
    p = tmp_path / "IMG.jpg"
    p.write_bytes(b"x")
    out = pp.finalize(p, "https://s.test/1", {"date": 1773480000, "caption": "ciao"},
                      pattern="{profilo}_{n}", counter=3, owner="mario", captions=True)
    assert out.name == "mario_0003.jpg" and not p.exists()
    assert int(os.path.getmtime(out)) == 1773480000
    assert (tmp_path / "mario_0003.jpg.txt").read_text().strip() == "ciao"
    q = tmp_path / "x.jpg"
    q.write_bytes(b"y")
    out2 = pp.finalize(q, "u", {"last_modified": "Sat, 14 Mar 2026 09:20:00 GMT"})
    assert out2 == q and int(os.path.getmtime(q)) == 1773480000


def _mp4(with_moov=True, cut=0):
    def box(kind, payload=b""):
        return struct.pack(">I", 8 + len(payload)) + kind + payload
    data = box(b"ftyp", b"isom0000") + (box(b"moov", b"\0" * 20) if with_moov else b"") + box(b"mdat", b"\1" * 100)
    return data[:len(data) - cut]


def test_check_file(tmp_path):
    def w(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return pp.check_file(p)[0]
    assert w("ok.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 100 + b"\xff\xd9")
    assert not w("cut.jpg", b"\xff\xd8\xff\xe0" + b"\0" * 100)
    assert w("ok.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 20 + b"IEND\xaeB`\x82")
    assert not w("cut.png", b"\x89PNG\r\n\x1a\n" + b"\0" * 20)
    assert w("webp_chiamato.jpg", b"RIFF" + struct.pack("<I", 12) + b"WEBPVP8 " + b"\0" * 4)
    assert w("ok.mp4", _mp4())
    assert not w("nomoov.mp4", _mp4(with_moov=False))
    assert not w("cut.mp4", _mp4(cut=30))
    assert not w("pagina.jpg", b"<!DOCTYPE html><html>errore</html>")
    assert not w("vuoto.jpg", b"")
    assert w("altro.bin", b"qualsiasi")
    assert w("finto.jpg", b"foto1.jpg")           # contenuto sconosciuto: non lo blocco


def test_free_bytes(tmp_path):
    assert pp.free_bytes(tmp_path / "non" / "esiste") > 0


def test_downloader_riscarica_jpeg_troncato_e_mette_nome_e_data(tmp_path):
    import asyncio

    import httpx

    from picfinder.core import Downloader, RemoteFile
    good = b"\xff\xd8\xff\xe0" + b"\0" * 200 + b"\xff\xd9"
    calls = []

    def handler(req):
        calls.append(1)
        body = good[:100] if len(calls) == 1 else good          # la prima volta arriva a metà
        return httpx.Response(200, content=body, headers={"content-type": "image/jpeg",
                                                         "last-modified": "Sat, 14 Mar 2026 09:20:00 GMT"})
    dl = Downloader(tmp_path, transport=httpx.MockTransport(handler), segments=1)
    dl.name_pattern = "{profilo}_{n}"
    f = RemoteFile(url="https://cdn.test/a.jpg", name="a.jpg", subdir="mario")
    stats = asyncio.run(dl.download([f]))
    assert stats["done"] == 1 and len(calls) == 2
    out = tmp_path / "mario" / "mario_0001.jpg"
    assert out.read_bytes() == good and int(os.path.getmtime(out)) == 1773480000


def test_downloader_si_ferma_se_il_disco_e_pieno(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from picfinder import core
    from picfinder.core import Downloader, RemoteFile
    monkeypatch.setattr(core, "free_bytes", lambda p: 100 * 1024 * 1024)      # 100 MB liberi
    events = []
    dl = Downloader(tmp_path, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")),
                    on_event=lambda k, d: events.append(k))
    asyncio.run(dl.download([RemoteFile(url="https://cdn.test/a.jpg", name="a.jpg")]))
    assert "disk_full" in events and not (tmp_path / "a.jpg").exists()


def test_gofile_cookie_dal_token_del_browser(tmp_path):
    """Gofile: senza il cookie accountToken i server dei file mandano una pagina web."""
    import asyncio

    import httpx

    from picfinder.core import Downloader, RemoteFile
    from picfinder.session import BrowserSession, CapturedRequest
    good = b"\x00\x00\x00\x10ftypisom0000" + b"\x00\x00\x00\x10moov" + b"\0" * 8 + b"\x00\x00\x00\x0cmdat" + b"\1" * 4

    def handler(req):
        if "accountToken=TOK" in req.headers.get("cookie", ""):
            return httpx.Response(200, content=good, headers={"content-type": "video/mp4"})
        return httpx.Response(200, text="<!DOCTYPE html><html><title>Gofile</title></html>",
                              headers={"content-type": "text/html"})
    s = BrowserSession("https://gofile.io/d/x", requests=[
        CapturedRequest("https://api.gofile.io/contents/x?page=1", headers={"authorization": "Bearer TOK"})])
    dl = Downloader(tmp_path, transport=httpx.MockTransport(handler), segments=1)
    dl.sessions["https://gofile.io/d/x"] = s
    s.add_token_cookies()
    stats = asyncio.run(dl.download([RemoteFile(url="https://file-eu-par-5.gofile.io/download/web/a/v.mp4", name="v.mp4")]))
    assert stats["done"] == 1 and (tmp_path / "v.mp4").read_bytes() == good
