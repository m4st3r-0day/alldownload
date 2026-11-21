"""Browser interno (Chromium di Qt).

Si apre quando un template lo chiede (login manuale, intestazioni da copiare) oppure con il
bottone "Browser". Tu fai login / aspetti / risolvi il controllo "sei umano?", poi premi
"Continua download": PicFinder prende cookie, richieste e pagina e cerca i file.

Il profilo è salvato su disco: i login restano anche dopo aver chiuso l'app.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from .core import USER_AGENT
from .i18n import tr, translate_tree
from .plugins import user_templates_dir
from .session import BrowserSession, CapturedRequest, Cookie

log = logging.getLogger("picfinder")

# Registra le richieste fetch/XHR della pagina (indirizzo, metodo, intestazioni, corpo, risposta).
CAPTURE_JS = r"""
(function () {
  if (window.__pf) return;
  var pf = window.__pf = { reqs: [], max: 600 };
  function push(r) { pf.reqs.push(r); if (pf.reqs.length > pf.max) pf.reqs.shift(); }
  function abs(u) { try { return new URL(u, location.href).href; } catch (e) { return String(u); } }
  function hdrs(h) {
    var o = {};
    try {
      if (!h) return o;
      if (typeof Headers !== 'undefined' && h instanceof Headers) { h.forEach(function (v, k) { o[k.toLowerCase()] = v; }); }
      else if (Array.isArray(h)) { h.forEach(function (p) { o[String(p[0]).toLowerCase()] = String(p[1]); }); }
      else { for (var k in h) o[k.toLowerCase()] = String(h[k]); }
    } catch (e) {}
    return o;
  }
  var textual = /json|text|javascript|xml|mpegurl/i;
  var of = window.fetch;
  if (of) {
    window.fetch = function (input, init) {
      var rec = { url: '', method: 'GET', headers: {}, body: null, kind: 'fetch' };
      try {
        if (typeof Request !== 'undefined' && input instanceof Request) {
          rec.url = input.url; rec.method = input.method; rec.headers = hdrs(input.headers);
        } else { rec.url = String(input); }
        if (init) {
          if (init.method) rec.method = String(init.method).toUpperCase();
          if (init.headers) { var h = hdrs(init.headers); for (var k in h) rec.headers[k] = h[k]; }
          if (typeof init.body === 'string') rec.body = init.body;
        }
        rec.url = abs(rec.url);
      } catch (e) {}
      push(rec);
      var p = of.apply(this, arguments);
      p.then(function (resp) {
        try {
          rec.status = resp.status;
          rec.ctype = resp.headers.get('content-type') || '';
          if (textual.test(rec.ctype)) resp.clone().text().then(function (t) { if (t.length < 4000000) rec.text = t; }).catch(function () {});
        } catch (e) {}
      }).catch(function () {});
      return p;
    };
  }
  var XP = XMLHttpRequest.prototype, XO = XP.open, XS = XP.send, XH = XP.setRequestHeader;
  XP.open = function (m, u) {
    this.__pf = { method: String(m || 'GET').toUpperCase(), url: abs(u), headers: {}, body: null, kind: 'xhr' };
    return XO.apply(this, arguments);
  };
  XP.setRequestHeader = function (k, v) {
    try { if (this.__pf) this.__pf.headers[String(k).toLowerCase()] = String(v); } catch (e) {}
    return XH.apply(this, arguments);
  };
  XP.send = function (b) {
    var r = this.__pf, x = this;
    if (r) {
      if (typeof b === 'string') r.body = b;
      push(r);
      x.addEventListener('load', function () {
        try {
          r.status = x.status;
          r.ctype = x.getResponseHeader('content-type') || '';
          if ((x.responseType === '' || x.responseType === 'text') && textual.test(r.ctype) && x.responseText.length < 4000000) r.text = x.responseText;
        } catch (e) {}
      });
    }
    return XS.apply(this, arguments);
  };
})();
"""

COLLECT_JS = ("JSON.stringify({url: location.href, html: document.documentElement.outerHTML,"
              " reqs: (window.__pf ? window.__pf.reqs : [])})")
COUNT_JS = "window.__pf ? window.__pf.reqs.length : 0"
PEEK_JS = ("JSON.stringify({title: document.title, url: location.href,"
           " text: (document.body ? document.body.innerText : '').replace(/\\s+/g, ' ').slice(0, 300),"
           " html: document.documentElement ? document.documentElement.outerHTML.length : 0,"
           " reqs: window.__pf ? window.__pf.reqs.length : -1})")
SCROLL_JS = "window.scrollBy(0, Math.max(600, window.innerHeight * 0.9)); document.body ? document.body.scrollHeight : 0"

_profile: QWebEngineProfile | None = None
_temp_profile: QWebEngineProfile | None = None


ENGINE_UA = ""


def _setup(p: QWebEngineProfile) -> QWebEngineProfile:
    # Il browser usa il suo vero «nome» (quello del suo motore Chromium): un nome finto che non combacia
    # con il motore fa fallire i controlli «sei umano?» (Cloudflare Turnstile 600010).
    # I download poi usano lo stesso nome, così i cookie del controllo restano validi.
    global ENGINE_UA
    ENGINE_UA = p.httpUserAgent()
    p.setHttpAcceptLanguage("it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7")
    script = QWebEngineScript()
    script.setName("picfinder-capture")
    script.setSourceCode(CAPTURE_JS)
    script.setInjectionPoint(QWebEngineScript.DocumentCreation)
    script.setWorldId(QWebEngineScript.MainWorld)
    script.setRunsOnSubFrames(False)
    p.scripts().insert(script)
    return p


def profile() -> QWebEngineProfile:
    """Profilo persistente (cookie e login restano su disco)."""
    global _profile
    if _profile is None:
        p = QWebEngineProfile("PicFinder", QApplication.instance())
        custom = os.environ.get("PICFINDER_BROWSERDIR")
        base = Path(custom) if custom else user_templates_dir().parent / "browser"
        base.mkdir(parents=True, exist_ok=True)
        p.setPersistentStoragePath(str(base / "storage"))
        p.setCachePath(str(base / "cache"))
        # cache solo in memoria: niente pagine/API vecchie da una sessione all'altra
        # (i link firmati per un IP vecchio darebbero 403). Login e cookie restano su disco.
        p.setHttpCacheType(QWebEngineProfile.MemoryHttpCache)
        p.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        _profile = _setup(p)
    return _profile


def temp_profile() -> QWebEngineProfile:
    """Profilo temporaneo (niente login salvati): riserva se quello salvato non funziona."""
    global _temp_profile
    if _temp_profile is None:
        _temp_profile = _setup(QWebEngineProfile(QApplication.instance()))
    return _temp_profile


class _Page(QWebEnginePage):
    """Pagina che apre i popup (es. "Accedi con Google") in una finestra vera.
    Niente javaScriptConsoleMessage qui: ridefinirlo fa cadere l'app su macOS con pagine molto «chiacchierone»."""

    def __init__(self, prof, owner):
        super().__init__(prof, owner)
        self.owner = owner
        self.popups: list[QDialog] = []

    def createWindow(self, _type):
        dlg = QDialog(self.owner)
        dlg.setWindowTitle("Accesso")
        dlg.resize(520, 680)
        view = QWebEngineView(dlg)
        page = _Page(self.profile(), dlg)
        view.setPage(page)
        page.windowCloseRequested.connect(dlg.close)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view)
        from . import editmenu
        editmenu.add_actions(dlg)
        dlg.show()
        self.popups.append(dlg)
        return page


class BrowserDialog(QDialog):
    """Finestra del browser. Dopo exec(): self.session (BrowserSession) se hai premuto Continua."""
    collected = Signal(object)

    def __init__(self, parent, url: str, message: str = "", title: str = "",
                 auto_continue: int | None = None, useful=None):
        super().__init__(parent)
        self.setWindowTitle(title or "Browser interno")
        self.resize(1180, 820)
        self.start_url = url
        self.session: BrowserSession | None = None
        self.useful = useful            # funzione(url) -> bool: richiesta utile al template?
        self.cookies: dict[tuple, Cookie] = {}
        self.auto_continue = auto_continue
        # niente clearHttpCache() qui: su macOS può far cadere l'app mentre il profilo si apre.
        # La cache è solo in memoria (vedi _setup): a ogni avvio dell'app riparte vuota.

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        nav = QHBoxLayout()
        from .icons import icon
        mc = "#98A2B3"
        self.b_back = QPushButton(icon("chevron-left", mc, 16), "")
        self.b_fwd = QPushButton(icon("chevron-right", mc, 16), "")
        self.b_reload = QPushButton(icon("refresh", mc, 16), "")
        for b in (self.b_back, self.b_fwd, self.b_reload):
            b.setObjectName("iconbtn")
        self.b_home = QPushButton("Home")
        self.b_home.setObjectName("ghost")
        self.b_home.setToolTip("Torna al link di partenza (utile dopo un login che non ti riporta lì)")
        self.b_clean = QPushButton("Pulisci dati")
        self.b_clean.setObjectName("ghost")
        self.b_clean.setToolTip("Cancella cookie e dati salvati del browser interno (anche i login) e ricarica.\n"
                                "Utile se un sito resta vuoto qui ma in Safari funziona.")
        self.b_clean.clicked.connect(self.clean_site_data)
        self.address = QLineEdit(url)
        self.address.returnPressed.connect(self.go)
        for b in (self.b_back, self.b_fwd, self.b_reload):
            nav.addWidget(b)
        nav.addWidget(self.b_home)
        nav.addWidget(self.b_clean)
        nav.addWidget(self.address, 1)
        lay.addLayout(nav)

        text = message or ("Fai login se serve, aspetta che si veda il contenuto (scorri per caricarne di più), "
                           "poi premi «Continua download».")
        self.banner = QLabel(tr(text))
        self.banner.setWordWrap(True)
        self.banner.setObjectName("banner")
        lay.addWidget(self.banner)

        self.view = QWebEngineView(self)
        self.page = _Page(profile(), self.view)
        self.view.setPage(self.page)
        self.page.renderProcessTerminated.connect(self._crashed)
        self.finished.connect(self._restore_capture)
        self.using_temp = False
        self.failures = 0
        lay.addWidget(self.view, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("Caricamento…")
        self.status.setObjectName("muted")
        self.autoscroll = QCheckBox("Scorri giù da solo")
        self.autoscroll.setToolTip("Scorre la pagina ogni 1,5 secondi per far caricare più contenuti")
        cancel = QPushButton("Annulla")
        cancel.clicked.connect(self.reject)
        self.go_btn = QPushButton("Continua download")
        self.go_btn.setDefault(True)
        self.go_btn.setObjectName("primary")
        self.go_btn.setMinimumWidth(170)
        self.go_btn.clicked.connect(self.finish)
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.autoscroll)
        bottom.addWidget(cancel)
        bottom.addWidget(self.go_btn)
        lay.addLayout(bottom)

        self.b_back.clicked.connect(self.view.back)
        self.b_fwd.clicked.connect(self.view.forward)
        self.b_reload.clicked.connect(self.view.reload)
        self.b_home.clicked.connect(lambda: self.view.load(QUrl(self.start_url)))
        self.view.urlChanged.connect(lambda u: self.address.setText(u.toString()))
        self.view.loadFinished.connect(self._loaded)

        store = profile().cookieStore()
        store.cookieAdded.connect(self._cookie_added)
        store.cookieRemoved.connect(self._cookie_removed)
        store.loadAllCookies()
        translate_tree(self)
        from . import editmenu
        editmenu.add_actions(self)              # Cmd+C / Cmd+V anche dentro le pagine web

        self.timer = QTimer(self, interval=1500, timeout=self._tick)
        self.timer.start()
        self.progress = 0
        self.view.loadProgress.connect(self._progress)
        self.watchdog = QTimer(self, singleShot=True, interval=10000, timeout=self._watchdog)
        self.watchdog.start()
        self._requests = 0
        self._useful = 0
        self._finishing = False
        log.info("Browser interno: apro %s", url)
        self.view.load(QUrl(url))

    def _peek(self, data, why: str = "pagina caricata"):
        try:
            d = json.loads(data or "{}")
        except (TypeError, ValueError):
            d = {}
        log.info("Browser: %s — titolo «%s», testo «%s», html %s caratteri, richieste catturate %s",
                 why, d.get("title", ""), d.get("text", "")[:200], d.get("html"), d.get("reqs"))
        if d.get("reqs") == -1:
            log.warning("Browser: lo script di cattura non è attivo in questa pagina")
        low = (d.get("title", "") + " " + d.get("text", "")).lower()
        if any(k in low for k in ("too many requests", "rate limit", "429", "troppe richieste")):
            self._error("Il sito dice «troppe richieste» (429): ti ha bloccato per qualche minuto. Aspetta e riprova.")
        elif any(k in low for k in ("just a moment", "checking your browser", "verify you are human",
                                     "un momento", "sei un umano")):
            self.status.setStyleSheet("color:#D97706;")
            self.status.setText(tr("Il sito fa un controllo «sei umano?»: completalo nella pagina, poi «Continua»."))
            if not getattr(self, "_challenge_watch", False):
                # se dopo 25 s il controllo è ancora lì, lo rifaccio senza la nostra cattura
                self._challenge_watch = True
                QTimer.singleShot(25_000, self._recheck_challenge)
        elif getattr(self, "_capture_paused", False) and d.get("html", 0):
            self.resume_capture()

    def _recheck_challenge(self):
        if getattr(self, "_closing", False):
            return
        try:
            self.page.runJavaScript(PEEK_JS, 0, self._challenge_still_there)
        except RuntimeError:
            pass

    def _challenge_still_there(self, data):
        try:
            d = json.loads(data or "{}")
        except (TypeError, ValueError):
            return
        low = (d.get("title", "") + " " + d.get("text", "")).lower()
        if any(k in low for k in ("just a moment", "checking your browser", "verify you are human",
                                  "un momento", "sei un umano")):
            log.warning("Browser: il controllo «sei umano?» non passa da 25 s")
            QTimer.singleShot(0, self.pause_capture)

    def _capture_script(self):
        coll = self.page.profile().scripts()
        found = coll.find("picfinder-capture")
        return coll, (found[0] if isinstance(found, list) and found else found if not isinstance(found, list) else None)

    def pause_capture(self):
        """La verifica Cloudflare non è riuscita: tolgo la nostra cattura (che modifica fetch/XHR della pagina)
        e ricarico. Dopo la verifica la rimetto e ricarico per catturare di nuovo."""
        if getattr(self, "_capture_paused", False) or getattr(self, "_capture_retry_done", False):
            return
        coll, script = self._capture_script()
        if script is None or (hasattr(script, "isNull") and script.isNull()):
            return
        self._capture_paused, self._capture_retry_done = True, True
        self._saved_script = script
        coll.remove(script)
        log.info("Browser: verifica Cloudflare senza la cattura delle richieste, poi la riattivo")
        self.status.setText(tr("Verifica «sei umano?»: ricarico la pagina in modo pulito. Completa la verifica…"))
        QTimer.singleShot(300, self.view.reload)

    def _restore_capture(self, *_):
        if getattr(self, "_capture_paused", False):
            self._capture_paused = False
            try:
                self.page.profile().scripts().insert(self._saved_script)
            except RuntimeError:
                pass

    def resume_capture(self):
        if not getattr(self, "_capture_paused", False):
            return
        self._capture_paused = False
        self.page.profile().scripts().insert(self._saved_script)
        log.info("Browser: verifica superata, riattivo la cattura e ricarico")
        self.status.setText(tr("Verifica superata: ricarico per leggere i contenuti…"))
        QTimer.singleShot(300, self.view.reload)

    def clean_site_data(self):
        """Svuota cookie, cache e memoria locale del profilo, poi ricarica la pagina."""
        prof = self.page.profile()
        log.warning("Browser: pulisco cookie, cache e dati salvati del profilo")
        self.page.runJavaScript("try{localStorage.clear();sessionStorage.clear();}catch(e){}")
        prof.cookieStore().deleteAllCookies()
        prof.clearHttpCache()
        if hasattr(prof, "clearAllVisitedLinks"):
            prof.clearAllVisitedLinks()
        self.cookies.clear()
        self.status.setObjectName("muted")
        self.status.setText(tr("Dati del browser cancellati: ricarico…"))
        QTimer.singleShot(500, lambda: self.view.load(QUrl(self.start_url)))

    # ---------- problemi ----------
    def _progress(self, p: int):
        self.progress = max(self.progress, p)
        if p and not self._finishing and self.status.text().startswith(("Caricamento", "⚠")):
            self.status.setObjectName("muted")
            self.status.setText(tr("Caricamento…") + f" {p}%")

    def _watchdog(self):
        if self.progress == 0 and not self._finishing:
            log.warning("Browser: dopo 10 s la pagina non ha ancora iniziato a caricare")
            if not self.using_temp:
                self._switch_to_temp("la pagina non parte")
            else:
                self._error("La pagina non parte nemmeno con il profilo temporaneo. Chiudi del tutto "
                            "AllDownload (Cmd+Q) e i processi «QtWebEngineProcess» in Monitoraggio Attività.")

    def _error(self, text: str):
        self.status.setText("⚠ " + tr(text))
        self.status.setStyleSheet("color:#DC2626;")

    def _crashed(self, status, code):
        log.error("Browser: la pagina si è chiusa all'improvviso (stato %s, codice %s)", status, code)
        if not self.using_temp:
            self._switch_to_temp("la pagina si è chiusa all'improvviso")
        else:
            self._error("La pagina si è chiusa all'improvviso: premi ⟳ per riprovare.")

    def _switch_to_temp(self, why: str):
        """Riprova con un profilo temporaneo (senza login salvati)."""
        log.warning("Browser: %s → riprovo con un profilo temporaneo", why)
        self.using_temp = True
        old = self.page
        self.page = _Page(temp_profile(), self.view)
        self.page.renderProcessTerminated.connect(self._crashed)
        self.view.setPage(self.page)
        old.deleteLater()
        store = temp_profile().cookieStore()
        store.cookieAdded.connect(self._cookie_added)
        store.cookieRemoved.connect(self._cookie_removed)
        self.banner.setText(self.banner.text() + "\n⚠ Uso un profilo temporaneo: i login di prima non ci sono. "
                            "Se il problema continua, chiudi del tutto AllDownload (Cmd+Q) e riaprilo.")
        self.progress = 0
        self.watchdog.start()
        self.view.load(QUrl(self.start_url))

    # ---------- cookie ----------
    def _cookie_added(self, c):
        name = bytes(c.name()).decode("utf-8", "replace")
        self.cookies[(name, c.domain(), c.path())] = Cookie(name, bytes(c.value()).decode("utf-8", "replace"),
                                                            c.domain(), c.path() or "/")

    def _cookie_removed(self, c):
        self.cookies.pop((bytes(c.name()).decode("utf-8", "replace"), c.domain(), c.path()), None)

    # ---------- navigazione ----------
    def go(self):
        text = self.address.text().strip()
        if text and "://" not in text:
            text = "https://" + text
        self.view.load(QUrl(text))

    def _loaded(self, ok: bool):
        url = self.view.url().toString()
        log.debug("Browser: pagina caricata (%s) %s", "ok" if ok else "errore", url)
        if getattr(self, "_closing", False):
            return          # finestra in chiusura (Annulla / Continua): niente da fare
        if not ok:
            self.failures += 1
            log.warning("Browser: la pagina non si carica (%s), tentativo %d", url or "indirizzo vuoto", self.failures)
            if (not url or url == "about:blank") and not self.using_temp:
                self._switch_to_temp("il profilo salvato non risponde")
                return
            self._error("La pagina non si carica. Controlla la connessione e premi ⟳ per riprovare.")
            return
        self.failures = 0
        self.page.runJavaScript(PEEK_JS, 0, self._peek)
        if self.auto_continue and not self._finishing:
            self.status.setText(tr("Continuo da solo tra {n} s…", n=self.auto_continue))
            QTimer.singleShot(self.auto_continue * 1000, self.finish)

    def _tick(self):
        if self.autoscroll.isChecked():
            self.page.runJavaScript(SCROLL_JS)
        js = ("window.__pf ? JSON.stringify(window.__pf.reqs.map(function(r){return r.url})) : '[]'")
        self.page.runJavaScript(js, 0, self._update_count)

    def _update_count(self, data):
        try:
            urls = json.loads(data or "[]")
        except (TypeError, ValueError):
            urls = []
        useful = sum(1 for u in urls if self.useful and self.useful(u))
        txt = tr("Richieste catturate: {n}", n=len(urls))
        if self.useful:
            txt += " · " + tr("utili per il template: {n}", n=useful)
        txt += f" · cookie: {len(self.cookies)}"
        if not self._finishing:
            self.status.setText(txt)

    # ---------- fine ----------
    def finish(self):
        if self._finishing:
            return
        self._finishing = True
        self.go_btn.setEnabled(False)
        self.status.setText(tr("Raccolgo pagina, richieste e cookie…"))
        self.page.runJavaScript(COLLECT_JS, 0, self._collected)

    def _collected(self, data):
        try:
            d = json.loads(data) if data else {}
        except (TypeError, ValueError):
            d = {}
        empty = not d.get("reqs") and len(d.get("html") or "") < 200
        if empty and not self.auto_continue:
            log.warning("Browser: «Continua» premuto ma la pagina è ancora vuota (caricamento %d%%)", self.progress)
            self.page.runJavaScript(PEEK_JS, 0, lambda x: self._peek(x, "pagina vuota"))
            self._error("La pagina è ancora vuota: aspetta che si veda il contenuto (o premi ⟳), poi «Continua».")
            self._finishing = False
            self.go_btn.setEnabled(True)
            return
        s = BrowserSession(start_url=self.start_url, final_url=d.get("url") or self.view.url().toString(),
                           html=d.get("html") or "", user_agent=ENGINE_UA or USER_AGENT,
                           requests=[CapturedRequest.from_js(r) for r in d.get("reqs") or [] if r.get("url")],
                           cookies=list(self.cookies.values()))
        self.session = s
        log.info("Browser interno: %s", s.summary())
        for r in s.requests[-40:]:
            log.debug("  catturata: %s %s [%s] intestazioni: %s", r.method, r.url[:140], r.status,
                      ", ".join(sorted(r.headers)) or "-")
        self.timer.stop()
        self.collected.emit(s)
        self.accept()

    def reject(self):
        self.timer.stop()
        log.info("Browser interno: annullato")
        super().reject()

    def done(self, r):
        self._closing = True
        self.timer.stop()
        self.watchdog.stop()
        try:
            self.view.stop()
        except RuntimeError:
            pass
        super().done(r)


def open_browser(parent, url: str, message: str = "", title: str = "", auto_continue: int | None = None,
                 useful=None) -> BrowserSession | None:
    dlg = BrowserDialog(parent, url, message, title, auto_continue, useful)
    dlg.exec()
    session = dlg.session
    dlg.deleteLater()        # pagina e vista vengono distrutte con la finestra, prima del profilo
    return session


def shutdown():
    """Da chiamare all'uscita: chiude le pagine prima dei profili (evita processi appesi)."""
    global _profile, _temp_profile
    app = QApplication.instance()
    for w in list(app.topLevelWidgets()) if app else []:
        if isinstance(w, BrowserDialog):
            w.deleteLater()
    if app:
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)   # distrugge davvero le pagine
    _profile = _temp_profile = None


class BrowserFetcher(QObject):
    """Scarica file usando il browser interno (stessa rete, stesso IP, stessi cookie del login).
    Serve per i link che il sito lega all'IP del browser: dall'app darebbero 403."""
    result = Signal(object, bool, str)      # (oggetto dell'elemento, riuscito, percorso o errore)
    finished = Signal()

    STALL_MS = 60_000

    def __init__(self, items: list[tuple[object, str, str]], delay: tuple[float, float] | None = None,
                 parent=None):
        """items: (chiave libera, url, percorso finale)."""
        super().__init__(parent)
        self.items = list(items)
        self.delay = delay
        self.prof = profile()
        self.page = QWebEnginePage(self.prof, self)
        self.current = None
        self.req = None
        self._stopped = False
        self._last_bytes = -1
        self.watch = QTimer(self)
        self.watch.setInterval(self.STALL_MS)
        self.watch.timeout.connect(self._stalled)
        self.prof.downloadRequested.connect(self._requested)

    def start(self):
        QTimer.singleShot(0, self._next)

    def stop(self):
        self._stopped = True
        if self.req is not None:
            self.req.cancel()
        self._finish()

    def _finish(self):
        self.watch.stop()
        try:
            self.prof.downloadRequested.disconnect(self._requested)
        except (RuntimeError, TypeError):
            pass
        self.finished.emit()

    def _next(self):
        if self._stopped:
            return
        if not self.items:
            self._finish()
            return
        self.current = self.items.pop(0)
        _key, url, _path = self.current
        log.info("  browser ↓ %s", url.split("?")[0])
        self._last_bytes = -1
        self.watch.start()
        self.page.download(QUrl(url))

    def _requested(self, req):
        if self.current is None or self.req is not None:
            return
        key, url, path = self.current
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        req.setDownloadDirectory(str(p.parent))
        req.setDownloadFileName(p.name)
        self.req = req
        req.isFinishedChanged.connect(self._done)
        req.receivedBytesChanged.connect(lambda: None)
        req.accept()

    def _stalled(self):
        req = self.req
        if req is None:
            self._report(False, "il browser non ha iniziato il download")
            return
        got = req.receivedBytes()
        if got == self._last_bytes:
            req.cancel()                     # _done segnala l'errore
        self._last_bytes = got

    def _done(self):
        req = self.req
        if req is None or not req.isFinished():
            return
        ok = req.state() == req.DownloadState.DownloadCompleted
        path = str(Path(req.downloadDirectory()) / req.downloadFileName())
        self._report(ok, path if ok else (req.interruptReasonString() or "download interrotto"))

    def _report(self, ok: bool, info: str):
        self.watch.stop()
        key = self.current[0] if self.current else None
        self.req, self.current = None, None
        self.result.emit(key, ok, info)
        import random as _r
        wait = int(_r.uniform(*self.delay) * 1000) if self.delay else 500
        QTimer.singleShot(wait, self._next)
