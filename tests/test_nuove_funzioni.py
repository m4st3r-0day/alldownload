"""Funzioni nuove: velocità adattiva, pezzi, ordine, chat, scadenze, orari, banda, cerca+scarica, pausa, HLS."""
import asyncio
import base64
import json
import time

import httpx

from picfinder.core import (Downloader, HostGate, RemoteFile, SpeedLimiter, chat_owner, order_for_download)
from picfinder.netpolicy import Schedule, SiteMemory, expired, link_expiry
from picfinder.session import BrowserSession, CapturedRequest


def test_connessioni_adattive_crescono_e_scendono(tmp_path):
    mem = SiteMemory(tmp_path / "lim.json")
    g = HostGate(per_host=4, adaptive=True, memory=mem)
    assert g.limit_for("cdn.it") == 2                    # parte con la metà
    for _ in range(HostGate.GROW_AFTER):
        g.success("https://cdn.it/a")
    assert g.limit_for("cdn.it") == 3
    g.cooldown("https://cdn.it/a", 0)
    assert g.limit_for("cdn.it") == 1
    g.remember()
    assert SiteMemory(tmp_path / "lim.json").get("cdn.it") == 1
    assert HostGate(per_host=4, adaptive=True, memory=SiteMemory(tmp_path / "lim.json")).limit_for("cdn.it") == 1


def test_ordine_piccoli_prima_e_server_a_turno():
    fs = [RemoteFile(url="https://a.it/v1.mp4", name="v1.mp4", size=900),
          RemoteFile(url="https://a.it/f1.jpg", name="f1.jpg", size=50),
          RemoteFile(url="https://a.it/f2.jpg", name="f2.jpg", size=10),
          RemoteFile(url="https://b.it/f3.jpg", name="f3.jpg", size=20)]
    names = [f.name for f in order_for_download(fs)]
    assert names[0] == "f2.jpg" and names[1] == "f3.jpg" and names[-1] == "v1.mp4"


def test_utente_della_chat_dalla_sessione():
    s = BrowserSession(start_url="https://onlyfans.com/my/chats/chat/398/")
    s.requests.append(CapturedRequest(method="GET", url="https://onlyfans.com/api2/v2/users/list?r[]=398",
                                      text='{"398":{"view":"x","id":398,"name":"Ma Rio","username":"mario_x"}}'))
    assert chat_owner(s, "https://onlyfans.com/my/chats/chat/398/") == "mario_x"
    assert chat_owner(None, "https://onlyfans.com/my/chats/chat/398/") is None


def _policy(t):
    pol = {"Statement": [{"Condition": {"DateLessThan": {"AWS:EpochTime": t}}}]}
    return base64.b64encode(json.dumps(pol).encode()).decode().replace("+", "-").replace("=", "_").replace("/", "~")


def test_scadenza_link():
    future, past = int(time.time()) + 3600, int(time.time()) - 10
    assert link_expiry(f"https://c.it/a.jpg?Policy={_policy(future)}") == future
    assert expired(f"https://c.it/a.jpg?Policy={_policy(past)}")
    assert not expired("https://c.it/a.jpg")
    assert expired(f"https://c.it/a.jpg?expires={past}")


def test_orario_dei_download():
    sch = Schedule(enabled=True, start="23:00", end="07:00")
    at = lambda h: time.struct_time((2026, 1, 1, h, 0, 0, 0, 1, 0))
    assert sch.blocked(at(2)) is None and sch.blocked(at(23)) is None
    assert sch.blocked(at(12))


def test_quota_di_banda_misura_e_limita():
    lim = SpeedLimiter(0, share=50)
    lim.MEASURE = 0.0
    lim._peak = 1_000_000
    lim._t0 = time.monotonic() - 1
    lim._measure(1)
    assert 400_000 < lim.rate <= 500_000 and lim.share == 0


def test_pezzi_in_parallelo(tmp_path):
    data = bytes(range(256)) * 400            # 100 KB
    ranges = []

    def handler(req):
        rng = req.headers.get("range")
        ranges.append(rng)
        if rng:
            a, b = rng.split("=")[1].split("-")
            a, b = int(a), int(b) if b else len(data) - 1
            return httpx.Response(206, content=data[a:b + 1],
                                  headers={"content-range": f"bytes {a}-{b}/{len(data)}"})
        return httpx.Response(200, content=data)
    import picfinder.core as core
    old = core.SEGMENT_MIN
    core.SEGMENT_MIN = 10_000
    try:
        dl = Downloader(tmp_path, None, transport=httpx.MockTransport(handler), per_host=4)
        dl._test_segments = True
        st = asyncio.run(dl.download([RemoteFile(url="https://cdn.it/v.mp4", name="v.mp4")]))
    finally:
        core.SEGMENT_MIN = old
    assert st["done"] == 1 and (tmp_path / "v.mp4").read_bytes() == data
    assert len([r for r in ranges if r and r != "bytes=0-0"]) >= 2


def test_cerca_e_scarica_insieme(tmp_path):
    class Plug:
        NAME = "prova"

        @staticmethod
        def match(url):
            return True

        @staticmethod
        async def list_files(client, url, password=None):
            for i in range(3):
                await asyncio.sleep(0.1)
                yield RemoteFile(url=f"https://cdn.it/{i}.jpg", name=f"{i}.jpg")

    import picfinder.plugins as plugins
    events = []
    dl = Downloader(tmp_path, None, transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")),
                    on_event=lambda k, d: events.append(k))
    orig = plugins.find_plugin
    plugins.find_plugin = lambda url: Plug
    try:
        st = asyncio.run(dl.scan_and_download(["https://sito.it/x"]))
    finally:
        plugins.find_plugin = orig
    assert st["done"] == 3 and st["found"] == 3
    assert events.index("done") < events.index("scanned")      # un file finito prima della fine della ricerca


def test_pausa_tiene_il_pezzo(tmp_path):
    data = b"a" * 50_000

    class Slow(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req):
            rng = req.headers.get("range")
            if rng:
                a = int(rng.split("=")[1].rstrip("-"))
                return httpx.Response(206, content=data[a:])

            class S(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield data[:20_000]
                    await asyncio.sleep(5)
                    yield data[20_000:]
            return httpx.Response(200, stream=S(), headers={"content-length": str(len(data))})

    dl = Downloader(tmp_path, None, transport=Slow())
    f = RemoteFile(url="https://cdn.it/v.bin", name="v.bin")

    async def go():
        t = asyncio.ensure_future(dl.download([f]))
        await asyncio.sleep(0.5)
        dl.pause()
        await t
    asyncio.run(go())
    assert (tmp_path / "v.bin.part").stat().st_size == 20_000
    dl2 = Downloader(tmp_path, None, transport=Slow())
    assert asyncio.run(dl2.download([f]))["done"] == 1
    assert (tmp_path / "v.bin").read_bytes() == data


def test_hls_protetto_non_si_scarica(tmp_path, monkeypatch):
    import picfinder.core as core
    monkeypatch.setattr(core, "find_ffmpeg", lambda custom=None: "/usr/bin/ffmpeg")
    pl = "#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI=\"skd://x\"\n#EXTINF:4,\nseg1.ts\n"
    dl = Downloader(tmp_path, None, transport=httpx.MockTransport(lambda r: httpx.Response(200, text=pl)))
    st = asyncio.run(dl.download([RemoteFile(url="https://v.it/a/index.m3u8", name="index.m3u8")]))
    assert st["failed"] == 1
