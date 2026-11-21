"""Download in parallelo ma cortese: limiti per server, 429, ripresa."""
import asyncio
import time

import httpx

from picfinder.core import Downloader, HostGate, RemoteFile, retry_after


class Slow(httpx.AsyncBaseTransport):
    """Ogni risposta impiega 0,3 s; registra quante richieste contemporanee riceve ogni server."""
    def __init__(self):
        self.now: dict[str, int] = {}
        self.peak: dict[str, int] = {}

    async def handle_async_request(self, req):
        h = req.url.host
        self.now[h] = self.now.get(h, 0) + 1
        self.peak[h] = max(self.peak.get(h, 0), self.now[h])
        await asyncio.sleep(0.3)
        self.now[h] -= 1
        return httpx.Response(200, content=b"x" * 10)


def test_parallelo_su_server_diversi_ma_uno_per_server(tmp_path):
    t = Slow()
    files = [RemoteFile(url=f"https://s{i % 3}.esempio.it/f{i}.jpg", name=f"f{i}.jpg", opts={"connections": 1})
             for i in range(6)]
    t0 = time.monotonic()
    stats = asyncio.run(Downloader(tmp_path, transport=t, concurrency=4).download(files))
    elapsed = time.monotonic() - t0
    assert stats["done"] == 6
    assert max(t.peak.values()) == 1            # mai 2 richieste insieme allo stesso server
    assert elapsed < 1.2                        # 3 server in parallelo: ~0,6 s invece di 1,8 s


def test_429_rallenta_solo_quel_server(tmp_path):
    calls = []

    def handler(req):
        calls.append((req.url.host, time.monotonic()))
        if req.url.host == "lento.it" and sum(1 for h, _ in calls if h == "lento.it") == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, content=b"ok")
    files = [RemoteFile(url="https://lento.it/a.jpg", name="a.jpg"),
             RemoteFile(url="https://veloce.it/b.jpg", name="b.jpg")]
    stats = asyncio.run(Downloader(tmp_path, transport=httpx.MockTransport(handler)).download(files))
    assert stats["done"] == 2
    lento = [t for h, t in calls if h == "lento.it"]
    assert len(lento) == 2 and lento[1] - lento[0] >= 0.9     # ha aspettato Retry-After


def test_ripresa_dopo_interruzione(tmp_path):
    data = bytes(range(256)) * 40          # 10 KB
    seen_ranges = []

    class Flaky(httpx.AsyncBaseTransport):
        def __init__(self):
            self.n = 0

        async def handle_async_request(self, req):
            self.n += 1
            rng = req.headers.get("range")
            seen_ranges.append(rng)
            if rng:
                start = int(rng.split("=")[1].rstrip("-"))
                return httpx.Response(206, content=data[start:],
                                      headers={"content-length": str(len(data) - start)})

            class Broken(httpx.AsyncByteStream):        # si interrompe a metà
                async def __aiter__(self):
                    yield data[:4000]
                    raise httpx.ReadError("connessione persa")
            return httpx.Response(200, stream=Broken(), headers={"content-length": str(len(data))})

    stats = asyncio.run(Downloader(tmp_path, transport=Flaky()).download(
        [RemoteFile(url="https://x.it/v.mp4", name="v.mp4")]))
    assert stats["done"] == 1
    assert (tmp_path / "v.mp4").read_bytes() == data
    assert seen_ranges == [None, "bytes=4000-"]


def test_retry_after():
    assert retry_after("7") == 7 and retry_after(None, 30) == 30 and retry_after("boh", 5) == 5


def test_pausa_per_connessione_come_epf():
    """3 connessioni con pausa: i primi 3 file partono insieme, poi ogni connessione fa la sua pausa."""
    starts = []

    async def go(per_host, n):
        g = HostGate(per_host=per_host)
        t0 = time.monotonic()

        async def one():
            async with g.slot("https://cdn.it/x", (0.3, 0.3)):
                starts.append(time.monotonic() - t0)
        await asyncio.gather(*(one() for _ in range(n)))

    asyncio.run(go(3, 6))
    first, second = sorted(starts)[:3], sorted(starts)[3:]
    assert max(first) < 0.1                     # 3 insieme subito
    assert min(second) >= 0.28                  # poi dopo la pausa di ogni connessione
    starts.clear()
    asyncio.run(go(1, 2))
    assert sorted(starts)[1] >= 0.28            # una sola connessione: uno alla volta


def test_pausa_non_blocca_la_fine_del_file():
    """Il file finisce subito: la pausa la fa la connessione dopo, non il file."""
    async def go():
        g = HostGate(per_host=1)
        t0 = time.monotonic()
        async with g.slot("https://cdn.it/x", (0.4, 0.4)):
            pass
        return time.monotonic() - t0
    assert asyncio.run(go()) < 0.1


def test_pause_ridotte_e_piene_dopo_429():
    g = HostGate(per_host=1, scale=0.5)
    assert 1.4 <= g.pause_for("cdn.it", (3.0, 5.0)) <= 2.5
    g0 = HostGate(per_host=1, scale=0.0)
    assert g0.pause_for("cdn.it", (3.0, 5.0)) <= 0.8
    g.cooldown("https://cdn.it/x", 1)            # il server si lamenta: pause piene
    assert g.pause_for("cdn.it", (3.0, 5.0)) >= 3.0


def test_link_rotti_scartati():
    from picfinder.etmpl import BROKEN_URL
    assert BROKEN_URL.search("https://texts.onlyfans.com/{POST_URL}")
    assert BROKEN_URL.search("https://texts.onlyfans.com/\\/contact")
    assert not BROKEN_URL.search("https://cdn.it/foto%20uno.jpg?x=1")


def test_lista_proxy_webshare():
    from picfinder.proxies import apply_list, parse_proxy_line, LIST_NAME
    from picfinder.settings import ProxyEntry
    assert parse_proxy_line("1.2.3.4:8080:user:p@ss") == "http://user:p%40ss@1.2.3.4:8080"
    assert parse_proxy_line("1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert parse_proxy_line("socks5://a:b@h:1") == "socks5://a:b@h:1"
    assert parse_proxy_line("# commento") is None
    mine = ProxyEntry("http://mio:1")
    old = ProxyEntry("http://vecchio:1", name=LIST_NAME)
    out = apply_list([mine, old], ["http://nuovo:1"])
    assert [e.url for e in out] == ["http://mio:1", "http://nuovo:1"]


def test_flussi_video_non_esplorati():
    from picfinder.etmpl import STREAM_MANIFEST
    assert STREAM_MANIFEST.search("https://cdn2.x.com/hls/files/a/0i.m3u8?Tag=2")
    assert STREAM_MANIFEST.search("https://cdn2.x.com/dash/a.mpd")
    assert not STREAM_MANIFEST.search("https://cdn2.x.com/files/a.mp4?x=m3u8")


def test_link_legato_ip():
    import base64, json
    from picfinder.core import ip_locked
    pol = {"Statement": [{"Condition": {"IpAddress": {"AWS:SourceIp": "1.2.3.4/32"}}}]}
    enc = base64.b64encode(json.dumps(pol).encode()).decode().replace("+", "-").replace("=", "_").replace("/", "~")
    assert ip_locked(f"https://cdn.it/a.jpg?Policy={enc}&Signature=x")
    assert not ip_locked("https://cdn.it/a.jpg?x=1")


def test_chiave_file_stabile_e_cartella_chat():
    from picfinder.core import file_key, organize
    a = "https://cdn2.onlyfans.com/files/9/96/x/1.jpg?Tag=2&u=1&Policy=AAA&Signature=BBB&Key-Pair-Id=K"
    b = "https://cdn2.onlyfans.com/files/9/96/x/1.jpg?Tag=2&u=1&Policy=CCC&Signature=DDD&Key-Pair-Id=K"
    assert file_key(a) == file_key(b)
    assert file_key("https://k.net/get?path=%2Fa.jpg") != file_key("https://k.net/get?path=%2Fb.jpg")
    assert organize("", "https://onlyfans.com/my/chats/chat/77/gallery", "v.mp4", True, True) == "77/Chat/Video"


def test_non_riscarica_file_gia_scaricati(tmp_path):
    import httpx
    from picfinder.core import Downloader, RemoteFile
    from picfinder.projects import History
    hits = []

    def handler(req):
        hits.append(str(req.url))
        return httpx.Response(200, content=b"x" * 10, headers={"content-type": "image/jpeg"})
    h = History(tmp_path / "db.sqlite")
    files = lambda sig: [RemoteFile(url=f"https://cdn.it/a/1.jpg?Signature={sig}", name="1.jpg")]
    dl = Downloader(tmp_path / "out", None, transport=httpx.MockTransport(handler), history=h)
    s1 = asyncio.run(dl.download(files("A")))
    s2 = asyncio.run(dl.download(files("B")))          # link rifirmato: stesso file
    assert s1["done"] == 1 and s2["skipped"] == 1 and len(hits) == 1
    (tmp_path / "out" / "1.jpg").unlink()              # cancellato dal disco: si riscarica
    s3 = asyncio.run(dl.download(files("C")))
    assert s3["done"] == 1 and len(hits) == 2


def test_403_su_link_legato_ip_non_riprova(tmp_path):
    import base64, json
    import httpx
    from picfinder.core import Downloader, RemoteFile, locked_ip
    pol = {"Statement": [{"Condition": {"IpAddress": {"AWS:SourceIp": "9.9.9.9/32"}}}]}
    enc = base64.b64encode(json.dumps(pol).encode()).decode().replace("+", "-").replace("=", "_").replace("/", "~")
    url = f"https://cdn.it/a.jpg?Policy={enc}&Signature=x"
    assert locked_ip(url) == "9.9.9.9"
    hits = []

    def handler(req):
        hits.append(str(req.url))
        if "ipify" in str(req.url):
            return httpx.Response(200, text="1.1.1.1")
        return httpx.Response(403, text="<Error/>")
    dl = Downloader(tmp_path, None, transport=httpx.MockTransport(handler))
    st = asyncio.run(dl.download([RemoteFile(url=url, name="a.jpg")]))
    assert st["failed"] == 1 and sum("cdn.it" in h for h in hits) == 1
