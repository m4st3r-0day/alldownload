"""Motore .etmpl: un template scritto da noi per il finto Koofr (i template EPF non sono più inclusi)."""
import asyncio
import re
from pathlib import Path

import httpx
import pytest

from picfinder.core import Downloader, PluginError
from picfinder.etmpl import EtmplPlugin, Template, expand
from picfinder.plugins import find_plugin

from conftest import BASE, LINK, make_transport

FIXTURES = Path(__file__).parent / "fixtures"
CORRETTO = FIXTURES / "koofr_prova.etmpl"


def run(tmp_path, tpl_path, url, password=None, server_password=None, log=None):
    plugin = EtmplPlugin(Template.load(tpl_path))
    dl = Downloader(tmp_path, transport=make_transport(server_password, log))
    return asyncio.run(dl.run(url, password, plugin=plugin))


def files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_lettura_template():
    t = Template.load(CORRETTO)
    assert t.title == "koofr prova"
    assert len(t.parsers) == 3 and t.parsers[1].method == "GET"
    assert "*.mp4" in t.targets


def test_variabili():
    m0 = re.search(r"(a)(b)", "ab")
    m1 = re.search(r"(x)", "x")
    assert expand("[#1]-[#2]", m0, [m0]) == "a-b"
    assert expand("[#-1:2]/[#1]", m1, [m0, m1], idx=1) == "b/x"
    assert expand("[#1:1]", None, [m0]) == "a"
    assert expand("[#jsonencode([#1])#]", re.search(r"(.+)", r"ciao è a/b"), []) == "ciao%20%C3%A8%20a%2Fb"


def test_link_incollato_sceglie_template():
    p = find_plugin(LINK)
    assert p.NAME == "Koofr"                    # il plugin Python ha la precedenza (cartella col nome del link)
    assert find_plugin("https://esempio.com/x") is None


def test_template_corretto_scarica_tutti_i_livelli(tmp_path):
    stats = run(tmp_path, CORRETTO, LINK)
    assert stats["done"] == 4 and stats["failed"] == 0
    assert files(tmp_path) == {
        "foto1.jpg",
        "Vacanze/mare.png",
        "Vacanze/2024/video.mp4",
        "Vacanze/2024/Agosto/tramonto è.jpeg",
    }


def test_password_passa_a_tutte_le_cartelle(tmp_path):
    log: list[str] = []
    stats = run(tmp_path, CORRETTO, LINK, password="se gre/ta", server_password="se gre/ta", log=log)
    assert stats["done"] == 4
    bundles = [u for u in log if "/bundle" in u]
    assert len(bundles) == 4 and all("password=se%20gre%2Fta" in u for u in bundles)


def test_password_sbagliata(tmp_path):
    with pytest.raises(PluginError, match="password"):
        run(tmp_path, CORRETTO, LINK, password="no", server_password="si")


def test_seconda_volta_salta_i_file_presenti(tmp_path):
    run(tmp_path, CORRETTO, LINK)
    stats = run(tmp_path, CORRETTO, LINK)
    assert stats["skipped"] == 4 and stats["done"] == 0


def test_disattivare_un_template(monkeypatch):
    from picfinder import plugins
    monkeypatch.setenv("PICFINDER_TEMPLATES", str(FIXTURES))    # template aggiunto dall'utente
    plugins.reload()
    key = find_plugin(LINK).KEY
    assert key == "python/koofr"                          # il plugin Python passa davanti
    plugins.set_enabled(key, False)
    p = find_plugin(LINK)
    assert p is not None and p.KEY == "tuoi/koofr_prova.etmpl"   # resta il template
    plugins.set_enabled("tuoi/koofr_prova.etmpl", False)
    assert find_plugin(LINK) is None
    plugins.set_enabled(key, True)
    assert find_plugin(LINK).KEY == key
    e = {x["key"]: x for x in plugins.entries()}
    assert e[key]["enabled"] and not e["tuoi/koofr_prova.etmpl"]["enabled"]
    plugins.set_enabled("tuoi/koofr_prova.etmpl", True)
    monkeypatch.delenv("PICFINDER_TEMPLATES")
    plugins.reload()


def test_nessun_template_epf_incluso():
    from picfinder.plugins import BUILTIN_TEMPLATES
    assert list(BUILTIN_TEMPLATES.glob("*.etmpl")) == []


def test_ricerca_in_profondita_i_file_escono_subito(tmp_path):
    """Album con 3 pagine-file: il primo file deve uscire prima di visitare la seconda pagina
    (prima: tutte le pagine, poi tutti i file → sembrava bloccato)."""
    tpl = tmp_path / "album.etmpl"
    tpl.write_text(
        "[Settings]\nExplorationLimit=selEntireSite\n[TargetFiles]\nFile000=*.jpg\n"
        "[StartingURLTemplates]\nURL000=album\\.test/a/\n"
        "[IncludedURLs]\nURL000=album\\.test/[af]/\nURL001=\\.jpg$\n"
        "[CustomParsers]\nExpression000=href=\"(/f/\\d+)\"\nAddress000=https://album.test[#1]\n"
        "Expression001=src=\"(https://cdn\\.album\\.test/\\d+\\.jpg)\"\nAddress001=[#1]\n"
        "[TemplateSettings]\nEncodedTitle=album%20test\n", encoding="utf-8")
    order = []

    def handler(req):
        order.append(req.url.path)
        if req.url.path == "/a/x":
            return httpx.Response(200, text='<a href="/f/1"></a><a href="/f/2"></a><a href="/f/3"></a>',
                                  headers={"content-type": "text/html"})
        n = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, text=f'<img src="https://cdn.album.test/{n}.jpg">',
                              headers={"content-type": "text/html"})

    async def go():
        plugin = EtmplPlugin(Template.load(tpl))
        out = []
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            async for f in plugin.list_files(c, "https://album.test/a/x"):
                out.append((f.name, len(order)))
        return out
    got = asyncio.run(go())
    assert [n for n, _ in got] == ["1.jpg", "2.jpg", "3.jpg"]
    assert got[0][1] == 2          # album + /f/1, poi subito il primo file
