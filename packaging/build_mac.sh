#!/bin/bash
# Crea AllDownload.app (app vera per Mac, non serve il Terminale per usarla).
# Doppio clic su «Crea app AllDownload.command» sulla Scrivania: ci vogliono 3-6 minuti.
set -e
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.homebrew/bin:$PATH"
cd "$(dirname "$0")/.." || exit 1          # cartella del progetto
PROJ="$PWD"
APP="AllDownload"
DATA="$HOME/Library/Application Support/PicFinder"   # dati dell'app (progetti, login, impostazioni)

pause() { read -r -p "$1 (Invio per chiudere) " _; }

PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then PY="$c"; break; fi
done
[ -n "$PY" ] || { echo "Serve Python 3.10 o più recente: brew install python"; pause "Errore"; exit 1; }

echo "1/5  Ambiente Python ($($PY --version))"
[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -e . "pyinstaller>=6.6" || { pause "Errore nell'installazione"; exit 1; }

echo "2/5  Controllo veloce"
python -c "import PySide6.QtWebEngineWidgets, PySide6.QtSvg, httpx, socksio, h2, picfinder.gui" \
  || { pause "Manca qualcosa"; exit 1; }

echo "3/5  Creo $APP.app (qualche minuto)…"
rm -rf build "dist/$APP.app"
pyinstaller --noconfirm --clean --windowed \
  --name "$APP" \
  --icon packaging/AllDownload.icns \
  --osx-bundle-identifier com.alldownload.app \
  --add-data "picfinder/templates:picfinder/templates" \
  --add-data "extension:extension" \
  --collect-submodules picfinder \
  --hidden-import PySide6.QtSvg \
  --hidden-import PySide6.QtWebEngineWidgets \
  --hidden-import PySide6.QtWebEngineCore \
  --log-level WARN \
  packaging/app_main.py || { pause "Errore nella creazione dell'app"; exit 1; }

bash packaging/mac_finish.sh "dist/$APP.app" "$(python -c 'import picfinder; print(picfinder.__version__)')" >/dev/null 2>&1 || true

echo "4/5  Porto login, impostazioni e template nell'app"
mkdir -p "$DATA"
if [ -f settings.json ]; then
  [ -f "$DATA/settings.json" ] && cp "$DATA/settings.json" "$DATA/settings.json.bak"
  cp settings.json "$DATA/settings.json"
fi
if [ -d browser-profilo/storage ]; then
  mkdir -p "$DATA/browser"
  rsync -a browser-profilo/storage/ "$DATA/browser/storage/"
fi

echo "5/5  Installo in Applicazioni"
DEST="/Applications"
[ -w "$DEST" ] || DEST="$HOME/Applications"
mkdir -p "$DEST"
rm -rf "$DEST/$APP.app"
cp -R "dist/$APP.app" "$DEST/"
echo ""
echo "Fatto: $DEST/$APP.app"
echo "Dati dell'app: $DATA"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST/$APP.app" 2>/dev/null || true
open "$DEST/$APP.app"
pause "Puoi chiudere questa finestra."
