"""Progetti salvati, "Aggiorna" e coda."""
import asyncio

from picfinder.core import Downloader
from picfinder.projects import Project, Store

from conftest import LINK, make_transport


def test_salva_modifica_elimina(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    pid = s.save(Project(title="Vacanze", category="Foto", links=[LINK, " ", "https://x/y"],
                         dest="/tmp/a", password="pw"))
    p = s.get(pid)
    assert p.title == "Vacanze" and p.links == [LINK, "https://x/y"] and p.password == "pw"
    p.title = "Vacanze 2024"
    s.save(p)
    assert [x.title for x in s.list()] == ["Vacanze 2024"]
    assert s.categories() == ["Foto"]
    assert [x.id for x in s.find("foto")] == [pid] and [x.id for x in s.find("vacanze 2024")] == [pid]
    s.record(pid, "u1", "done", "a.jpg")
    s.delete(pid)
    assert s.list() == [] and s.files(pid) == []


def test_conteggi_e_stato_fallito_non_cancella_salvato(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    pid = s.save(Project(title="P"))
    s.record(pid, "u1", "done", "a.jpg", "/x/a.jpg", 10)
    s.record(pid, "u2", "failed", "b.jpg")
    s.record(pid, "u1", "failed", "a.jpg")          # nuovo tentativo fallito: resta salvato
    p = s.get(pid)
    assert (p.saved, p.failed) == (1, 1)
    assert s.known_urls(pid) == {"u1"}
    s.forget_file(pid, "u1")
    assert s.known_urls(pid) == set()


def test_scan_di_piu_link(tmp_path):
    dl = Downloader(tmp_path, transport=make_transport())
    files = asyncio.run(dl.scan_many([LINK, LINK]))           # doppione: contato una volta
    assert len(files) == 4 and all(f.opts is not None for f in files)


def test_aggiorna_scarica_solo_nuovi(tmp_path):
    s = Store(tmp_path / "db.sqlite")
    pid = s.save(Project(title="K", links=[LINK]))
    dl = Downloader(tmp_path / "out", transport=make_transport())
    files = asyncio.run(dl.scan_many([LINK]))
    first = files[:2]
    asyncio.run(dl.download(first))
    for f in first:
        s.record(pid, f.url, "done", f.name)
    # l'utente cancella i file dal disco: "Aggiorna" non li riscarica
    for p in (tmp_path / "out").rglob("*"):
        if p.is_file():
            p.unlink()
    known = s.known_urls(pid)
    files = asyncio.run(Downloader(tmp_path / "out", transport=make_transport()).scan_many([LINK]))
    new = [f for f in files if f.url not in known]
    assert len(new) == 2 and not {f.url for f in new} & {f.url for f in first}


def test_aggiorna_da_riga_di_comando(tmp_path, capsys):
    from picfinder.cli import update_project
    s = Store(tmp_path / "db.sqlite")
    pid = s.save(Project(title="K", category="Cloud", links=[LINK], dest=str(tmp_path / "out")))
    assert update_project(s, s.get(pid), make_transport()) == 0
    assert s.get(pid).saved == 4 and s.get(pid).last_run
    assert update_project(s, s.get(pid), make_transport()) == 0
    assert "4 file trovati, 0 nuovi" in capsys.readouterr().out


def test_interrompi_ricerca_lenta(tmp_path):
    """Interrompi deve fermare subito anche una ricerca che aspetta (ritardi, pagine lente)."""
    import threading
    import time as _t

    import httpx

    async def slow(req):
        import asyncio as aio
        await aio.sleep(30)                        # un sito lentissimo
        return httpx.Response(200, text="")

    class Slow(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req):
            return await slow(req)

    dl = Downloader(tmp_path, transport=Slow())
    threading.Timer(0.3, dl.stop).start()
    t0 = _t.monotonic()
    files = asyncio.run(dl.scan_many([LINK]))
    assert files == [] and _t.monotonic() - t0 < 3


def test_interrompi_download(tmp_path):
    import threading
    import time as _t

    import httpx
    from picfinder.core import RemoteFile

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            import asyncio as aio
            for _ in range(100):
                await aio.sleep(0.1)
                yield b"x" * 10

    class T(httpx.AsyncBaseTransport):
        async def handle_async_request(self, req):
            return httpx.Response(200, stream=SlowBody(), headers={"content-length": "1000"})

    dl = Downloader(tmp_path, transport=T())
    files = [RemoteFile(url=f"https://x/{i}.jpg", name=f"{i}.jpg") for i in range(3)]
    threading.Timer(0.4, dl.stop).start()
    t0 = _t.monotonic()
    stats = asyncio.run(dl.download(files))
    assert _t.monotonic() - t0 < 3 and stats["done"] == 0
    assert not list(tmp_path.glob("*.part")) and not list(tmp_path.glob("*.jpg"))
