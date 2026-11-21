# PicFinder: funzionalità e idee

Scrivi qui le funzionalità che vuoi, i bug, i siti da aggiungere e tutto il resto.
Usa le caselle: `[ ]` = da fare, `[x]` = fatto.
Quando vuoi che lavori su qualcosa, dimmi solo "leggi FUNZIONALITA.md".

---

## ✅ Già fatto (v0.1)

- [x] Motore di download in Python (download paralleli, 3 tentativi, ripresa con file `.part`)
- [x] Salta i file già scaricati (stesso nome e dimensione)
- [x] Lettura dei template `.etmpl` di Extreme Picture Finder
- [x] Template Koofr incluso, con il bug delle sottocartelle corretto
- [x] Sezione extra `[PicFinderStart]` per partire diretto dall'API
- [x] Plugin Python per i siti troppo complicati per un `.etmpl`
- [x] Riga di comando (`python -m picfinder <link>`)
- [x] Finestra grafica: tema chiaro/scuro, contatori, tabella file, velocità, registro
- [x] Trascina un link o un `.etmpl` nella finestra
- [x] Ricorda l'ultima cartella di destinazione
- [x] Test automatici con un finto server Koofr

---

## 🧩 Funzionalità da aggiungere (prese da Extreme Picture Finder 3.1 → 3.72)

<!-- Tra parentesi la versione EPF. [x] = già fatto in PicFinder. Aggiungi le tue idee in fondo. -->

### Ordine consigliato

1. Progetti salvati, "Aggiorna", coda e categorie (base per quasi tutto)
2. Nomi dei file, sottocartelle e conflitti
3. Motore template completo (tutte le funzioni dei Custom Parsers) + tester
4. Video a pezzi (m3u8 / mpd) e analisi pagine migliore
5. Browser interno (login, richieste JSON, siti JavaScript)
6. Visualizzatore di immagini
7. Database online dei template
8. Ricerca immagini sul web

---

### A. Progetti, coda e automazione

- [x] Progetti salvati con tutte le impostazioni (3.x)
- [x] Più indirizzi di partenza, modificabili come testo (copia/incolla), con [Importa] [Esporta] [Genera] (3.4, 3.23, 3.37) — fatto il campo a più righe; Importa/Esporta/Genera ancora no
- [ ] Generatore di URL: `pagina1 … pagina50`, con cifre minime e passo (3.5, 3.42.4)
- [x] "Aggiorna": solo i file nuovi, non riscarica quelli cancellati, solo gli indirizzi selezionati (3.9.2, 3.13.2, 3.15)
- [x] Albero unico con progetti e ricerche, divisi in categorie; sposta con un clic (3.10, 3.35) — fatto per i progetti (le ricerche web non ci sono ancora)
- [x] Selezione multipla: avvia, sposta, elimina più progetti; quelli avviati vanno in coda (3.43) — avvia ed elimina sì; sposta: cambia la categoria e salva
- [x] Avvia tutta una categoria, un progetto dopo l'altro; "Riprendi" parte dal primo non finito (3.35, 3.39) — "Riprendi dal primo non finito" ancora no
- [x] Contatore accanto al progetto: file salvati / non salvati, es. (120/-3) (3.6, 3.63)
- [ ] "Al termine": esporta lista, avvia un altro progetto, esegui un comando/script con la cartella di destinazione (3.19, 3.67)
- [ ] Condizioni di stop: fermati a un orario, dopo N file, ecc. (3.68.10)
- [x] Riga di comando per avviare/aggiornare progetti da Utilità di pianificazione, cron o launchd (3.17) — `python -m picfinder --aggiorna "Nome o Categoria"` / `--aggiorna tutti` / `--progetti`
- [ ] Impostazioni predefinite salvabili per progetti e ricerche (3.5.4, 3.25.1)
- [ ] Salvataggio veloce anche con migliaia di indirizzi, con avanzamento (3.13.4, 3.24.1)
- [x] Riga di comando di base (`python -m picfinder <link>`)

### B. Esplorazione del sito

- [ ] Modalità: solo pagina corrente / cartella corrente e più giù / intero sito (3.13, 3.53.2)
- [ ] Limite di profondità (fino a 4 cifre) per tutte le modalità; profondità visibile nel registro (3.13.2, 3.54.1, 3.53, 3.65.2)
- [ ] Generare indirizzi di partenza extra da regex nel template (pagine di forum, `/page-2` …) (3.30)
- [ ] Scarica gli indirizzi nell'ordine della coda (contro l'errore 429) (3.71)
- [x] Ritardo casuale tra i download, anche nei nuovi tentativi (3.20.1, 3.67.1) — fatto per i template (MinDelay/MaxDelay)
- [ ] Numero di connessioni contemporanee per progetto (3.42) — dai template sì (SuggestedSimultaneousConnections), da interfaccia no
- [ ] Ridownload dell'indirizzo padre dopo un redirect (3.48)
- [ ] Redirect verso l'indirizzo di partenza permesso in automatico (3.62)
- [x] Gestione `#` negli indirizzi senza giri infiniti (3.13.3, 3.28.2)
- [x] Download paralleli, l'interfaccia non si blocca (3.11, 3.24.1)

### C. Analisi delle pagine

- [x] Link nel testo semplice, HTML con errori, più attributi dei tag (3.8.2, 3.5.4.8, 3.64.1)
- [x] CSS `url(...)`, `background=` su ogni tag, `<script>` (3.6.1, 3.13.3, 3.13.2)
- [x] `srcset` delle immagini (3.14.6, 3.44.1)
- [ ] Regex personalizzate aggiunte al parser generico (3.24.1)
- [x] Analizza anche le pagine di errore HTTP (opzione on/off) (3.65, 3.66) — se il template ha ParseErrorPages=True
- [ ] Gallerie TGP: dalla miniatura all'immagine grande (3.2, 3.3, 3.26)
- [ ] Siti JavaScript (vedi browser interno, sezione F) (3.17, 3.24.1)

### D. Video

- [ ] File `.m3u8` (HLS): sceglie la risoluzione massima, scarica chiavi, file di inizializzazione, audio separato (3.63, 3.66.15, 3.68.12, 3.68.16, 3.70)
- [ ] Salva l'`.m3u8` pulito con i pezzi in una sottocartella, pronto per `ffmpeg -i index.m3u8 output.mp4` (3.68.16, 3.70)
- [ ] Opzione: unire i pezzi in un unico `.mp4` con ffmpeg in automatico (idea nostra)
- [ ] File `.mpd` (DASH) (3.64.4)
- [ ] Video con audio separato (es. stile Reddit) (3.65.13)
- [ ] File grandi (> 10 MB, > 1,8 GB) senza problemi (3.35, 3.59, 3.65.10)

### E. Nomi dei file, sottocartelle e conflitti

- [ ] Scelta tipi file con caselle (immagini, video come `.webm`, …) (3.7, 3.41.2)
- [ ] Nome da: [fatto: attributo del tag, es. alt] titolo pagina, nome file della pagina, URL completo, parametro dell'indirizzo, attributo del tag, regex sul file o sulla pagina padre, data-ora `ANNO-MES-GIO ORA-MIN-SEC-MS` (3.5.3, 3.8, 3.8.1, 3.16, 3.33, 3.46, 3.51.1)
- [ ] Scegliere quale pagina padre usare per il nome (3.15.3)
- [ ] Togliere N caratteri all'inizio/fine; prefisso e suffisso (spazi compresi) (3.51.2, 3.39)
- [x] Estensione personalizzata; file senza estensione con `*.` (3.5, 3.13.5) — fatto `*.`; estensione personalizzata ancora no
- [x] Nome reale da Content-Disposition (con priorità) e da Content-Type, UTF-8 (3.14.6, 3.41, 3.53.7)
- [ ] Nomi numerici che partono da un numero scelto (3.41.3)
- [ ] Sottocartelle: per ogni indirizzo di partenza, dal titolo della pagina, dal parametro dell'indirizzo, copiando la struttura del sito o dell'indirizzo del file, cartella col dominio se il file è su altro sito (3.16, 3.27, 3.34, 3.40, 3.51, 3.64)
- [ ] Conflitti: [fatto dai template: non salvare / rinomina `_001` / sovrascrivi] — manca rinomina stile Windows `nome (2).jpg` con cifre scelte (3.9, 3.27.4, 3.39)
- [x] Niente `:` o caratteri vietati nei nomi; nomi troppo lunghi accorciati (3.38.1, 3.49.1)
- [x] Caratteri Unicode nei nomi (3.44)
- [x] Sottocartelle da regex sull'indirizzo padre (`sfmParentURLRE`)

### F. Browser interno (con Chromium di Qt: QtWebEngine è già dentro PySide6)

- [x] Login manuale su siti con form, forum, social; anche accesso con Google/Apple/Facebook (3.4, 3.21, 3.24.4, 3.66.12)
- [x] Usa cookie, proxy e User-Agent dell'app; capisce da solo se sei già connesso (3.21, 3.34.1, 3.40, 3.60.1) — cookie e User-Agent sì; il proxy nel browser interno non ancora
- [ ] Salta il browser se l'accesso è già salvato (utile in coda) (3.59)
- [x] Barra indirizzi, Indietro, Avanti, Home (= indirizzo di partenza) (3.72)
- [x] Elenco delle richieste JSON/XHR della pagina, con intestazioni, da aggiungere alla coda (3.53, 3.63, 3.68.5) — catturate in automatico e usate dal template (contatore in basso); scelta a mano non ancora
- [ ] Elenco di link e immagini della pagina caricata, da scegliere e aggiungere (3.39, 3.53)
- [x] Scorrimento automatico verso il basso (3.68)
- [x] Chiusura automatica dopo X secondi o dopo una certa richiesta AJAX (3.65) — nella coda: continua da solo 10 s dopo il caricamento
- [ ] Regex applicate in automatico agli indirizzi del browser (3.60)
- [x] Controlli Cloudflare risolti dall'utente nel browser, poi il download continua (3.69, 3.70.7) — dipende dal sito: alcuni legano il controllo al browser e lo rifiutano ai download
- [x] Opzione "login manuale" e utente/password copiati dal template (3.38, 3.42.6)

### G. Rete e richieste

- [ ] Password HTTP (Basic Auth) nelle intestazioni, anche email come utente (3.5.1, 3.6.1.1, 3.23)
- [ ] Referer: on/off, valore personalizzato per tutti o per regex (3.5.5, 3.61)
- [x] Intestazioni HTTP personalizzate per qualsiasi indirizzo (3.63) — testo fisso sì; "copia dal browser" quando ci sarà il browser interno
- [ ] Client Hints insieme allo User-Agent (3.69)
- [ ] Accetta o ignora i cookie (3.28.1)
- [x] Proxy HTTP, SOCKS4, SOCKS5 (3.7, 3.46.2)
- [ ] Errori di connessione: riprova senza fermare tutto; stop se il disco è pieno (3.33, 3.40)
- [x] Ridownload automatico di file interrotti, incompleti, danneggiati; i parziali (206) non vengono salvati (3.62.2, 3.67) — fatto: file incompleti riprovati e mai salvati a metà
- [ ] Ridownload di un file con tasto destro (3.19)
- [ ] Limiti di dimensione file [minimo: fatto dai template] e di pixel per le immagini (solo sulle immagini) (3.21.4, 3.53.3, 3.58)
- [ ] File da 0 byte salvati senza errori (3.34)
- [x] HTTPS e TLS 1.3 (3.6, 3.62)
- [x] Richieste POST dai Custom Parsers (3.49)

### H. Motore dei template (Custom Parsers)

- [x] Riferimenti `[#n]`, `[#k:n]`, `[#-k:n]` nel Result (3.37, 3.62.3)
- [x] URL della pagina aggiunto al testo prima dell'analisi (3.45)
- [x] Funzioni `JSONDecode` e `jsonencode` (3.53.4)
- [x] Riferimenti `[#+k:n]` e riferimenti usati anche dentro l'Expression (3.39.1, 3.62.3, 3.65.11) — fatto [#+k:n]; dentro l'Expression ancora no
- [ ] Riferimenti relativi usati dentro le funzioni (3.64.2)
- [ ] Aggiungere al testo anche le pagine che hanno portato qui e i dati POST (3.45, 3.63.4)
- [ ] Cicli: più URL da una regex con `[$da-a$cifre$passo$]` (3.27, 3.28.2, 3.42.4, 3.46)
- [x] Funzioni: `Math(a+b)`, `Replace` (anche su più righe), `Base64Decode`, `Base64Encode`, `CharFromCode`, `CharFromHexCode`, `DecToHex`, `HexToDec` (3.42, 3.54, 3.62.1, 3.64.2, 3.65.2, 3.44.1, 3.46.3) — fatte Base64Decode/Encode, DecToHex, HexToDec; mancano Math, Replace, CharFromCode
- [x] Content-Type per le richieste POST (3.57)
- [x] Excluded Page Parts: tolto solo se From e To combaciano entrambi (3.42) — controllare il nostro motore
- [ ] Parser dedicati a siti specifici (fatto il sistema in `sitehooks.py` + Bunkr), scritti in Python come plugin (Flickr, Instagram, x.com, Reddit, Tumblr, DeviantArt, SmugMug, imgur, …) (3.6x–3.7x)

### I. Editor e strumenti per template

- [ ] Editor di template dentro l'app (3.29)
- [ ] Tester di regex con risultati ad albero (3.49)
- [ ] Tester di Excluded Page Parts (3.48)
- [ ] Avviso se un template richiede una versione più nuova (3.41)

### J. Database online dei template

- [ ] Esplora, cerca e scarica template da un archivio online; più template insieme (3.1, 3.2, 3.29, 3.35)
- [ ] Ricorda quali hai scaricato; controlla se ci sono versioni nuove e avvisa (3.2, 3.38)
- [ ] Versione del template visibile (3.37)
- [ ] Condividi i tuoi template in modo anonimo (3.29)
- [ ] Nascondi categorie, richiedi categorie nuove (3.4, 3.6)
- Nota: serve un nostro archivio (es. repository GitHub con un indice JSON dei template)

### K. Ricerca immagini sul web

- [ ] Più motori: Google, Bing, Yahoo, Flickr, Imgur, Yandex, DuckDuckGo, Naver, OpenClipart (3.13 → 3.50)
- [ ] Modalità: immagini a grandezza piena (predefinita) e correlate simili, senza doppioni (3.3, 3.23)
- [ ] Più frasi di ricerca per progetto; limite di risultati per motore; filtri URL (3.26)
- [ ] Cartelle separate per frase e per motore; titolo personalizzato (3.18, 3.26, 3.35)
- [ ] SafeSearch; "Aggiorna" con solo i risultati nuovi (3.13.1, 3.14)
- [ ] Nomi file e conflitti anche per le ricerche (3.18)
- Nota: molti motori bloccano la lettura automatica e cambiano spesso; da valutare con API ufficiali dove esistono

### L. Lista file, registro e monitor

- [ ] Monitor dei download con stato di ogni indirizzo, senza sfarfallio (3.23, 3.36)
- [x] Registro: perché un indirizzo è saltato o filtrato, redirect, codici HTTP, intestazioni (3.31, 3.63, 3.67)
- [x] Registro veloce anche con molte righe; selezione multipla (3.53.2, 3.59.3)
- [ ] Cerca per nome nella lista dei file scaricati (3.25.1)
- [ ] Rinomina file; riscarica; copia o apri l'indirizzo del file o della pagina padre (3.42.5, 3.56, 3.66)
- [ ] Ordinamento che rispetta i numeri nei nomi (`img2` prima di `img10`) (3.56, 3.71)
- [ ] Esporta la lista dei file: colonne a scelta, intestazione, data/ora, solo file esistenti (3.15, 3.15.2, 3.24.1, 3.35)
- [ ] Conferme configurabili (es. prima di eliminare) (3.34)

### M. Visualizzatore di immagini

- [ ] Miniature veloci anche con 1000+ immagini, poca memoria (3.1, 3.6.1, 3.23)
- [ ] Formati: GIF animate, WebP, HEIC, alcuni RAW; salta i non supportati (3.7, 3.28, 3.53.6, 3.68.10)
- [ ] Presentazione (slideshow), elimina con selezione del file successivo (3.31, 3.34.1)
- [ ] Immagini correlate come miniature sotto quella grande (3.23)
- [ ] Crea una galleria web HTML dalle immagini scaricate (3.5.6)

### N. App

- [ ] Controllo automatico degli aggiornamenti (3.5)
- [ ] Segnalazione errori inviata al nostro server (3.34.1)
- [ ] Finestre posizionate bene se cambiano i monitor (3.33.1)

### Non le rifacciamo

- Flash SWF/FLV (Flash non esiste più)
- Motori chiusi o tolti: Altavista, AllTheWeb, PicSearch, Ask, SkyDrive
- Internet Explorer, correzioni per Windows XP/Vista, SSL v3 (insicuro), limiti della versione di prova

### Le mie idee

- [ ] 
- [ ] 

---

## 🌐 Siti e template

<!-- Siti da supportare. Se hai il template EPF, mettilo nella cartella e scrivi il nome del file. -->

| Sito | Stato | Template / note |
|---|---|---|
| Koofr | ✅ funziona | `picfinder/templates/koofr.etmpl` |
| imagefap (galleria) | ✅ provato su sito finto | `picfinder/templates/imagefap_gallery.etmpl` |
| imagefap (categoria) | ✅ caricato | `picfinder/templates/imagefap_categoria.etmpl` |
| Bunkr (album) | ✅ provato su sito finto | `bunkr_album.etmpl` + parser dedicato in `sitehooks.py`; in EPF usa il login manuale |
| Tumblr (blog) | 🌐 browser interno (si apre da solo) | `tumblr_blog.etmpl`: copia l'autorizzazione dal browser |
| pixeldrain (lista e file) | ✅ plugin Python con API (veloce, con miniature) | `plugins/pixeldrain.py`; il template `pixeldrain.etmpl` resta come riserva |
| filester | ✅ provato su sito finto | `filester.etmpl`; in EPF chiede di provare di essere umano |
| Gofile | 🌐 browser interno (si apre da solo) | `gofile.etmpl`: token copiato dal browser — provato su sito finto |
| Fansly (media profilo) | 🌐 browser interno: login col tuo account | `fansly_media.etmpl`: usa il TUO account, sessione copiata dal browser |
| OnlyFans (profilo) | 🌐 browser interno: login col tuo account | `onlyfans_profilo.etmpl`: usa il TUO account, sessione copiata dal browser |
|  |  |  |

---

## 🎨 Grafica e interfaccia

- [x] Anteprime dei video: miniatura del sito oppure fotogramma con ffmpeg, con simbolo ▶
- [x] Registro nella finestra (Dettagliato / Copia / Salva / Cartella log) + file di log per ogni sessione

- [ ] 
- [ ] 

---

## 🐞 Bug e problemi

<!-- Cosa hai fatto, cosa ti aspettavi, cosa è successo. Incolla eventuali errori dal Registro. -->

- [ ] 

---

## 📦 Distribuzione (Windows, Mac, Linux)

- [ ] App per Mac (`.app` / `.dmg`) con icona
- [ ] App per Windows (`.exe` / installer)
- [ ] App per Linux (AppImage)
- [ ] Build automatica per i 3 sistemi con GitHub Actions

---

## 💡 Idee per il futuro (da valutare)

<!-- Cose non urgenti. Esempi che possiamo considerare: -->

- [x] Coda di più link da scaricare uno dopo l'altro
- [x] Anteprima miniature delle immagini trovate prima di scaricare
- [x] Scegliere a mano quali file scaricare (Cerca file → caselle → Scarica selezionati)
- [ ] Pausa e ripresa dei download
- [ ] Limite di velocità
- [x] Cronologia dei download (SQLite)
- [ ] Editor di template dentro l'app
- [ ] Aggiornamento automatico dei template
- [ ] Browser interno per i siti con login (come il "Manual login" di EPF)
- [ ] Lingua inglese oltre all'italiano

---

## 📝 Note libere

