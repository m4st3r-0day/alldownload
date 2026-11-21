"""Motore dei template .etmpl provato con template scritti da noi su siti finti.

L'app non include più template di Extreme Picture Finder: i siti supportati hanno plugin Python.
Il formato .etmpl resta supportato per chi vuole aggiungere i suoi.
"""
import asyncio
import json
import random
import re

import httpx
import pytest

from picfinder.core import Downloader
from picfinder.etmpl import EtmplPlugin, Template, expand


@pytest.fixture(autouse=True)
def niente_attese(monkeypatch):
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)


def tpl(tmp_path, name: str, text: str):
    p = tmp_path.parent / f"tpl-{tmp_path.name}" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.strip() + "\n", encoding="utf-8")
    return p


def site(routes: dict, log: list | None = None):
    """routes: {(metodo, url esatto o regex): funzione(req) | (status, testo, headers) | testo}"""
    def handler(req: httpx.Request):
        url = str(req.url)
        if log is not None:
            log.append((req.method, url, req.content.decode() if req.content else "", req.headers.get("referer")))
        for (method, pattern), resp in routes.items():
            if req.method == method and (url == pattern or re.fullmatch(pattern, url)):
                r = resp(req) if callable(resp) else resp
                if isinstance(r, httpx.Response):
                    return r
                status, body, headers = (r + ({},))[:3] if isinstance(r, tuple) else (200, r, {})
                headers = {"content-type": "text/html; charset=utf-8", **headers}
                return httpx.Response(status, content=body if isinstance(body, bytes) else body.encode(),
                                      headers=headers)
        return httpx.Response(404, text="not found")
    return httpx.MockTransport(handler)


def run(dest, tpl_path, url, transport, events=None):
    """Scarica in dest/out (in dest i test tengono anche registro e impostazioni)."""
    plugin = EtmplPlugin(Template.load(tpl_path))
    cb = (lambda k, d: events.append((k, d))) if events is not None else None
    return asyncio.run(Downloader(dest / "out", transport=transport, on_event=cb).run(url, plugin=plugin))


def files(root):
    root = root / "out" if (root / "out").is_dir() else root
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- galleria: parti escluse, nome da alt, cartella
GALLERIA_TPL = r"""
[Settings]
ExplorationLimit=selEntireSite
NamingTagAttributeName=alt
SaveNamingType=sntTagAttributeValue
ResolveNamingConflictsType=rncDoNotSave
SubFoldersMode=sfmParentURLRE
DownloadTargetFilesFromExternalSites=True
SuggestedSimultaneousConnections=1
UseRandomDelayBetweenDownloads=True
MinDelayBetweenDownloads=2
MaxDelayBetweenDownloads=3
[TargetFiles]
File000=*.jpg
[ExcludedURLs]
URL000=.
[IncludedURLs]
URL000=/album/\d+/[^/?]+(\?p=\d+)?$
URL001=/foto/\d+/$
URL002=/grande/
[CustomParsers]
Expression000=<a[^>]+href="(/foto/\d+/)\?[^"]+"
Address000=[#1]
[SubFoldersParentURLREs]
Expression000=/album/(\d+)/([^?/]+)
Address000=[#1]-[#2]
[ExcludedPageParts]
From000=
To000=<div id="inizio"
From001=<div id="preferiti"
To001=
From002=<div id="descrizione"
To002=
[StartingURLTemplates]
URL000=galleria\.test/album/\d+
[TemplateSettings]
EncodedTitle=galleria%20prova
"""
G = "https://galleria.test"
ALBUM = f"{G}/album/123/Bella-Gita"


def album_page(photos, next_page=False):
    links = "".join(f'<a href="/foto/{p}/?a=123"><img src="{G}/piccole/{p}.jpg"></a>' for p in photos)
    nxt = f'<a href="{ALBUM}?p=1">avanti</a>' if next_page else ""
    return (f'<a href="/album/777/Menu">menu</a><div id="inizio">x</div>{links}{nxt}'
            f'<div id="preferiti"><a href="/album/999/Altro">altro</a></div>')


def photo_page(pid, alt):
    return (f'<a href="/foto/555/">nav</a><div id="inizio"></div>'
            f'<img src="https://cdn.galleria.test/grande/{pid}.jpg" alt="{alt}">'
            f'<div id="descrizione"><a href="/foto/999/">altra</a></div>')


def galleria(log=None):
    return site({
        ("GET", ALBUM): album_page([111, 222], next_page=True),
        ("GET", f"{ALBUM}?p=1"): album_page([333]),
        ("GET", f"{G}/foto/111/"): photo_page(111, "Tramonto al mare"),
        ("GET", f"{G}/foto/222/"): photo_page(222, "Montagna"),
        ("GET", f"{G}/foto/333/"): photo_page(333, "Lago"),
        ("GET", r"https://cdn\.galleria\.test/grande/\d+\.jpg"): (200, b"JPEG" * 10, {"content-type": "image/jpeg"}),
    }, log)


def test_galleria_parti_escluse_nome_alt_cartella(tmp_path):
    t = tpl(tmp_path, "galleria.etmpl", GALLERIA_TPL)
    log = []
    stats = run(tmp_path, t, ALBUM, galleria(log))
    assert stats["done"] == 3 and stats["failed"] == 0
    assert files(tmp_path) == {"123-Bella-Gita/Tramonto al mare.jpg", "123-Bella-Gita/Montagna.jpg",
                               "123-Bella-Gita/Lago.jpg"}
    visited = {u for _, u, _, _ in log}
    assert not any(x in u for u in visited for x in ("/777/", "/999/", "/555/", "/piccole/"))
    assert all(r and "/foto/" in r for _, u, _, r in log if "cdn.galleria" in u)     # referer naturale


def test_galleria_non_riscarica(tmp_path):
    t = tpl(tmp_path, "galleria.etmpl", GALLERIA_TPL)
    run(tmp_path, t, ALBUM, galleria())
    stats = run(tmp_path, t, ALBUM, galleria())
    assert stats["skipped"] == 3 and stats["done"] == 0      # rncDoNotSave


def test_opzioni_e_parti_escluse(tmp_path):
    t = Template.load(tpl(tmp_path, "galleria.etmpl", GALLERIA_TPL + "\n[Settings]\nUseMinFileSizeLimit=Flase\n"))
    o = t.options
    assert o["connections"] == 1 and o["delay"] == (2, 3) and o["conflicts"] == "do_not_save"
    assert "min_size" not in o
    out = t.strip_parts('AAA<div id="inizio">BBB<div id="preferiti">CCC')
    assert "AAA" not in out and "BBB" in out and "CCC" not in out


# ---------------------------------------------------------------- POST con JSON e file su un altro server
POST_TPL = r"""
[Settings]
ExplorationLimit=selEntireSite
[TargetFiles]
File000=*.mp4
[IncludedURLs]
URL000=/api/scarica$
URL001=^https://cdn\d\.dati\.test/f/
[CustomParsers]
Expression000=^https://dati\.test/d/([^\s/?#]+)
Address000=/api/scarica
RequestType000=POST
POSTData000=%7B%22slug%22%3A%22[#1]%22%7D
Expression001="file":"([^"]+)","name":"([^"]+)","server":"([^"]+)","token":"([^"]+)"
Address001=[#3]/f/[#jsonencode([#1])#]?token=[#4]&n=[#jsonencode([#2])#]
[CustomHTTPHeaders]
URLRegEx000=/api/
Name000_000=content-type
Type000_000=chvtText
Value000_000=application/json
Result000_000=
[ExcludedPageParts]
From000=<nav
To000=</nav>
[StartingURLTemplates]
URL000=dati\.test/d/
[TemplateSettings]
EncodedTitle=dati%20prova
"""


def test_post_json_e_file_su_altro_server(tmp_path):
    start = "https://dati.test/d/SlugX"
    log = []

    def api(req):
        assert json.loads(req.content) == {"slug": "SlugX"}
        assert req.headers["content-type"] == "application/json"
        return (200, '{"file":"abc 1.mp4","name":"Il mio video.mp4","server":"https://cdn1.dati.test","token":"T0K"}',
                {"content-type": "application/json"})

    stats = run(tmp_path, tpl(tmp_path, "dati.etmpl", POST_TPL), start, site({
        ("GET", start): '<nav><a href="/d/Altro">no</a></nav><main>file</main>',
        ("POST", "https://dati.test/api/scarica"): api,
        ("GET", r"https://cdn1\.dati\.test/f/abc%201\.mp4\?token=T0K&n=Il%20mio%20video\.mp4"):
            (200, b"MP4" * 30, {"content-type": "video/mp4",
                                 "content-disposition": "attachment; filename*=UTF-8''Il%20mio%20video.mp4"}),
    }, log))
    assert stats["done"] == 1 and files(tmp_path) == {"Il mio video.mp4"}
    assert not any("/d/Altro" in u for _, u, _, _ in log)


# ---------------------------------------------------------------- sessione del browser: intestazioni copiate
NUVOLA_TPL = r"""
[Settings]
ExplorationLimit=selEntireSite
ManualLogin=True
ManualLoginMessage=Aspetta di vedere la cartella, poi Continua
[TargetFiles]
File000=*.jpg
File001=*.mp4
[ExcludedURLs]
URL000=^https?://nuvola\.test
URL001=_mini\.
[IncludedURLs]
URL000=api\.nuvola\.test/cartelle/
[CustomParsers]
Expression000=(?m)^(https://[^/\r\n]+/cartelle/)[^/\?#]+(\?[^\r\n#]+)
Address000=/-/-/-/
Expression001={"id":"([^"{}]+)","type":"folder"
Address001=[#-1:1][#1][#-1:2]
[CustomHTTPReferers]
URLRegExp000=nuvola\.test
RefererType000=hrtSimpleText
Text000=https://nuvola.test/
CPRE000=
CPResult000=
[CustomHTTPHeaders]
URLRegEx000=api\.nuvola\.test/cartelle/
Name000_000=authorization
Type000_000=chvtCopyFromParent
Value000_000=api\.nuvola\.test/cartelle/
Result000_000=
Name000_001=origin
Type000_001=chvtText
Value000_001=https://nuvola.test
Result000_001=
[ExcludedPageParts]
From000="mini":"
To000="
[StartingURLTemplates]
URL000=nuvola\.test/d/
[TemplateSettings]
EncodedTitle=nuvola%20prova
"""


def test_sessione_del_browser_intestazioni_e_cookie(tmp_path):
    from picfinder.session import BrowserSession, CapturedRequest, Cookie
    q = "?wt=4fd"
    root = {"data": {"id": "abc", "children": {
        "s": {"id": "sub1", "type": "folder"},
        "f": {"id": "file1", "type": "file", "link": "https://dl1.nuvola.test/file1/a.jpg",
              "mini": "https://dl1.nuvola.test/a_mini.jpg"}}}}
    sub = {"data": {"id": "sub1", "children": {
        "g": {"id": "file2", "type": "file", "link": "https://dl1.nuvola.test/file2/b.mp4"}}}}
    session = BrowserSession(
        start_url="https://nuvola.test/d/abc", final_url="https://nuvola.test/d/abc", html="<html></html>",
        cookies=[Cookie("conto", "TOK", ".nuvola.test")],
        requests=[CapturedRequest(f"https://api.nuvola.test/cartelle/abc{q}", "GET", {"authorization": "Bearer TOK"},
                                  status=200, ctype="application/json", text=json.dumps(root, separators=(",", ":")))])
    log = []

    def api_sub(req):
        assert req.headers["authorization"] == "Bearer TOK"            # copiata dal browser
        assert req.headers["origin"] == "https://nuvola.test"          # testo fisso
        assert req.headers["referer"] == "https://nuvola.test/"
        return (200, json.dumps(sub, separators=(",", ":")), {"content-type": "application/json"})

    def store(req):
        assert "conto=TOK" in req.headers.get("cookie", "")
        return (200, b"X" * 20, {"content-type": "application/octet-stream"})

    t = site({("GET", f"https://api.nuvola.test/cartelle/sub1{q}"): api_sub,
              ("GET", r"https://dl1\.nuvola\.test/\w+/\w+\.\w+"): store}, log)
    plugin = EtmplPlugin(Template.load(tpl(tmp_path, "nuvola.etmpl", NUVOLA_TPL)))
    assert plugin.t.needs_browser() and plugin.t.warnings() and plugin.t.warnings(session=object()) == []
    dl = Downloader(tmp_path, transport=t)
    found = asyncio.run(dl.scan("https://nuvola.test/d/abc", plugin=plugin, session=session))
    assert sorted(f.name for f in found) == ["a.jpg", "b.mp4"]
    assert dl.cookie_header("https://dl1.nuvola.test/x") == "conto=TOK" and dl.cookie_header("https://altro.x/") == ""
    assert not any("cartelle/abc" in u or "_mini" in u for _, u, _, _ in log)   # già nel browser / esclusa
    assert asyncio.run(dl.download(found))["done"] == 2


def test_risorse_della_pagina_non_esplorate(tmp_path):
    t = Template.load(tpl(tmp_path, "nuvola.etmpl", NUVOLA_TPL))
    page = ('<link rel="stylesheet" href="https://s.nuvola.test/app.css">'
            '<script src="https://s.nuvola.test/js/script.js"></script>'
            '<img src="https://dl1.nuvola.test/x/mini_senza_estensione">'
            '<img src="https://dl1.nuvola.test/y/foto.jpg">')
    start = "https://nuvola.test/d/abc"
    ok = [l.url for l in t.extract(start, page)
          if t.why_not(l.url, start, target=t.is_target(l.url)) is None and (not l.resource or t.is_target(l.url))]
    assert ok == ["https://dl1.nuvola.test/y/foto.jpg"]


def test_json_nomi_con_parentesi(tmp_path):
    t = Template.load(tpl(tmp_path, "nuvola.etmpl", NUVOLA_TPL))
    url = "https://dl1.nuvola.test/ea538f72/Foto%20(1).jpg"
    txt = json.dumps({"data": {"children": {"a": {"type": "file", "name": "Foto (1).jpg", "link": url}}}})
    got = [l.url for l in t.extract("https://api.nuvola.test/cartelle/x?p=1", txt, "") if "ea538f72" in l.url]
    assert got == [url] and t.is_target(url)


def test_risposte_api_dal_browser_senza_rete(tmp_path):
    """Con la sessione del browser: file interi dalle risposte già catturate, niente miniature della pagina."""
    from picfinder.session import BrowserSession, CapturedRequest
    api_url = "https://fan.test/api/media?limit=10"
    media = {"list": [{"files": {"full": {"url": "https://cdn.fan.test/a/intero1.jpg?P=1"},
                                 "anteprima": {"url": "https://cdn.fan.test/a/pic_300x300.jpg?P=1"}}},
                      {"files": {"full": {"url": "https://cdn.fan.test/b/intero2.jpg?P=2"}}}]}
    t = tpl(tmp_path, "fan.etmpl", r"""
[Settings]
ExplorationLimit=selEntireSite
ManualLogin=True
[TargetFiles]
File000=*.jpg
[ExcludedURLs]
URL000=_\d+x\d+\.
URL001=^https://fan\.test/(?!api/)
[IncludedURLs]
URL000=fan\.test/api/media
[StartingURLTemplates]
URL000=fan\.test/[^/]+/media
[TemplateSettings]
EncodedTitle=fan%20prova
""")
    session = BrowserSession(
        start_url="https://fan.test/nome/media", final_url="https://fan.test/nome/media",
        html='<img src="https://cdn.fan.test/a/pic_300x300.jpg?P=1">',
        requests=[CapturedRequest(api_url, "GET", {"sign": "S"}, status=200, ctype="application/json",
                                  text=json.dumps(media, separators=(",", ":")))])
    log = []
    dl = Downloader(tmp_path, transport=site({}, log))
    found = asyncio.run(dl.scan("https://fan.test/nome/media", plugin=EtmplPlugin(Template.load(t)), session=session))
    assert sorted(f.name for f in found) == ["intero1.jpg", "intero2.jpg"]
    assert log == []


# ---------------------------------------------------------------- template dell'utente: copie e versioni
def test_copia_vecchia_non_nasconde_la_versione_nuova(tmp_path, monkeypatch):
    from picfinder import plugins
    base = POST_TPL + "\nTemplateDatabaseID=4242\nTemplateDatabaseVersion={v}\n"
    extra = tmp_path / "extra"
    extra.mkdir()
    (extra / "dati (2).etmpl").write_text(base.format(v=13), encoding="utf-8")
    mine = plugins.user_templates_dir()
    mine.mkdir(parents=True, exist_ok=True)
    (mine / "dati.etmpl").write_text(base.format(v=18), encoding="utf-8")
    monkeypatch.setenv("PICFINDER_TEMPLATES", str(extra))
    plugins.reload()
    found = [p for p in plugins.all_plugins() if getattr(p, "t", None) is not None and p.t.db_id == "4242"]
    assert len(found) == 1 and found[0].t.db_version == 18
    assert any("dati (2)" in x for x in plugins.superseded())
    monkeypatch.delenv("PICFINDER_TEMPLATES")
    plugins.reload()


# ---------------------------------------------------------------- pezzi del motore
def test_riferimenti_relativi_e_funzioni():
    a = re.search(r"(x)(y)", "xy")
    b = re.search(r"(z)", "z")
    assert expand("[#+1:1]", a, [a, b], idx=0) == "z"
    assert expand("[#base64decode(aGVsbG8=)#]-[#dectohex(255)#]-[#hextodec(ff)#]", None, []) == "hello-ff-255"


def test_stesso_sito_con_sottodomini():
    from picfinder.etmpl import site_of
    assert site_of("https://cdn1.filester.me/x") == site_of("https://filester.me/d/y") == "filester.me"
    assert site_of("https://a.b.co.uk/x") == "b.co.uk"
    assert site_of("https://brainless.bunkr.ru/x") != site_of("https://bunkr.cr/a/1")


def test_stesso_file_su_server_diversi_contato_una_volta():
    from picfinder.core import mirror_key
    a = "https://store8.gofile.io/download/web/ID1/a.mp4"
    b = "https://file-na-lax-1.gofile.io/download/web/ID1/a.mp4"
    assert mirror_key(a) == mirror_key(b)
    assert mirror_key(a) != mirror_key("https://store8.gofile.io/download/web/ID2/a.mp4")
    assert mirror_key(a) != mirror_key("https://store8.altrosito.io/download/web/ID1/a.mp4")


def test_titolo_pagina():
    from picfinder.etmpl import page_title
    assert page_title("<title>B Jade | filester.me</title>", "https://filester.me/f/x") == "B Jade"
    assert page_title('<meta property="og:title" content="Gita: mare/monti &amp; co - Bunkr">', "https://bunkr.cr/a/x") \
        == "Gita- mare-monti & co"
    assert page_title("<p>niente</p>", "https://x.y/") == ""


def test_cartella_per_link_col_nome_dell_album():
    from picfinder.core import organize
    from picfinder.etmpl import json_title, page_title
    assert page_title("<title>Gofile — Cloud Storage Made Simple</title>", "https://gofile.io/d/x") == ""
    assert json_title('{"status":"ok","data":{"type":"folder","name":"Sazwel","children":{}}}') == "Sazwel"
    assert organize("", "https://gofile.io/d/FZlT7mKQ", "a.jpg", True, True, album="Sazwel") == "Sazwel/Foto"
    assert organize("", "https://gofile.io/d/FZlT7mKQ", "a.jpg", True, True) == "FZlT7mKQ/Foto"
    assert organize("", "https://onlyfans.com/mario/media", "a.jpg", True, True, album="Mario (@mario)") == "mario/Foto"


# ---------------------------------------------------------------- plugin Python pixeldrain (API)
def test_pixeldrain_api_veloce(tmp_path):
    from picfinder.plugins import find_plugin
    lista = "https://pixeldrain.com/l/Lista9"
    assert find_plugin(lista).KEY == "python/pixeldrain"
    calls = []
    api = {"success": True, "id": "Lista9", "title": "Mare",
           "files": [{"id": "aaa111", "name": "Spiaggia.jpg", "size": 200},
                     {"id": "bbb222", "name": "Onde.mp4", "size": 150},
                     {"id": "ccc333", "name": "Note.txt", "size": 10}]}
    t = site({
        ("GET", "https://pixeldrain.com/api/list/Lista9"): (200, json.dumps(api), {"content-type": "application/json"}),
        ("GET", r"https://pixeldrain\.com/api/file/\w+\?download"): (200, b"D" * 10, {"content-type": "application/octet-stream"}),
    }, calls)
    dl = Downloader(tmp_path / "out", transport=t)
    found = asyncio.run(dl.scan(lista))
    assert [f.name for f in found] == ["Spiaggia.jpg", "Onde.mp4"]
    assert found[1].thumb == "https://pixeldrain.com/api/file/bbb222/thumbnail"
    assert len(calls) == 1
    asyncio.run(dl.download(found))
    assert files(tmp_path) == {"Mare/Spiaggia.jpg", "Mare/Onde.mp4"}


def test_pixeldrain_lista_inesistente(tmp_path):
    from picfinder.core import PluginError
    with pytest.raises(PluginError, match="non trovato"):
        asyncio.run(Downloader(tmp_path, transport=site({})).scan("https://pixeldrain.com/l/Nope"))
