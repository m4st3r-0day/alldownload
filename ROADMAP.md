# Roadmap di AllDownload

Stato al 21 novembre 2026 — versione 0.2.0.
Ordine = priorità. Spunta quando è fatto e sposta la riga nel [CHANGELOG](CHANGELOG.md).
`[~]` = codice pronto, manca la prova sul sito vero.

---

## 1. Indipendenza da Extreme Picture Finder (obiettivo principale)

Scopo: nell'app solo codice nostro, così il progetto può avere una licenza aperta (MIT) senza problemi.
I file `.etmpl` restano supportati: chi li ha li importa da solo, ma noi non li distribuiamo.

- [x] Koofr → plugin Python (cartella col nome del link condiviso)
- [x] pixeldrain → plugin Python (API)
- [x] Bunkr → plugin Python (album + file, API `_001_v2` + firma `/sign`; elenco «gallery» per le foto)
- [~] filester → plugin Python (cartelle con `onclick`, API `/v2/api/public/download`)
- [x] Gofile → plugin Python (API `contents`, token ospite → cookie `accountToken`)
- [~] OnlyFans profilo (media) → plugin Python (con la sessione del browser interno)
- [~] OnlyFans chat (galleria, foto e video sbloccati) → plugin Python
- [~] Fansly → plugin Python
- [~] ImageFap (galleria e categoria) → plugin Python
- [~] Tumblr → plugin Python
- [x] happymodal → plugin Python (gallerie ed elenchi)
- [x] blinkgirl, gedecomix → plugin Python
- [~] jliji, av01, X (Twitter) → plugin Python
- [x] Togliere i template EPF da `picfinder/templates/` (restano solo i plugin nostri; i `.etmpl` dell'utente funzionano ancora)
- [x] Test per ogni plugin con pagine finte (come Koofr e pixeldrain)
- [x] Licenza **MIT**, repo pubblico

## 2. Pubblicazione e installazione

- [ ] Primo push della 0.2.0 su GitHub e prima Release con le app (Mac e Windows) create da GitHub Actions
- [ ] App per Mac **firmata e notarizzata** da Apple (Developer ID): niente più «tasto destro → Apri»
- [ ] App per Mac anche **Intel** (o universale)
- [ ] Windows: risolvere l'errore `'lazy_import' object is not callable` (probabile Python 3.15) e provare tutto
- [ ] Linux: pacchetto AppImage
- [ ] Aggiornamenti: firma dei pacchetti (oltre allo SHA-256) e canale «beta» facoltativo
- [x] Bloccare versioni di PySide6 provate (`>=6.8,<6.13`, Python `<3.15`) per non rompersi con un aggiornamento

## 3. Problemi aperti

- [ ] Bunkr: i video richiedono ancora la pagina di ogni file (l'elenco «gallery» dà solo le foto) → strada veloce per le foto negli album misti (serve un album di prova con foto e video)
- [ ] Provare davvero filester, OnlyFans, Fansly, pixeldrain, ImageFap, Tumblr, jliji, av01, X e segnarli «Supportato, provato»
- [x] Repo privato: l'aggiornamento automatico vuole un token GitHub → istruzioni guidate dentro l'app (apre GitHub con i campi pronti)
- [x] Cambio lingua e tema: subito, senza riavviare

## 4. Funzioni nuove

- [x] **Vista a griglia** delle anteprime, con barra spaziatrice = anteprima veloce (come il Finder)
- [x] **Notifiche vere del Mac** e numero dei file mancanti sull'icona nel Dock
- [x] **Cerca nei file scaricati**: per nome, cartella/profilo, tipo (Strumenti → Cerca nei file scaricati…)
- [x] **Esporta / importa** progetti e impostazioni (File → Esporta…; proxy e token solo se lo chiedi)
- [x] **Controllo dei siti** a mano (Strumenti → Controlla i siti…): cerca senza scaricare un link per sito
- [ ] Controllo dei siti da solo ogni giorno, con avviso
- [ ] Aggiornamento dei template/plugin **senza** aggiornare tutta l'app
- [ ] Segnalazione dei crash facoltativa (con il permesso dell'utente, senza dati personali)

## 5. Qualità del codice

- [x] Dividere `gui.py`: tema in `theme.py`, pezzi della finestra in `widgets.py`, griglia in `gridview.py`
- [ ] Dividere ancora `MainWindow` (azioni, ricerca, download)
- [x] Test dell'interfaccia (avvio, stati, lingua e tema, griglia, Dock) in GitHub Actions a ogni push (`packaging/github-tests.yml`)
- [x] Controllo automatico che ogni testo abbia la traduzione inglese (`tests/test_i18n_copertura.py`)
- [x] Documentazione per scrivere un plugin Python nuovo: [docs/plugins.md](docs/plugins.md)

---

## Regole che restano sempre

- Niente aggiramento di DRM o flussi cifrati.
- Niente proxy che cambiano per evitare limiti o blocchi; i proxy cambiano solo se il proxy stesso non va.
- Nessun travestimento (impronte del browser finte, «stealth»).
- OnlyFans/Fansly: solo il proprio account e i contenuti a cui si è abbonati; niente proxy (timeout).
- Nessun parser per siti di leak (Coomer, Kemono e simili).
- Password e token mai nei log, proxy e impostazioni mai nel repo.
