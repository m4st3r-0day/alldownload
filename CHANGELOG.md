# Changelog

All notable changes are listed here. Format based on [Keep a Changelog](https://keepachangelog.com/).

## [0.4.0] — 2026-11-21

### Cambiato
- OnlyFans (profilo e chat), filester e pixeldrain: provati sul sito vero → «Supportato, provato».
- Niente più messaggi interni di Chromium nel Terminale (FIDO/Bluetooth, `stun… -105`).
- GitHub Actions: Mac su `macos-15` (l'immagine `macos-14` è stata ritirata da GitHub il 2 novembre 2026).

## [0.3.0] — 2026-11-21

### Nuovo
- Siti nuovi (plugin Python, dai template EPF che avevi): **happymodal** (gallerie ed elenchi), **blinkgirl**, **jliji** (set ed elenchi), **gedecomix** (fumetti, capitoli in ordine, elenchi), **X / Twitter** (profilo: Media, Post, Risposte, Repost — col tuo login, foto originali e video nella qualità più alta) e **av01** (video HLS → .mp4 con ffmpeg; i video cifrati no).
- **Vista a griglia** delle anteprime; barra spaziatrice = anteprima grande (frecce per scorrere).
- **Cerca nei file scaricati** (Strumenti, Cmd+Shift+F): nome, cartella o profilo, tipo; doppio clic = mostra nel Finder.
- **Esporta / importa** progetti e impostazioni (menu File). Proxy e token GitHub solo se lo chiedi; prima di importare salva una copia.
- **Controlla i siti** (Strumenti): cerca senza scaricare un link per ogni sito dei tuoi progetti e dice cosa va.
- Numero dei file mancanti sull'icona nel Dock mentre scarica.
- Lingua e tema cambiano subito, senza riavviare.
- Aggiornamenti con repo privato: finestra guidata che apre GitHub con il token già impostato.

### Cambiato
- **Licenza MIT**: il codice è aperto.
- Avvertenze nel README e in «Informazioni su AllDownload»: uso personale, responsabilità di chi usa l'app.
- Niente più avvisi `qt.accessibility.table` nel Terminale.
- Bunkr, filester, Gofile, OnlyFans (profilo e chat), Fansly, ImageFap, Tumblr: ora **plugin Python nostri**.
- **Niente più template EPF inclusi** nell'app. Il formato `.etmpl` resta supportato: puoi aggiungere i tuoi
  (trascinali nella finestra o mettili nella cartella dei template).
- Bunkr: le foto degli album arrivano dall'elenco «gallery», senza aprire la pagina di ogni foto.
- PySide6 bloccato a `>=6.8,<6.13`, Python `<3.15` (su Windows 3.15 dava `'lazy_import' object is not callable`).
- `gui.py` diviso: `theme.py`, `widgets.py`, `gridview.py`.

### Sviluppo
- Test dell'interfaccia, test delle traduzioni inglesi, prove a ogni push su GitHub (Mac, Windows, Linux).
- Guida per scrivere un plugin: `docs/plugins.md`.

## [0.2.0] — 2026-11-21

### Nuovo
- **Aggiornamenti dall'app**: AllDownload controlla da solo se c'è una versione nuova (una volta al giorno), ti mostra le novità e si aggiorna con un clic. Prima di sostituire i file ne salva una copia in `backup/`; impostazioni, log e login non vengono mai toccati. Anche da *AllDownload → Controlla aggiornamenti…*.
- **Design nuovo, da app del Mac**: barra laterale come nel Finder, colore principale preso dalle Impostazioni di Sistema, niente scritte MAIUSCOLE, stato dei file con pallino colorato, Impostazioni nello stile di Impostazioni di Sistema.
- Animazioni brevi e morbide (pannello Opzioni, barra di avanzamento) e avvisi in basso quando un download finisce. Opzione «Riduci le animazioni».
- **Icona nella barra dei menu**: avanzamento, pausa, ripresa e stop senza aprire la finestra.
- **Nomi a modello**: es. `{profilo}_{data}_{n}` → `mario_2026-03-14_0007.jpg` (Impostazioni → Download).
- **Data giusta sui file**: la data del post (dalle API del sito) o quella del server; didascalia del post in un `.txt` accanto, se vuoi.
- **Spazio su disco**: avviso prima di scaricare se non basta, e stop automatico prima di riempire il disco.
- **File interi**: foto e video controllati alla fine; se sono troncati (o il server ha mandato una pagina web) si riscaricano da soli.
- **App pronte su GitHub**: a ogni versione GitHub crea l'app per Mac e per Windows con il controllo SHA-256; l'aggiornamento automatico funziona anche per l'app installata.
- **Siti provati a novembre 2026**: Bunkr (nuova API di download con link firmati), filester (cartelle e file), OnlyFans (media del profilo e chat), Koofr, Gofile. Nella finestra Template sono segnati «Supportato, provato 11/2026».
- La cartella di ogni link prende il **nome dell'album / della cartella condivisa** (Bunkr, filester, Koofr, Gofile, pixeldrain e gli altri), non il codice del link. Profili OnlyFans/Fansly: il nome utente.
- OnlyFans/Fansly: avviso se i proxy sono attivi (con i proxy si va in timeout) e consigli al primo uso (login, chat, VPN senza cambiare server).
- Menu **Modifica** (Taglia, Copia, Incolla, Seleziona tutto): copia e incolla funzionano anche dentro il browser interno.
- Le pause di «Pause tra un file e l'altro» valgono anche per la ricerca delle pagine (con un minimo di ~0,3 s per server).
- Se hai una copia vecchia di un template incluso, l'app usa da sola la versione più nuova.
- Licenza: tutti i diritti riservati. README e guida aggiornati, con i siti supportati e come usare OnlyFans.

### Corretto
- Bunkr (e simili) sembrava bloccato in ricerca: ora i file escono uno alla volta mentre cerca, e le pause del template valgono per server.
- filester: le cartelle trovavano 0 file (il sito non usa più link normali) e i file arrivano da un server nuovo; ora una sola richiesta per file.
- Bunkr: il sito ha cambiato il modo di dare i link (prima cifrati, ora firmati): di nuovo funzionante, e una pagina inutile in meno per ogni file.
- Gofile: i nomi con parentesi («Foto (1).jpg») venivano tagliati e i server dei file rispondevano con una pagina web (mancava il cookie di accesso dell'ospite): ora scarica.
- Impostazioni: i testi lunghi vanno a capo invece di essere tagliati.
- Niente più messaggi «js: …» delle pagine web e avvisi sui caratteri nel Terminale.
- Il browser interno faceva chiudere l'app su macOS (OnlyFans, filester): era il filtro dei link `alldownload://`, ora gestito senza toccare gli eventi del browser.

## [0.1.0] — 2026-11-15

First public release.

### Search and download
- Runs Extreme Picture Finder `.etmpl` templates, with a compatibility check for each one.
- Python plugins for Koofr and pixeldrain; bundled templates for Gofile, Bunkr, ImageFap, Tumblr, filester, OnlyFans (profile and chat gallery) and Fansly.
- Preview and choose files before downloading, or download everything right away.
- Find and download at the same time.
- HLS videos (`.m3u8`) without encryption are saved as `.mp4` with ffmpeg.

### Speed and politeness
- Parallel downloads with a per-server limit that adapts and is remembered per server.
- Large files in parallel parts when the server supports ranges; HTTP/2.
- Small files first, servers take turns.
- `Retry-After`, a cool-down on 429/503, and a long pause for servers that keep refusing.
- Download hours, pause on battery, bandwidth share, speed limit.
- Daily request counter per site with a warning.

### Projects
- Projects with categories, update with new files only, queue with priorities.
- Watched projects checked automatically.
- Pause and resume, also after closing the app; interrupted files resume.
- Expired signed links detected before downloading, with a new search offered.

### Files
- One folder per link, split into `Foto`, `Video`, `Altri`; chats in `<user>/Chat`.
- Already downloaded files are recognised even when links change.
- Identical photos with different names are flagged or moved to `_Doppioni`.

### Built-in browser
- Login, cookies, API request capture, popups, auto-scroll.
- Real engine User-Agent shared with downloads; request capture paused automatically when a Cloudflare check fails.
- Downloads through the browser itself for links tied to its IP.

### Interface
- New design with sidebar, line icons, light and dark theme.
- English and Italian.
- Statistics, template editor with live test, detailed log.
- "Send to AllDownload": bookmarklet, Chrome extension and the `alldownload://` link scheme.
- macOS app build script.

### Network
- Proxy list (HTTP/SOCKS, `ip:port:user:password`, lists from a link), speed test, failover only when a proxy fails, passwords masked.
