# Architecture

AllDownload is a Python 3.10+ application. The interface uses **PySide6** (Qt 6, with QtWebEngine for the built-in browser); networking uses **httpx** (async, HTTP/2, SOCKS). Data is stored in SQLite and JSON files.

The Python package is still named `picfinder` (the project's original name). That keeps imports, data folders and existing installs stable.

## Modules

| Module | Role |
|---|---|
| `gui.py` | Main window: states (idle, scanning, review, downloading), file list, preview, projects, queue, events from the engine. |
| `core.py` | The engine: `Downloader` (scan, download, find-and-download), `HostGate` (per-server politeness), `SpeedLimiter`, folder rules, resumable and segmented downloads, HLS. |
| `etmpl.py` | `.etmpl` parser and `EtmplPlugin` crawler. |
| `plugins/` | Plugin registry and Python plugins (`koofr`, `pixeldrain`). |
| `sitehooks.py` | Small site-specific fixes used by templates. |
| `browser.py` | Built-in browser: request capture, cookies, popups, auto-scroll, `BrowserFetcher` (downloads through the browser itself). |
| `session.py` | `BrowserSession`: what the browser hands to the crawler. |
| `netpolicy.py` | Remembered limits per server, download hours and battery, link expiry, image fingerprints, page cache. |
| `proxies.py` | Proxy pool: test, sort by speed, failover, list parsing, masking. |
| `projects.py` | SQLite store: projects, files, download history, request counters, failures, image hashes. |
| `settings.py` / `settings_dialog.py` | Settings dataclass (JSON) and its window. |
| `projects_panel.py`, `templates_dialog.py`, `tools_dialogs.py` | Sidebar, templates window, statistics, template editor, "Send to" dialog. |
| `i18n.py` / `lang_en.py` | Translation: Italian source strings, English dictionary. |
| `icons.py` | Line icons and the app icon, drawn as SVG. |
| `logs.py` | Session log files. |
| `cli.py` | Command line. |

## How a download works

```
link ──► plugin / template ──► scan ──► list of RemoteFile ──► user choice ──► download
             ▲                   │                                               │
     built-in browser            └─ organize(): folder per link, Foto/Video      ├─ HostGate (per server)
     (cookies, API capture)         dedupe of mirror servers                     ├─ SpeedLimiter
                                                                                  ├─ resume / segments / HLS
                                                                                  └─ history, duplicates
```

1. **Find a plugin.** `plugins.find_plugin(url)` picks a Python plugin or a template (most specific match).
2. **Browser if needed.** If the template needs it, the GUI opens `BrowserDialog`. The resulting `BrowserSession` goes to the scan.
3. **Scan.** `Downloader.scan()` runs the plugin. Every `RemoteFile` gets its final folder from `organize()` and is sent to the GUI as a `found` event.
4. **Download.** `Downloader.download()` orders the files (small first, servers taking turns) and runs them in parallel:
   - a global semaphore (*files at once*);
   - `HostGate`: per-server connection limit (adaptive, remembered in `limiti_siti.json`), the template's pause per connection, and cool-down on 429/503 using `Retry-After`;
   - `SpeedLimiter`: fixed limit or a share of the measured line;
   - resume with `Range` from `.part` files; large files in parallel parts; HLS through ffmpeg (encrypted streams refused).
5. **After each file.** It is recorded in the history (stable key that ignores signatures), checked for image duplicates, and reported as a `done` event.

`Downloader.scan_and_download()` does steps 3 and 4 together: each `found` file goes straight into the download queue.

## Threads

- The engine runs `asyncio` inside a `QThread` (`Worker`). It talks to the GUI only through Qt signals with queued connections.
- Previews run in a small `QThreadPool` (2 threads).
- The built-in browser and `BrowserFetcher` run in the GUI thread (Qt WebEngine requirement).
- Stop and pause cancel the asyncio task from the GUI thread with `call_soon_threadsafe`.

## Data

The data folder is `PicFinder` inside the platform's application data folder (see the [user guide](user-guide.md#where-your-data-is)). Environment variables override single paths:

| Variable | Default |
|---|---|
| `PICFINDER_SETTINGS` | `<data>/settings.json` |
| `PICFINDER_LOGDIR` | `<data>/log` |
| `PICFINDER_BROWSERDIR` | `<data>/browser` |
| `PICFINDER_TEMPLATES` | extra template folder, none by default |

## Network rules

- Politeness first: per-server limits, the template's pauses, `Retry-After`, a long pause for servers that keep answering 429, and a daily request counter.
- Proxies switch only when the proxy itself fails, never because a site refused a request.
- Links signed for one IP (CloudFront policies) are downloaded without the proxy, or through the built-in browser.
- No DRM or encryption bypass, no fingerprint spoofing.

## Tests

`pytest -q` runs about 70 tests with mocked servers (`httpx.MockTransport`) and a small local test site in `tests/sito_prova/`. They cover templates, the crawler, politeness, resume, segments, pause, find-and-download, proxies, projects, previews and the browser session.
