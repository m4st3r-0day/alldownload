# Scrivere un plugin per un sito

AllDownload trova i file in due modi:

1. **Plugin Python** in `picfinder/plugins/` (codice nostro, il modo consigliato).
2. **Template `.etmpl`** (formato compatibile con Extreme Picture Finder), per chi non scrive codice.

Se per lo stesso sito ci sono tutti e due, vince il plugin con `PREFERRED = True`.

## Il minimo

```python
# picfinder/plugins/miosito.py
import re
import sys

from ..core import PluginError, RemoteFile
from ._kit import clean_name, kit_for

NAME = "MioSito"
DELAY = (1.0, 2.0)         # pausa tra due pagine dello stesso server (secondi)
TESTED = ""                # "2026-11" quando l'hai provato sul sito vero

_RE = re.compile(r"^https?://(www\.)?miosito\.com/album/(\w+)", re.I)


def match(url: str) -> bool:
    return bool(_RE.match(url))


async def list_files(client, url, password=None, session=None):
    kit = kit_for(sys.modules[__name__], client, session)
    page = await kit.fetch(f"https://miosito.com/api/album/{_RE.match(url).group(2)}")
    data = page.json()
    folder = clean_name(data.get("title") or "")      # nome dell'album, non il codice del link
    if not data.get("files"):
        raise PluginError("Album vuoto o privato.")
    for f in data["files"]:
        yield RemoteFile(url=f["url"], name=clean_name(f["name"]), subdir=folder, size=f.get("size"))
```

`list_files` è un generatore asincrono: dai i file man mano che li trovi, così la lista si riempie subito.

## Attributi facoltativi

| Attributo | A cosa serve |
|---|---|
| `PREFERRED = True` | passa davanti al template `.etmpl` dello stesso sito |
| `ACCEPTS_SESSION = True` | `list_files` riceve `session=` con le risposte del browser interno |
| `NEEDS_BROWSER = True` | apre il browser interno prima di cercare (login, controlli del sito) |
| `BROWSER_MESSAGE = "…"` | testo mostrato sopra il browser |
| `BROWSER_USEFUL = r"…"` | regex delle richieste del browser da tenere |
| `TESTED = "2026-11"` | mese dell'ultima prova vera; vuoto = «da provare» nella lista dei template |
| `DELAY = (min, max)` | pausa casuale tra due pagine dello stesso server |

## Gli attrezzi in `_kit.py`

- `kit_for(modulo, client, session)` → `Crawl` con la pausa del plugin, moltiplicata per «Pause» nelle Impostazioni.
- `Crawl.fetch(url, method="GET", json_body=…, headers=…, referer=…)` → `Page` (`.text`, `.json()`, `.status`).
  Se il browser interno ha già quella risposta, la usa senza chiedere di nuovo. Con 401/403/404/429 lancia
  `PluginError` con un messaggio chiaro per l'utente.
- `Crawl.copy_headers(regex, ("authorization", …))` copia intestazioni (token, firme) dalle richieste del browser.
- `clean_name`, `name_from_url`, `page_title`.

## Regole

- Nomi delle cartelle: il titolo dell'album o della cartella, mai il codice del link. Se non c'è, usa il codice.
- Pausa per server, non globale: due siti diversi non si aspettano a vicenda.
- Niente proxy a rotazione per aggirare limiti, niente aggiramento di DRM, niente finti browser:
  vedi le regole fisse in [ROADMAP.md](../ROADMAP.md).
- Siti con account (OnlyFans, Fansly): solo l'account dell'utente e i contenuti a cui è abbonato.
- Errori per l'utente con `PluginError("…")`: frasi corte, cosa fare.

## Prove

Metti una pagina salvata in `tests/fixtures/` e una prova in `tests/test_plugin_siti.py` con
`httpx.MockTransport` (guarda quelle di filester e gofile). Poi prova sul sito vero e scrivi `TESTED`.
Per controllare tutti i siti dei tuoi progetti in un colpo: **Strumenti → Controlla i siti…**.
