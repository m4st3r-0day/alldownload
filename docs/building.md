# Building and development

## Requirements

| | Version |
|---|---|
| Python | 3.10 or newer |
| PySide6 | 6.6 or newer (installed by `pip`) |
| httpx | 0.27+ with `socks` and `http2` extras (installed by `pip`) |
| ffmpeg | optional: video frames in previews, HLS videos |

On macOS: `brew install python ffmpeg`.

## Run from source

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # app + pytest + pyinstaller
python -m picfinder                # window
pytest -q                          # tests
```

To keep settings, logs and the browser profile inside the project folder while developing:

```bash
export PICFINDER_SETTINGS="$PWD/settings.json"
export PICFINDER_LOGDIR="$PWD/log"
export PICFINDER_BROWSERDIR="$PWD/browser-profilo"
```

These paths are listed in `.gitignore`: they hold logins and proxy passwords.

## macOS app

```bash
bash packaging/build_mac.sh
```

The script:

1. creates or reuses `.venv` and installs the app with PyInstaller;
2. checks that QtWebEngine, QtSvg, httpx and the app import correctly;
3. builds `dist/AllDownload.app` (icon `packaging/AllDownload.icns`, bundle id `com.alldownload.app`) with the templates and the browser extension inside;
4. adds the `alldownload://` URL scheme, signs the app ad hoc, and copies settings and the browser login from the project folder (if present) to the app's data folder;
5. installs the app in `/Applications` (or `~/Applications`) and opens it.

The app is signed ad hoc, not notarized. It runs on the Mac that built it. To share it, sign it with a Developer ID and notarize it, or let users build it themselves.

If the app crashes, the Python and Qt traceback is written to `crash.log` in the log folder.

## Windows and Linux

The app runs from source on both (see above). The code is cross-platform, but packaged builds have only been made for macOS so far. PyInstaller works the same way:

```bash
pyinstaller --windowed --name AllDownload \
  --add-data "picfinder/templates:picfinder/templates" \
  --add-data "extension:extension" \
  --collect-submodules picfinder \
  packaging/app_main.py
```

On Windows use `;` instead of `:` in `--add-data`.

## Project layout

```
picfinder/          application package (see architecture.md)
  templates/        bundled .etmpl templates
  plugins/          Python plugins
extension/          Chrome extension "Send to AllDownload"
packaging/          macOS build script, app entry point, icons
tests/              pytest suite, fixtures, local test site
docs/               documentation
```

## Translations

Interface strings are written in Italian in the code. They are translated at runtime by `i18n.tr()` and `i18n.translate_tree()` with the dictionary in `picfinder/lang_en.py`. To add a string, write it in Italian in the code and add its English text to `EN`. To add a language, create `lang_<code>.py` with the same structure and extend `i18n.py`.

## Release checklist

- [ ] `pytest -q` passes.
- [ ] Version updated in `picfinder/__init__.py` and `pyproject.toml`.
- [ ] `CHANGELOG.md` updated.
- [ ] `git status` shows no `settings.json`, `log/`, `browser-profilo/` or `.venv/`.
- [ ] macOS app built and opened once.
