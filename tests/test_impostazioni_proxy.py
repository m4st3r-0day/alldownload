"""Impostazioni, lista proxy, limite di velocità."""
import asyncio
import time

import httpx

from picfinder.core import Downloader, RemoteFile, SpeedLimiter
from picfinder.proxies import ProxyPool, is_proxy_failure, mask
from picfinder.settings import ProxyEntry, Settings


def test_impostazioni_salva_e_rileggi(tmp_path, monkeypatch):
    monkeypatch.setenv("PICFINDER_SETTINGS", str(tmp_path / "s.json"))
    s = Settings.load()
    assert s.parallel == 4 and s.proxies == []
    s.parallel, s.theme, s.proxy_mode = 99, "dark", "fastest"
    s.proxies = [ProxyEntry("socks5://u:pw@1.2.3.4:1080", name="casa"), ProxyEntry("http://5.6.7.8:3128", enabled=False)]
    s.save()
    r = Settings.load()
    assert r.parallel == 16 and r.theme == "dark"                 # valori fuori scala corretti
    assert [p.name for p in r.proxies] == ["casa", ""] and len(r.enabled_proxies()) == 1
    (tmp_path / "s.json").write_text("non è json")
    assert Settings.load().parallel == 4                           # file rotto: valori di partenza


def test_proxy_il_piu_veloce_e_cambio_se_non_risponde():
    speeds = {"http://a:1": 300, "http://b:1": 80, "http://c:1": None}

    async def tester(proxy, url, timeout):
        if speeds[proxy] is None:
            raise httpx.ConnectError("rifiutato")
        return speeds[proxy]

    pool = ProxyPool([ProxyEntry(u) for u in speeds], "fastest", tester=tester)
    assert asyncio.run(pool.choose()) == "http://b:1"            # il più veloce
    assert pool.ordered() == ["http://b:1", "http://a:1"]          # quello morto è escluso
    assert pool.mark_dead("http://b:1", "timeout") == "http://a:1"
    assert pool.mark_dead("http://a:1", "timeout") is None         # nessuno: senza proxy


def test_modalita_primo_e_spento():
    async def tester(proxy, url, timeout):
        return {"http://a:1": 500, "http://b:1": 10}[proxy]
    pool = ProxyPool([ProxyEntry("http://a:1"), ProxyEntry("http://b:1")], "first", tester=tester)
    assert asyncio.run(pool.choose()) == "http://a:1"             # rispetta l'ordine della lista
    assert not ProxyPool([ProxyEntry("http://a:1")], "off")


def test_errori_del_sito_non_cambiano_proxy():
    req = httpx.Request("GET", "https://x")
    assert is_proxy_failure(httpx.ConnectError("x")) and is_proxy_failure(httpx.ProxyError("x"))
    assert not is_proxy_failure(httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req)))
    assert mask("socks5://mario:segreta@1.2.3.4:1080") == "socks5://mario:***@1.2.3.4:1080"


def test_download_passa_al_proxy_successivo(tmp_path):
    """Se il proxy cade durante i download, si continua col prossimo senza perdere tentativi."""
    async def tester(proxy, url, timeout):
        return {"http://uno:1": 10, "http://due:1": 50}[proxy]
    pool = ProxyPool([ProxyEntry("http://uno:1"), ProxyEntry("http://due:1")], "fastest", tester=tester)
    dl = Downloader(tmp_path, transport=None, proxy_pool=pool)
    used = []

    class T(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req):
            used.append(dl.proxy)
            if dl.proxy == "http://uno:1":
                raise httpx.ConnectError("proxy spento")
            return httpx.Response(200, content=b"ok")

    dl.transport = T()
    stats = asyncio.run(dl.download([RemoteFile(url="https://x.it/a.jpg", name="a.jpg")]))
    assert stats["done"] == 1 and used == ["http://uno:1", "http://due:1"]


def test_limite_di_velocita():
    async def go():
        lim = SpeedLimiter(100)                  # 100 KB/s
        t0 = time.monotonic()
        for _ in range(3):
            await lim.consume(100 * 1024)        # 300 KB
        return time.monotonic() - t0
    assert 1.6 < asyncio.run(go()) < 2.6         # il primo "pieno" è gratis, poi ~2 s


def test_nomi_delle_fonti():
    from picfinder.core import source_name
    assert source_name("https://onlyfans.com/mario_rossi/media") == "mario_rossi"
    assert source_name("https://gofile.io/d/yM2TxCbc") == "yM2TxCbc"
    assert source_name("https://pixeldrain.com/l/Lista9") == "Lista9"
    assert source_name("https://www.imagefap.com/gallery.php?gid=123") == "123"
    assert source_name("https://www.tumblr.com/bloggo") == "bloggo"
    assert source_name("https://bunkr.cr/a/AlbumX") == "AlbumX"
    assert source_name("https://esempio.it/") == "esempio.it"


def test_cartelle_per_link_e_tipo():
    from picfinder.core import organize
    of = "https://onlyfans.com/mario/media"
    assert organize("", of, "a.jpg", True, True) == "mario/Foto"
    assert organize("", of, "b.mp4", True, True) == "mario/Video"
    assert organize("", of, "c.zip", True, True) == "mario/Altri"
    # sottocartelle del template: restano, senza doppioni del nome
    assert organize("Lista9", "https://pixeldrain.com/l/Lista9", "x.png", True, True) == "Lista9/Foto"
    assert organize("123-Nice-Set", "https://www.imagefap.com/pictures/123/Nice-Set", "x.jpg", True, False) == "123-Nice-Set"
    assert organize("Vacanze/2024", "https://app.koofr.net/links/abc", "v.mp4", True, True) == "abc/Vacanze/2024/Video"
    assert organize("Sub", "https://x.it/a/b", "f.jpg", False, False) == "Sub"


def test_scan_organizza(tmp_path):
    import asyncio
    from conftest import LINK, make_transport
    from picfinder.core import Downloader
    files = asyncio.run(Downloader(tmp_path, transport=make_transport(), folder_per_link=True,
                                   split_by_type=True).scan_many([LINK]))
    # cartella col nome del link condiviso (non «abc-123»), e nessuna cartella doppia
    assert sorted(f.subdir for f in files) == ["Foto di Anna/Foto", "Foto di Anna/Vacanze/2024/Agosto/Foto",
                                               "Foto di Anna/Vacanze/2024/Video", "Foto di Anna/Vacanze/Foto"]
