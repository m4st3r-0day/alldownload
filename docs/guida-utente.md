# Guida utente

[English](user-guide.md)

- [La finestra](#la-finestra)
- [Scaricare da un link](#scaricare-da-un-link)
- [Progetti](#progetti)
- [Il browser interno](#il-browser-interno)
- [Cartelle e doppioni](#cartelle-e-doppioni)
- [Pausa, ripresa, coda](#pausa-ripresa-coda)
- [Impostazioni](#impostazioni)
- [Proxy](#proxy)
- [Mandare link dal browser](#mandare-link-dal-browser)
- [Strumenti](#strumenti)
- [Scorciatoie](#scorciatoie)
- [Dove sono i tuoi dati](#dove-sono-i-tuoi-dati)

## La finestra

![Finestra principale](images/main-it.png)

| Zona | A cosa serve |
|---|---|
| **Colonna a sinistra** | Progetti salvati (per categoria), *Download rapido*, e in fondo: template attivi, rete, impostazioni. |
| **Link** | Incolli uno o più link, uno per riga. Sotto vedi a quale servizio appartiene ogni link. |
| **Opzioni** | Nome e categoria del progetto, password (per i link protetti), cartella di destinazione, e due scelte: *Scarica tutto subito* e *Tutti i tipi di file*. Le opzioni si chiudono durante la ricerca, per lasciare spazio alla lista. |
| **Risultati** | Contatori (trovati, selezionati, scaricati, già presenti, errori), barra di avanzamento, lista dei file con anteprima, e la scheda **Registro**. |

## Scaricare da un link

1. Incolla un link (o trascinalo nella finestra) e premi **Invio** o **Cerca file**.
2. I file compaiono mentre vengono trovati. Clicca su un file per l'anteprima.
3. Scegli i file: caselle, oppure **Tutti / Nessuno / Immagini / Video**, oppure scrivi nel filtro.
4. Premi **Scarica N file**.

**Scarica tutto subito:** con questa opzione i file partono appena trovati, senza scegliere.

**Colonna Stato:**

| Stato | Significato |
|---|---|
| Da scaricare | Spuntato, in attesa. |
| Già scaricato | L'hai già scaricato (anche se il link è cambiato). Non spuntato. |
| Completato | Salvato. |
| Già presente | Nella cartella c'è già un file con stesso nome e stessa grandezza. |
| Doppione | La stessa foto esiste già con un altro nome. |
| Nuovo tentativo N | Il server era lento o occupato: riprovo. |
| Errore | Non salvato. Il motivo è nella scheda **Registro**. |

## Progetti

Un progetto ricorda link, cartella e opzioni.

- **Salva:** apri *Opzioni*, scrivi un nome (e se vuoi una categoria) e premi **Salva progetto**. Scorciatoia: Cmd/Ctrl+S.
- **Aggiorna:** scegli uno o più progetti (o una categoria intera) e premi **Aggiorna**. Scarica solo i file nuovi.
- **Tasto destro su un progetto:**
  - **Priorità nella coda:** alta, normale o bassa. Quando aggiorni più progetti, quelli con priorità alta vanno prima.
  - **Controlla da solo:** ogni ora, 6 ore, 12 ore o ogni giorno. Il controllo parte solo quando l'app è libera. I progetti osservati hanno l'icona dell'occhio.

## Il browser interno

Alcuni siti chiedono login, token o un controllo «sei umano?». Il template lo dice e il browser si apre da solo. Puoi aprirlo anche con **Browser**.

1. Fai login se serve.
2. Aspetta che si veda il contenuto. Usa **Scorri giù da solo**, o scorri tu, per caricarne di più (gallerie, chat).
3. Premi **Continua download**.

Il browser passa ai download la pagina, le sue richieste API e i cookie. I login restano per la volta dopo.

- **Home** torna al link di partenza (utile dopo un login che ti porta altrove).
- **Pulisci dati** cancella cookie e dati del browser interno, login compresi.
- **Cloudflare «sei umano?»:** se il controllo fallisce, AllDownload ricarica la pagina senza la sua cattura delle richieste. Tu completi il controllo, poi la cattura si riaccende.

Alcuni siti firmano i link dei file per un solo IP: quello del browser. Se col proxy un download viene rifiutato per questo, AllDownload scarica quei file senza proxy o con il browser interno stesso.

## Cartelle e doppioni

Ordine predefinito (*Impostazioni → Download → Cartelle*):

```
AllDownload/
  mario/            ← una cartella per link: profilo, album, cartella
    Foto/
    Video/
    Chat/           ← galleria della chat OnlyFans di questo utente
      Foto/
      Video/
  _Doppioni/        ← solo se scegli «Sposta in _Doppioni»
```

**Doppioni** (*Impostazioni → Download → Doppioni*):
- *Non riscaricare i file già scaricati:* ogni file scaricato viene ricordato con una chiave stabile, quindi si riconosce anche se il sito rifirma il link. Se cancelli un file dal disco, la volta dopo si riscarica.
- *Foto uguali con nome diverso:* non controllare, segnala come «Doppione», o sposta in `_Doppioni`. Usa un'impronta dell'immagine, quindi trova anche le copie ridimensionate.
- *Se il nome esiste già:* salta se ha la stessa grandezza, non salvare, salva come `nome_001`, o sovrascrivi.

## Pausa, ripresa, coda

- **Pausa** (bottone vicino ai contatori, o Cmd/Ctrl+P): i pezzi già scaricati restano. **Riprendi** continua da lì.
- Se chiudi l'app durante un download, al prossimo avvio ti chiede se riprendere.
- Link scaduti: alcuni siti firmano i link per poco tempo. Prima del download AllDownload lo controlla e ti propone di rifare la ricerca e scaricare gli stessi file.

## Impostazioni

Si aprono con Cmd/Ctrl+, o dalla colonna a sinistra.

| Pagina | Opzioni principali |
|---|---|
| **Generale** | Lingua, tema, cartella predefinita, avvisi. |
| **Download** | File insieme, per server, connessioni adattive, pezzi per i file grandi, HTTP/2, pause tra i file (come il template / dimezzate / minime), limite di velocità, tentativi, attesa, cartelle, doppioni. |
| **Orari e limiti** | Scarica solo in una fascia oraria, pausa a batteria, quota di banda (es. 70% della linea), avviso di richieste al giorno per sito, ogni quanto controllare i progetti osservati. |
| **Rete e proxy** | Uso dei proxy e lista, indirizzo di prova, User-Agent personalizzato. |
| **Anteprime** | Miniature automatiche, grandezza massima, percorso di ffmpeg. |
| **Browser interno** | Tempo per continuare da solo nelle code. |
| **Registro** | Registro dettagliato nella finestra, quanti file di log tenere. |

Lingua e tema nuovi si vedono al prossimo avvio.

![Impostazioni](images/settings-it.png)

## Proxy

*Impostazioni → Rete e proxy.*

- **Aggiungi…** accetta un proxy per riga: `http://host:porta`, `socks5://utente:password@host:porta`, oppure `ip:porta:utente:password`.
- **Lista da link…** carica una lista da un indirizzo (per esempio il link di download di Webshare). Si riscarica a ogni avvio.
- **Prova tutti** misura ogni proxy. Con *il più veloce che risponde* usa il più rapido.
- Se un proxy non risponde si passa al prossimo. Se invece è il **sito** a rifiutare (403/429), il proxy resta: l'app rallenta.

Le password sono nascoste nella finestra e nel registro. Chi gestisce un proxy vede il tuo traffico: usa proxy di cui ti fidi.

## Mandare link dal browser

*Strumenti → Manda ad AllDownload dal browser…*

- **Segnalibro** (Safari, Chrome, Firefox): crea un segnalibro e come indirizzo incolla il testo mostrato. Cliccalo su una pagina: il link arriva in AllDownload.
- **Estensione per Chrome** (Chrome, Edge, Brave): carica la cartella `extension/` da `chrome://extensions` → *Modalità sviluppatore* → *Carica estensione non pacchettizzata*. Aggiunge «Manda ad AllDownload» ai menu della pagina e dei link.

Tutti e due usano link `alldownload://`, che funzionano con l'app installata su Mac.

## Strumenti

- **Statistiche** (Cmd/Ctrl+I): file e spazio per sito, richieste di oggi, errori, e i limiti di connessione imparati per ogni server.
- **Editor dei template** (Cmd/Ctrl+E): apri, modifica e prova un template su un link, con il registro completo.
- **Template** (Cmd/Ctrl+T): tutti i template con servizio, tipo, compatibilità e un interruttore per attivarli.

## Scorciatoie

| Azione | macOS | Windows / Linux |
|---|---|---|
| Cerca / scarica | Invio o ⌘↩ | Invio o Ctrl+Invio |
| Incolla | ⌘V | Ctrl+V |
| Browser interno | ⌘B | Ctrl+B |
| Salva progetto | ⌘S | Ctrl+S |
| Nuovo progetto | ⌘N | Ctrl+N |
| Pausa / riprendi | ⌘P | Ctrl+P |
| Template | ⌘T | Ctrl+T |
| Editor dei template | ⌘E | Ctrl+E |
| Statistiche | ⌘I | Ctrl+I |
| Impostazioni | ⌘, | Ctrl+, |
| Apri cartella dei download | ⇧⌘D | Ctrl+Maiusc+D |

## Dove sono i tuoi dati

| | macOS | Windows | Linux |
|---|---|---|---|
| Cartella base | `~/Library/Application Support/PicFinder` | `%APPDATA%\PicFinder` | `~/.local/share/PicFinder` |

Dentro la cartella base:

| File / cartella | Contenuto |
|---|---|
| `settings.json` | Impostazioni (anche le password dei proxy). |
| `picfinder.db` | Progetti, storico dei download, contatori, impronte delle foto. |
| `templates/` | I template che hai aggiunto tu. |
| `browser/` | Profilo del browser interno (login). |
| `log/` | Registri delle sessioni, `crash.log`. |
| `limiti_siti.json` | Limiti di connessione imparati per ogni server. |
| `pagine.sqlite` | Copie delle pagine (per aggiornare più in fretta). |

La cartella si chiama ancora `PicFinder`, il nome iniziale del progetto: così i dati che hai già continuano a funzionare. I percorsi esatti sono in *Informazioni su AllDownload*.
