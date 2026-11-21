"""Plugin Python dei siti (codice nostro): Bunkr, filester, Gofile, OnlyFans, Fansly, ImageFap, Tumblr.
Ogni test usa pagine finte costruite come quelle vere (novembre 2026)."""
import asyncio
import json

import httpx
import pytest

from picfinder import plugins


def run(plugin, url, handler, session=None, password=None):
    async def go():
        plugin.pause_scale = 0.0001          # niente pause nei test
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            if getattr(plugin, "ACCEPTS_SESSION", False):
                gen = plugin.list_files(c, url, password, session=session)
            else:
                gen = plugin.list_files(c, url, password)
            return [f async for f in gen]
    return asyncio.run(go())


# ------------------------------------------------------------------ Bunkr
def _bunkr_handler(seen):
    album = ('<title>Vacanze 2024 | Bunkr</title>'
             '<div><a href="/f/PH1"></a><p class="truncate theName text-center">mare.jpg</p></div>'
             '<div><a href="/f/VID"></a><p class="truncate theName text-center">onde.mp4</p></div>')

    def h(req):
        u = str(req.url)
        seen.append(u)
        if u.endswith("/a/ALB"):
            return httpx.Response(200, text=album, headers={"content-type": "text/html"})
        if u.endswith("/api/album/gallery"):
            assert json.loads(req.content) == {"slug": "ALB"}
            return httpx.Response(200, json={"data": [{"id": 11, "name": "mare.jpg", "image_url": "x"}]})
        if "/f/VID" in u:
            return httpx.Response(200, text='<a class="btn" href="https://dl.bunkr.cr/file/22">Download</a>')
        if u.endswith("/api/_001_v2"):
            fid = json.loads(req.content)["id"]
            name = {"11": "mare.jpg", "22": "onde.mp4"}[fid]
            return httpx.Response(200, json={"mediafiles": "https://c6.cdn.cr", "original": name,
                                             "path": f"/storage/media/u{fid}.{name.rsplit('.', 1)[1]}"})
        if "glb-apisign.cdn.cr/sign" in u:
            return httpx.Response(200, json={"token": "T", "ex": 9})
        return httpx.Response(404)
    return h


def test_bunkr_album_foto_veloci_video_dalla_pagina():
    p = plugins.find_plugin("https://bunkr.cr/a/ALB")
    assert p.KEY == "python/bunkr"
    seen = []
    files = run(p, "https://bunkr.cr/a/ALB", _bunkr_handler(seen))
    assert [f.name for f in files] == ["mare.jpg", "onde.mp4"]
    assert {f.subdir for f in files} == {"Vacanze 2024"}
    assert files[0].url == "https://c6.cdn.cr/storage/media/u11.jpg?n=mare.jpg&token=T&ex=9"
    assert not any("/f/PH1" in u for u in seen)          # la foto salta la sua pagina
    assert any("/f/VID" in u for u in seen)              # il video no


def test_bunkr_file_singolo_e_formato_vecchio():
    import base64
    key = b"SECRET_KEY_" + str(1773480000 // 3600).encode()
    real = b"https://cdn.old/x.jpg"
    enc = base64.b64encode(bytes(b ^ key[i % len(key)] for i, b in enumerate(real))).decode()

    def h(req):
        u = str(req.url)
        if "/f/ONE" in u:
            return httpx.Response(200, text='<a href="https://dl.bunkr.si/file/5">Download</a>')
        if u.endswith("/api/_001_v2"):
            return httpx.Response(200, json={"encrypted": True, "timestamp": 1773480000, "url": enc})
        return httpx.Response(404)
    files = run(plugins.find_plugin("https://bunkr.si/f/ONE"), "https://bunkr.si/f/ONE", h)
    assert [f.url for f in files] == ["https://cdn.old/x.jpg"]


# ------------------------------------------------------------------ filester
def test_filester_cartella_vera_salvata():
    """Pagina vera di una cartella (salvata dal registro), con 10 file."""
    from pathlib import Path
    saved = Path("/mnt/user-data/uploads/Desktop/picfinder/log/pagine/20261121-140355-filester.me-1.html")
    if not saved.exists():
        pytest.skip("pagina di prova non disponibile")
    from picfinder.plugins.filester import _items
    items = _items(saved.read_text(encoding="utf-8", errors="replace"))
    assert len(items) == 10 and all(k == "d" and n for k, _, n in items)


def test_filester_cartella_con_sottocartella_e_pagine():
    page1 = ('<title>B Jade | filester.me</title>'
             '<div class="file-item" data-type="images" data-name="a.jpg" onclick="window.location.href=\'/d/AAA\'">a</div>'
             '<div class="file-item folder" data-name="Extra" onclick="window.location.href=\'/f/SUB\'">x</div>'
             '<a href="?page=2">2</a>')
    page2 = '<div class="file-item" data-name="b.mp4" onclick="window.location.href=\'/d/BBB\'">b</div>'
    sub = '<title>Extra | filester.me</title><div class="file-item" data-name="c.png" onclick="window.location.href=\'/d/CCC\'">c</div>'

    def h(req):
        u = str(req.url)
        if u.endswith("/f/ba6c") :
            return httpx.Response(200, text=page1)
        if u.endswith("/f/ba6c?page=2"):
            return httpx.Response(200, text=page2)
        if u.endswith("/f/SUB"):
            return httpx.Response(200, text=sub)
        if u.endswith("/v2/api/public/download"):
            slug = json.loads(req.content)["file_slug"]
            name = {"AAA": "a.jpg", "BBB": "b.mp4", "CCC": "c.png"}[slug]
            return httpx.Response(200, json={"file": f"id-{slug}.{name[-3:]}", "name": name,
                                             "server": "https://fsc3.cdn.cr", "success": True, "token": "TK"})
        return httpx.Response(404)
    p = plugins.find_plugin("https://filester.me/f/ba6c")
    assert p.KEY == "python/filester"
    files = run(p, "https://filester.me/f/ba6c", h)
    assert [(f.name, f.subdir) for f in files] == [("a.jpg", "B Jade"), ("c.png", "B Jade/Extra"), ("b.mp4", "B Jade")]
    assert files[0].url == "https://fsc3.cdn.cr/v2/id-AAA.jpg?token=TK&download=true&n=a.jpg"


# ------------------------------------------------------------------ Gofile
def test_gofile_cartelle_e_pagine_con_token_del_browser():
    from picfinder.session import BrowserSession, CapturedRequest
    root_url = "https://api.gofile.io/contents/FZl?page=1&pageSize=100&sortField=name&sortDirection=1"
    root = {"status": "ok", "data": {"id": "r", "type": "folder", "name": "Sazwel", "children": {
        "a": {"type": "file", "name": "Sazwel (1).jpg", "link": "https://file-eu-1.gofile.io/download/web/a/Sazwel (1).jpg"},
        "s": {"type": "folder", "id": "SUB", "name": "Extra"}}}}
    s = BrowserSession("https://gofile.io/d/FZl", requests=[CapturedRequest(
        root_url, headers={"authorization": "Bearer TOK", "x-website-token": "WT"}, status=200,
        ctype="application/json", text=json.dumps(root))])
    calls = []

    def h(req):
        calls.append(str(req.url))
        assert req.headers["authorization"] == "Bearer TOK" and req.headers["x-website-token"] == "WT"
        page = req.url.params["page"]
        if page == "1":
            return httpx.Response(200, json={"status": "ok", "data": {"name": "Extra", "metadata": {"hasNextPage": True},
                                  "children": {"b": {"type": "file", "name": "b.mp4", "link": "https://f/b.mp4"}}}})
        return httpx.Response(200, json={"status": "ok", "data": {"name": "Extra", "children": {
            "c": {"type": "file", "name": "c.mp4", "link": "https://f/c.mp4"}}}})
    files = run(plugins.find_plugin("https://gofile.io/d/FZl"), "https://gofile.io/d/FZl", h, session=s)
    assert [(f.name, f.subdir) for f in files] == [("Sazwel (1).jpg", "Sazwel"), ("b.mp4", "Sazwel/Extra"),
                                                  ("c.mp4", "Sazwel/Extra")]
    assert len(calls) == 2                       # la cartella principale c'era già dal browser
    assert s.add_token_cookies() == ["accountToken"]


def test_gofile_senza_browser_spiega_cosa_fare():
    from picfinder.core import PluginError
    with pytest.raises(PluginError, match="browser"):
        run(plugins.find_plugin("https://gofile.io/d/X"), "https://gofile.io/d/X", lambda r: httpx.Response(404))


# ------------------------------------------------------------------ OnlyFans
def _of_session(chat=False):
    from picfinder.session import BrowserSession, CapturedRequest
    page1 = {"list": [{"id": 1, "postedAt": "2026-03-14T09:20:00+00:00", "rawText": "Ciao",
                       "media": [{"id": 10, "type": "photo", "canView": True,
                                  "files": {"full": {"url": "https://cdn2.onlyfans.com/files/a/abc_source.jpg?Policy=x"},
                                            "thumb": {"url": "https://cdn2.onlyfans.com/thumb.jpg"}}},
                                 {"id": 11, "type": "video", "canView": False, "files": {}},
                                 {"id": 12, "type": "video", "canView": True, "files": {"full": {"url": None}, "drm": {"manifest": {}}}}]}],
             "hasMore": True}
    page2_url = "https://onlyfans.com/api2/v2/users/77/posts/medias?limit=24&beforePublishTime=1"
    base = "https://onlyfans.com/api2/v2/chats/555/media?limit=24" if chat else "https://onlyfans.com/api2/v2/users/77/posts/medias?limit=24"
    reqs = [CapturedRequest(base, headers={"sign": "S1", "time": "1", "app-token": "A"}, status=200,
                            ctype="application/json", text=json.dumps(page1))]
    if not chat:
        reqs.append(CapturedRequest(page2_url, headers={"sign": "S2", "time": "2", "app-token": "A"}))
    reqs.append(CapturedRequest("https://onlyfans.com/api2/v2/users/me", headers={}, status=200, text="{}"))
    return BrowserSession("https://onlyfans.com/mario/media", requests=reqs)


def test_onlyfans_profilo_media_interi_niente_bloccati_niente_drm():
    seen = []

    def h(req):
        seen.append((str(req.url), req.headers.get("sign")))
        return httpx.Response(200, json={"list": [{"id": 2, "media": [{"id": 20, "type": "video", "canView": True,
                              "source": {"source": "https://cdn3.onlyfans.com/files/v/vid_source.mp4?Policy=y"}}]}]})
    p = plugins.find_plugin("https://onlyfans.com/mario/media")
    assert p.KEY == "python/onlyfans"
    files = run(p, "https://onlyfans.com/mario/media", h, session=_of_session())
    assert [f.name for f in files] == ["abc_source.jpg", "vid_source.mp4"]
    assert files[0].meta.get("caption") == "Ciao"
    assert seen == [("https://onlyfans.com/api2/v2/users/77/posts/medias?limit=24&beforePublishTime=1", "S2")]


def test_onlyfans_chat():
    p = plugins.find_plugin("https://onlyfans.com/my/chats/chat/555/")
    assert p.KEY == "python/onlyfans"
    files = run(p, "https://onlyfans.com/my/chats/chat/555/", lambda r: httpx.Response(404),
                session=_of_session(chat=True))
    assert [f.name for f in files] == ["abc_source.jpg"]


def test_onlyfans_senza_pagine_caricate_spiega():
    from picfinder.core import PluginError
    from picfinder.session import BrowserSession
    with pytest.raises(PluginError, match="scorri"):
        run(plugins.find_plugin("https://onlyfans.com/mario"), "https://onlyfans.com/mario",
            lambda r: httpx.Response(404), session=BrowserSession("https://onlyfans.com/mario"))


# ------------------------------------------------------------------ Fansly
def test_fansly_pagine_con_before_e_solo_versione_intera():
    from picfinder.session import BrowserSession, CapturedRequest
    first = "https://apiv3.fansly.com/api/v1/mediaoffers/location?accountId=1&mediaType=&before=&after=0&limit=30&offset=0"
    s = BrowserSession("https://fansly.com/mario/media", requests=[CapturedRequest(first, headers={
        "authorization": "AUTH", "fansly-client-id": "C"})])
    calls = []

    def h(req):
        calls.append(dict(req.url.params))
        assert req.headers["authorization"] == "AUTH"
        if req.url.params["before"] == "":
            return httpx.Response(200, json={"response": {"data": [{"id": "5"}, {"id": "4"}], "accountMedia": [
                {"media": {"filename": "a.jpg", "locations": [{"location": "https://cdn3.fansly.com/a.jpg?x"}],
                           "variants": [{"locations": [{"location": "https://cdn3.fansly.com/a_small.jpg"}]}]}}]}})
        if req.url.params["before"] == "4":
            return httpx.Response(200, json={"response": {"data": [{"id": "3"}], "accountMedia": [
                {"media": {"filename": "b.mp4", "locations": [{"location": "https://cdn3.fansly.com/b.mp4?x"}]}}]}})
        return httpx.Response(200, json={"response": {"data": [], "accountMedia": []}})
    files = run(plugins.find_plugin("https://fansly.com/mario/media"), "https://fansly.com/mario/media", h, session=s)
    assert [f.name for f in files] == ["a.jpg", "b.mp4"]
    assert [c["before"] for c in calls] == ["", "4", "3"]


# ------------------------------------------------------------------ Tumblr
def test_tumblr_misura_piu_grande_e_pagine():
    from picfinder.session import BrowserSession, CapturedRequest
    first = "https://www.tumblr.com/api/v2/blog/mario/posts?fields=x"
    s = BrowserSession("https://www.tumblr.com/mario", requests=[CapturedRequest(first, headers={"authorization": "Bearer T"})])

    def h(req):
        if "page2" in str(req.url):
            return httpx.Response(200, json={"response": {"posts": [{"content": [
                {"type": "video", "url": "https://va.media.tumblr.com/v.mp4"}]}], "links": {}}})
        return httpx.Response(200, json={"response": {"posts": [{"blog": {"avatar": [{"url": "https://64.media.tumblr.com/av.png"}]},
            "content": [{"type": "image", "media": [{"url": "https://64.media.tumblr.com/s400.jpg", "width": 400, "height": 300},
                                                    {"url": "https://64.media.tumblr.com/s1280.jpg", "width": 1280, "height": 960}]}]}],
            "links": {"next": {"href": "/v2/blog/mario/posts?page2=1"}}}})
    files = run(plugins.find_plugin("https://www.tumblr.com/mario"), "https://www.tumblr.com/mario", h, session=s)
    assert [f.url for f in files] == ["https://64.media.tumblr.com/s1280.jpg", "https://va.media.tumblr.com/v.mp4"]
    assert {f.subdir for f in files} == {"mario"}


# ------------------------------------------------------------------ ImageFap
def test_imagefap_galleria_pagine_e_foto_intere():
    def h(req):
        u = str(req.url)
        if "/pictures/123/" in u and "page=1" not in u:
            return httpx.Response(200, text='<title>Montagne Porn Pics</title><a href="/photo/1/?pgid=&gid=123&page=0">1</a>'
                                            '<a href="/pictures/123/x?gid=123&amp;page=1&amp;view=0">2</a>')
        if "page=1" in u:
            return httpx.Response(200, text='<a href="/photo/2/?pgid=&gid=123&page=1">2</a>')
        if "/photo/1/" in u:
            return httpx.Response(200, text='<img id="mainPhoto" alt="vetta.jpg" src="https://cdn.imagefap.com/images/full/1/vetta.jpg">')
        if "/photo/2/" in u:
            return httpx.Response(200, text='<a href="https://cdn.imagefap.com/images/full/2/lago.png">x</a>')
        return httpx.Response(404)
    p = plugins.find_plugin("https://www.imagefap.com/pictures/123/Montagne")
    assert p.KEY == "python/imagefap"
    files = run(p, "https://www.imagefap.com/pictures/123/Montagne", h)
    assert [(f.name, f.url) for f in files] == [("vetta.jpg", "https://cdn.imagefap.com/images/full/1/vetta.jpg"),
                                               ("lago.png", "https://cdn.imagefap.com/images/full/2/lago.png")]


# ------------------------------------------------------------------ happymodal
def test_happymodal_elenco_pagine_e_gallerie():
    p = plugins.find_plugin("https://happymodal.com/")
    assert p.NAME == "happymodal"
    seen = []
    H = "https://happymodal.com"

    def listing(gals, nxt=None):
        items = "".join(f'<a href="/p/{g}/"><img src="/thumb/{g}.jpg"></a>' for g in gals)
        more = f'<a href="/page/{nxt}/">avanti</a>' if nxt else ""
        return (f'<header><a href="/p/999/">menu</a></header><div class="grid" data-lib-grid>{items}{more}</div>'
                f'<aside><a href="/p/888/">laterale</a></aside><footer><a href="/page/50/">x</a></footer>')

    def gallery(n):
        return (f'<title>Set {n} - HappyModal</title><a href="/img/x/menu.jpg">no</a><div class="gallery">'
                f'<a href="/img/{n}/a.jpg"><img src="/img/{n}/a_small.jpg"></a>'
                f'<a href="https://happymodal.com/img/{n}/b.webp"><img src="/s.jpg"></a>'
                f'<a href="/p/{n}/?share=1">condividi</a></div><aside><a href="/img/z/ads.jpg">ad</a></aside>')

    def h(req):
        u = str(req.url)
        seen.append(u)
        if u == f"{H}/":
            return httpx.Response(200, text=listing([1, 2], nxt=2))
        if u == f"{H}/page/2/":
            return httpx.Response(200, text=listing([3]))
        m = __import__("re").search(r"/p/(\d+)/$", u)
        if m:
            return httpx.Response(200, text=gallery(m.group(1)))
        return httpx.Response(404)

    files = run(p, f"{H}/", h)
    assert [(f.subdir, f.name) for f in files] == [
        ("Set 1", "a.jpg"), ("Set 1", "b.webp"), ("Set 2", "a.jpg"), ("Set 2", "b.webp"),
        ("Set 3", "a.jpg"), ("Set 3", "b.webp")]
    assert not any(x in u for u in seen for x in ("/p/999/", "/p/888/", "/page/50/"))
    assert files[0].headers["Referer"] == f"{H}/p/1/"


def test_happymodal_galleria_vuota_spiega():
    p = plugins.find_plugin("https://www.happymodal.com/p/5/")
    with pytest.raises(plugins.PluginError if hasattr(plugins, "PluginError") else Exception, match="nessuna foto"):
        run(p, "https://www.happymodal.com/p/5/", lambda r: httpx.Response(200, text="<div class='x'></div>"))


# ------------------------------------------------------------------ blinkgirl
def test_blinkgirl_elenco_e_articolo():
    B = "https://blinkgirl.com"
    p = plugins.find_plugin(f"{B}/")
    assert p.NAME == "blinkgirl"

    def h(req):
        u = str(req.url)
        if u == f"{B}/":
            return httpx.Response(200, text='<a href="/menu-x/">m</a><div class="tdb_module_loop">'
                                            '<span class="entry-thumb"><a href="/set-uno/">x</a></span>'
                                            '<a href="/set-uno/">uno</a><a href="/page/2/">2</a></div>'
                                            '<div class="td-footer-template-wrap"><a href="/footer/">f</a></div>')
        if u == f"{B}/page/2/":
            return httpx.Response(200, text='<div class="tdb_module_loop"><a href="/set-due/">due</a></div>')
        if u.endswith("/set-uno/"):
            return httpx.Response(200, text='<title>Set Uno - BlinkGirl</title><img src="/logo.jpg">'
                                            '<figure class="wp-block-gallery"><a href="/wp/a.jpg"><img src="/wp/a-300x200.jpg"></a>'
                                            '<a href="/wp/b.jpg"><img src="/wp/b-300x200.jpg"></a></figure>'
                                            '<div class="x" id="comments"><a href="/wp/c.jpg">c</a></div>')
        if u.endswith("/set-due/"):
            return httpx.Response(200, text='<title>Set Due - BlinkGirl</title><figure class="wp-block-gallery">'
                                            '<img data-src="/wp/d.webp" src="data:image/gif;base64,x"></figure>')
        return httpx.Response(404)

    files = run(p, f"{B}/", h)
    assert [(f.subdir, f.name) for f in files] == [("Set Uno", "a.jpg"), ("Set Uno", "b.jpg"), ("Set Due", "d.webp")]


# ------------------------------------------------------------------ jliji
def test_jliji_set_con_pagine_senza_miniature():
    J = "https://jliji.com"
    p = plugins.find_plugin(f"{J}/set/42")

    def page(n, nxt):
        more = f'<a href="/set/42?page={nxt}">{nxt}</a>' if nxt else ""
        return (f'<title>Bel set - jliji</title><div class="gallery-grid">'
                f'<a href="https://img.jliji.test/42/{n}.jpg"><img src="https://img.jliji.test/thumbs/42/{n}.jpg"></a>'
                f'{more}</div><div class="related-sets"><a href="/set/99">x</a></div>')

    seen = []

    def h(req):
        u = str(req.url)
        seen.append(u)
        if u == f"{J}/set/42":
            return httpx.Response(200, text=page(1, 2))
        if u == f"{J}/set/42?page=2":
            return httpx.Response(200, text=page(2, None))
        return httpx.Response(404)

    files = run(p, f"{J}/set/42", h)
    assert [(f.subdir, f.name) for f in files] == [("Bel set", "1.jpg"), ("Bel set", "2.jpg")]
    assert not any("/set/99" in u for u in seen)


# ------------------------------------------------------------------ gedecomix
def test_gedecomix_fumetto_capitoli_in_ordine():
    G = "https://gedecomix.com"
    p = plugins.find_plugin(f"{G}/porncomic/storia-bella/")
    comic = ('<title>Storia Bella - Gedecomix</title><a href="/porncomic/storia-bella/capitolo-9/">menu</a>'
             '<ul class="main version-chap"><li><a href="/porncomic/storia-bella/capitolo-2/">2</a></li>'
             '<li><a href="/porncomic/storia-bella/capitolo-1/">1</a></li></ul><button id="clear-read-status">x</button>')

    def chapter(n):
        return ('<div class="reading-content">'
                f'<img id="image-0" data-src=" https://gedecomix.com/static/WP-manga/data/m/{n}/p01.jpg " src="x.gif">'
                f'<img id="image-1" src="https://gedecomix.com/static/WP-manga/data/m/{n}/p02.png">'
                '<img src="https://gedecomix.com/ads/banner.jpg"></div>'
                '<div class="nav" id="manga-reading-nav-foot" data-position="footer"><img src="/static/WP-manga/data/no.jpg"></div>')

    def h(req):
        u = str(req.url)
        if u == f"{G}/porncomic/storia-bella/":
            return httpx.Response(200, text=comic)
        m = __import__("re").search(r"capitolo-(\d+)/$", u)
        if m:
            return httpx.Response(200, text=chapter(m.group(1)))
        return httpx.Response(404)

    files = run(p, f"{G}/porncomic/storia-bella/", h)
    assert [(f.subdir, f.name) for f in files] == [
        ("Storia Bella/capitolo 1", "001.jpg"), ("Storia Bella/capitolo 1", "002.png"),
        ("Storia Bella/capitolo 2", "001.jpg"), ("Storia Bella/capitolo 2", "002.png")]
    assert files[0].url == "https://gedecomix.com/static/WP-manga/data/m/1/p01.jpg"


def test_gedecomix_capitoli_via_ajax():
    G = "https://gedecomix.com"
    p = plugins.find_plugin(f"{G}/porncomic/altra/")

    def h(req):
        u = str(req.url)
        if u == f"{G}/porncomic/altra/":
            return httpx.Response(200, text='<title>Altra - Gedecomix</title><div id="manga-chapters-holder"></div>')
        if u == f"{G}/porncomic/altra/ajax/chapters/" and req.method == "POST":
            return httpx.Response(200, text='<ul class="main version-chap"><li><a href="/porncomic/altra/ch-1/">1</a></li></ul>')
        if u.endswith("/ch-1/"):
            return httpx.Response(200, text='<div class="reading-content"><img src="/static/WP-manga/data/a/1.jpg"></div>')
        return httpx.Response(404)

    files = run(p, f"{G}/porncomic/altra/", h)
    assert [(f.subdir, f.name) for f in files] == [("Altra/ch 1", "001.jpg")]


# ------------------------------------------------------------------ av01
def test_av01_token_dal_browser_e_video_hls():
    from picfinder.core import is_hls
    from picfinder.session import BrowserSession, CapturedRequest
    page = "https://www.av01.media/it/video/12345/titolo-video"
    p = plugins.find_plugin(page)
    assert p.NAME.startswith("av01") and plugins.needs_browser(p)
    session = BrowserSession(
        start_url=page, final_url=page, html="<title>Titolo del video - AV01</title>",
        requests=[CapturedRequest("https://www.av01.media/api/v1/videos/12345/cdn-access?token_v2=abc", "GET", {},
                                  status=200, ctype="application/json",
                                  text='{"access_token":"TOK.1","expires_at":1999999999}')])
    files = run(p, page, lambda r: httpx.Response(404), session=session)
    assert len(files) == 1
    f = files[0]
    assert f.url == "https://www.av01.media/api/v1/videos/12345/manifest/master.m3u8?access_token=TOK.1"
    assert f.name == "Titolo del video [12345].mp4" and is_hls(f) and f.headers["Referer"] == page


def test_av01_senza_lettore_spiega():
    from picfinder.session import BrowserSession
    page = "https://www.av01.media/video/1/x"
    with pytest.raises(Exception, match="lettore video"):
        run(plugins.find_plugin(page), page, lambda r: httpx.Response(404),
            session=BrowserSession(start_url=page, final_url=page, html=""))


# ------------------------------------------------------------------ X (Twitter)
def _x_page(tweets, cursor):
    entries = [{"content": {"itemContent": {"__typename": "TimelineTweet", "tweet_results": {"result": t}}}}
               for t in tweets]
    if cursor:
        entries.append({"content": {"__typename": "TimelineTimelineCursor", "cursorType": "Bottom",
                                    "entryType": "TimelineTimelineCursor", "value": cursor}})
    return {"data": {"user": {"result": {"timeline": {"timeline": {"instructions": [{"entries": entries}]}}}}}}


def _x_tweet(tid, user, media):
    return {"__typename": "Tweet", "rest_id": tid,
            "core": {"user_results": {"result": {"legacy": {"screen_name": user}}}},
            "legacy": {"id_str": tid, "created_at": "Wed Oct 10 20:19:24 +0000 2018", "full_text": f"post {tid}",
                       "extended_entities": {"media": media}}}


def test_x_media_pagine_con_cursore_e_foto_originali():
    import urllib.parse
    from picfinder.session import BrowserSession, CapturedRequest
    p = plugins.find_plugin("https://x.com/Nome_1/media")
    assert p.NAME.startswith("X") and plugins.needs_browser(p)
    assert plugins.find_plugin("https://x.com/home") is None or plugins.find_plugin("https://x.com/home").NAME != p.NAME
    var = urllib.parse.quote('{"userId":"1","count":20,"includePromotedContent":false}')
    api = f"https://x.com/i/api/graphql/AbC/UserMedia?variables={var}&features=%7B%7D"
    photo = {"type": "photo", "media_key": "3_1", "media_url_https": "https://pbs.twimg.com/media/FOTO1.jpg"}
    video = {"type": "video", "media_key": "7_2", "video_info": {"variants": [
        {"content_type": "application/x-mpegURL", "url": "https://video.twimg.com/x.m3u8"},
        {"content_type": "video/mp4", "bitrate": 832000, "url": "https://video.twimg.com/v/320/vid.mp4?tag=1"},
        {"content_type": "video/mp4", "bitrate": 2176000, "url": "https://video.twimg.com/v/720/vid.mp4?tag=1"}]}}
    page1 = _x_page([_x_tweet("100", "Nome_1", [photo]), _x_tweet("101", "Altro", [
        {"type": "photo", "media_key": "3_9", "media_url_https": "https://pbs.twimg.com/media/ALTRO.png"}])], "C2")
    page2 = _x_page([_x_tweet("102", "Nome_1", [video, photo])], "C3")
    page3 = _x_page([], "C3")
    seen = []

    def h(req):
        u = str(req.url)
        seen.append(u)
        assert req.headers["authorization"] == "Bearer AAA" and req.headers["x-csrf-token"] == "csrf"
        v = json.loads(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))["variables"])
        assert v["userId"] == "1" and v["count"] == 20
        return httpx.Response(200, json={"C2": page2, "C3": page3}[v["cursor"]])

    session = BrowserSession(
        start_url="https://x.com/Nome_1/media", final_url="https://x.com/Nome_1/media", html="",
        requests=[CapturedRequest(api, "GET", {"authorization": "Bearer AAA", "x-csrf-token": "csrf", "cookie": "no"},
                                  status=200, ctype="application/json", text=json.dumps(page1))])
    files = run(p, "https://x.com/Nome_1/media", h, session=session)
    assert [(f.subdir, f.name) for f in files] == [
        ("@Nome_1", "100_FOTO1.jpg"), ("@Nome_1", "102_vid.mp4")]
    assert files[0].url == "https://pbs.twimg.com/media/FOTO1?format=jpg&name=orig"
    assert files[1].url == "https://video.twimg.com/v/720/vid.mp4?tag=1"
    assert files[0].meta["caption"] == "post 100" and files[0].meta["date"] == 1539202764
    assert len(seen) == 2                                     # pagina 1 dal browser, poi C2 e C3 (fine)


def test_x_senza_post_nel_browser_spiega():
    from picfinder.session import BrowserSession
    p = plugins.find_plugin("https://twitter.com/qualcuno")
    with pytest.raises(Exception, match="non ha caricato i post"):
        run(p, "https://twitter.com/qualcuno", lambda r: httpx.Response(404),
            session=BrowserSession(start_url="x", final_url="x", html=""))
