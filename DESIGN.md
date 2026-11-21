# PicFinder — lista design

Analisi del 14/11/2026. Guardata finestra principale (vuota, ricerca, scelta file, download) e Impostazioni.
Spunta `[x]` quando è fatto.

## Fase 1 — Errori che si vedono (prima di tutto)

- [x] **Bottoni a destra dei link schiacciati.** «Cerca file», «Incolla», «Browser» hanno il testo tagliato a metà. Durante il download il bottone rosso è vuoto.
- [x] **Anteprima: testo sopra testo.** «Caricamento anteprima…» finisce sopra il nome del file.
- [x] **Menu a tendina rotti.** La freccia di «Categoria» e delle tendine in Impostazioni ha un riquadro bianco con bordo storto.
- [x] **Testi di aiuto tagliati** in Impostazioni (es. «Se un server risponde…» finisce a metà, righe una sopra l'altra vicino a «Dimentica tutto»).
- [x] **Impostazioni: voce scelta a sinistra** con un rettangolo di focus brutto intorno.

## Fase 2 — Spazio e ordine

- [x] **La lista file è troppo piccola.** Il modulo in alto prende metà finestra: si vedono solo 4-5 file.
  - Modulo più compatto: Link grande, sotto una riga con Password · Cartella · Opzioni.
  - Progetto e Categoria in una riga sottile sopra (o nel pannello progetti).
  - Durante scelta e download il modulo si chiude in una riga («2 link · mario, gofile» + «Modifica»).
- [x] **5 riquadri grandi dei numeri** (Trovati, Selezionati…): diventano una riga sottile di numeri colorati sopra la lista.
- [x] **Filtri sopra le schede.** «Tutti / Nessuno / Solo immagini / Solo video / Filtra» valgono solo per «File»: vanno dentro la scheda File.
- [x] **Anteprima più grande** e ridimensionabile (divisore trascinabile tra lista e anteprima).
- [x] **Pannello progetti:** vuoto con testo in fondo. Messaggio vuoto al centro, bottoni Aggiorna/Elimina solo quando c'è un progetto scelto.
- [x] **Intestazione:** titolo + sottotitolo prendono spazio. Una barra unica: logo · nome · (template, rete, impostazioni) a destra.
- [x] **Barra in basso:** «Pronto…» + rete. Tenere, ma testo più piccolo e grigio.

## Fase 3 — Coerenza (sembrare professionale)

- [x] **Icone:** ora emoji miste (⚡ ⚙ ▶ 🗂) che cambiano da Mac a Windows. Un solo set di icone a linea, stesso colore e dimensione.
- [x] **Bottoni: 3 tipi soltanto,** stessa altezza (32 px), stessi angoli:
  - principale (viola pieno) — una sola azione per schermata,
  - secondario (bordo grigio),
  - leggero (solo testo, es. «Apri cartella»).
- [x] **Scritte:** una scala sola — titoli sezione, testo normale, aiuto grigio piccolo. Etichette in MAIUSCOLO tutte uguali.
- [x] **Tabella file:**
  - dimensione allineata a destra,
  - stato come etichetta colorata (Completato, Errore, Già presente…),
  - colonna miniatura piccola,
  - righe un po' più alte, colori alternati leggeri.
- [x] **Lista vuota:** disegno semplice + «Incolla un link per iniziare» + scorciatoie (⌘V, Invio).
- [x] **Impostazioni:**
  - aiuti più corti, il resto in un «?» con spiegazione al passaggio del mouse,
  - gruppi con titoletto (es. Velocità, Cartelle, Doppioni),
  - icone a sinistra nelle voci,
  - titolo della finestra.
- [x] **Tema scuro:** controllare tutte le schermate, anche Impostazioni e browser interno.

## Lingua

- [x] Inglese e italiano (Impostazioni → Generale → Lingua). Il registro tecnico resta in italiano.

## Fase 4 — Rifiniture

- [x] Icona dell'app (Dock, barra di Windows) e finestra «Informazioni» curata.
- [ ] Animazioni leggere: barra di avanzamento morbida, comparsa dei file trovati.
- [ ] Notifiche più chiare a fine download (quanti, dove, errori cliccabili).
- [x] Scorciatoie da tastiera visibili nei menu.
- [x] Finestra del browser interno con lo stesso stile dell'app.
- [ ] Controllo finale su Mac, Windows e Linux con screenshot prima/dopo.
