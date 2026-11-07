<p align="center"><img src="docs/icon.png" width="96" alt=""></p>

<h1 align="center">Image SlideShow Viewer</h1>

<p align="center">
Visualizzatore di immagini per Windows in stile ACDSee: albero delle cartelle e browser a miniature,
visualizzatore a schermo intero, slideshow che salta da una cartella all'altra, archivi CBZ/ZIP
e operazioni in blocco.<br>
<a href="README.md">English</a> · <b>Italiano</b>
</p>

---

## Funzioni

- **Browser** con albero delle cartelle e griglia di miniature (in cache su disco), ordinamento naturale per nome, data o dimensione.
- **Visualizzatore** con adatta alla finestra / 100% / zoom, rotazione automatica secondo l'EXIF, GIF e WebP animate.
- **Slideshow** con intervallo, ordine casuale, ripetizione e sottocartelle; **↓ / ↑ saltano alla cartella successiva / precedente** mentre scorre.
- **Archivi CBZ / ZIP** mostrati come cartelle con la copertina, da sfogliare come fumetti.
- **Rinomina in blocco** sul modello di ACDSee: modello, cerca e sostituisci, maiuscole/minuscole, inserisci testo, rimuovi testo, spazi, con anteprima immediata.
- **Conversione in blocco** in JPEG, PNG, WebP, BMP o TIFF, con qualità e ridimensionamento.
- **Copia / sposta / elimina** (nel Cestino) di file e cartelle.
- **Menu contestuale di Esplora risorse**: clic destro su una cartella, un archivio o un'immagine per avviare lo slideshow, rinominare o convertire.
- **Cartelle di rete**: scrivi `\\192.168.0.2` per vedere le cartelle condivise di un computer.
- Interfaccia in **italiano e inglese**, selezionabile dal menu.

## Requisiti

- Windows 10 o 11 (funziona anche su Linux e macOS, senza le parti specifiche di Windows)
- Python 3.10 o più recente
- [PySide6](https://pypi.org/project/PySide6/) 6.5 o più recente

## Installazione

1. Installa **Python 3.10 o più recente** da [python.org](https://www.python.org/) e spunta *"Add Python to PATH"*.
2. Scarica o clona questo repository.
3. Fai doppio clic su **`image_slideshow_viewer.pyw`**. Al primo avvio ti chiede se installare PySide6 (1-2 minuti), poi apre il programma. Con `.pyw` non compare la finestra nera del terminale; se qualcosa va storto vedi un messaggio d'errore e trovi i dettagli in `image-slideshow-viewer-error.log`.

Da terminale:

```
pip install -r requirements.txt
python image_slideshow_viewer.pyw                 (apre il browser)
python image_slideshow_viewer.pyw D:\Foto         (apre il browser su una cartella)
python image_slideshow_viewer.pyw foto.jpg        (apre subito il visualizzatore)
python image_slideshow_viewer.pyw fumetto.cbz     (apre l'archivio come un fumetto)
python image_slideshow_viewer.pyw --slideshow D:\Foto D:\Fumetti\vol1.cbz
python image_slideshow_viewer.pyw --rename  file1.jpg file2.jpg …
python image_slideshow_viewer.pyw --convert file1.png file2.png …
```

### Creare un .exe e usarlo come programma predefinito per le foto

1. Fai doppio clic su **`build_exe.bat`**. Crea la cartella `dist\ImageSlideShowViewer\` con dentro `ImageSlideShowViewer.exe`.
   Usa l'exe dentro `dist`, non quello nella cartella `build`. Il file `warn-ImageSlideShowViewer.txt` è normale e si può ignorare.
2. Sposta l'intera cartella `dist\ImageSlideShowViewer` (non solo il file .exe, che ha bisogno della sottocartella `_internal`) dove preferisci, per esempio `C:\Programmi\ImageSlideShowViewer`.
3. In Esplora risorse fai clic destro su un .jpg, poi *Apri con → Scegli un'altra app → Cerca un'altra app nel PC*, seleziona `ImageSlideShowViewer.exe` e spunta *"Usa sempre"*. Ripeti per .png, .gif, .cbz e così via.

Da quel momento, con un doppio clic su una foto si apre il visualizzatore. **Invio** ti porta al browser su quella cartella, come in ACDSee.

## Menu contestuale di Esplora risorse

*Strumenti → Menu contestuale di Esplora risorse* aggiunge a Esplora risorse il sottomenu **Image SlideShow Viewer**:

| Clic destro su | Comandi |
|---|---|
| Una cartella, un disco o lo spazio vuoto di una cartella | Avvia slideshow |
| Un archivio `.cbz` / `.zip` | Avvia slideshow, Rinomina in blocco |
| Un'immagine | Avvia slideshow, Rinomina in blocco, Converti formato |

- Con più elementi selezionati si apre una sola finestra con tutti (per esempio un unico slideshow su tutte le cartelle selezionate, una dopo l'altra).
- Le voci vengono scritte solo per l'utente corrente (`HKEY_CURRENT_USER\Software\Classes`): non servono permessi di amministratore e togliendo la spunta dalla stessa voce di menu spariscono del tutto.
- Su Windows 11 il sottomenu è sotto **"Mostra altre opzioni"** (oppure Maiusc+F10).
- Se sposti il programma o passi dal `.pyw` all'`.exe`, le voci vengono aggiornate alla successiva apertura del programma. Anche il cambio di lingua le aggiorna.

## Browser

- A sinistra c'è l'albero delle cartelle, a destra la griglia: prima le sottocartelle (con l'anteprima della prima immagine), poi le immagini. Doppio clic o Invio su una cartella per entrarci, Backspace per tornare su.
- Le miniature restano in cache su disco, quindi alla seconda apertura di una cartella compaiono subito.
- Puoi ordinare per nome (con numeri naturali: foto2 viene prima di foto10), per data o per dimensione, anche in ordine decrescente.
- Il cursore *Miniature* cambia la dimensione delle anteprime. La cartella si aggiorna da sola quando i file cambiano.
- **Tasto destro** sulle miniature: visualizza, *Slideshow su «cartella»* (solo quella cartella o quell'archivio), slideshow, rinomina, converti, copia, sposta, elimina, mostra in Esplora risorse.
- **Archivi ZIP / CBZ:** compaiono come cartelle (in azzurro) con la copertina. Doppio clic per entrarci, oppure selezionali e avvia lo slideshow: sono trattati come cartelle anche dal salto cartella (↓/↑) e da "Includi sottocartelle". Le immagini dentro le sottocartelle dell'archivio vengono mostrate in ordine. Dentro un archivio non si possono rinominare né eliminare singole immagini; RAR/CBR e 7Z non sono supportati.
- **Rete:** nella barra del percorso puoi scrivere `\\192.168.0.2` (o il nome del computer) per vedere le sue cartelle condivise, oppure direttamente `\\192.168.0.2\Foto`. Con *Su* da una condivisione torni all'elenco delle condivisioni. Se il computer chiede una password, accedi prima una volta da Esplora risorse.

| Tasto | Azione |
|---|---|
| Invio / doppio clic | Apri la cartella o l'immagine |
| F5 | Slideshow |
| F2 | Rinomina in blocco |
| Ctrl+Maiusc+C | Converti formato |
| Ctrl+Maiusc+K / M | Copia in… / Sposta in… |
| Canc | Sposta nel Cestino |
| Backspace, Alt+↑ / Alt+← | Cartella superiore / Indietro |
| F1 | Elenco delle scorciatoie |

## Slideshow

Le opzioni sono nella seconda barra: **Intervallo**, **Casuale**, **Ripeti** e **Includi sottocartelle**.

- Con **una cartella selezionata**, lo slideshow parte da quella e prosegue con tutte le altre cartelle della vista. Tasto destro → *Slideshow su «cartella»* mostra solo quella.
- Con **più cartelle selezionate** (Ctrl+clic o Maiusc+clic), lo slideshow mostra solo quelle, una dopo l'altra.
- ↓/↑ portano sempre alla cartella successiva/precedente rispetto a quella che stai guardando, anche dopo aver scorso le immagini con →/←. Una cartella che contiene solo sottocartelle viene percorsa comunque con tutte le sue sottocartelle.
- Se non selezioni niente e la cartella corrente contiene solo sottocartelle, lo slideshow le percorre tutte.
- Con **più immagini selezionate**, lo slideshow mostra solo quelle; con **una sola immagine selezionata**, parte da quella.
- Con **Includi sottocartelle**, lo slideshow percorre la cartella e tutte le sottocartelle, una dopo l'altra. Se è attivo anche *Casuale*, mescola sia l'ordine delle cartelle sia le foto dentro ogni cartella. I tasti ↓/↑ restano dentro l'albero di partenza.
- Senza sottocartelle, lo slideshow ripete la cartella corrente (se è attivo *Ripeti*). Con ↓/↑ passi alla cartella vicina sul disco che contiene immagini, e lo slideshow continua da lì. Il salto si ferma alla cartella di primo livello del disco (per esempio `D:\Foto`) o alla cartella Immagini.

| Tasto | Azione |
|---|---|
| → ← , PagGiù/PagSu, rotellina | Immagine successiva / precedente |
| **↓ ↑** , Ctrl+→ / Ctrl+← | **Cartella successiva / precedente** |
| Spazio / P | Avvia o ferma lo slideshow (anche nel visualizzatore normale) |
| S | Ferma lo slideshow |
| O | Opzioni: nome cartella sì/no, colori, barra comandi |
| + / − | Intervallo più lungo / più corto |
| Home / Fine | Prima / ultima immagine della cartella |
| F, F11, doppio clic | Schermo intero |
| Z, * | Adatta alla finestra ↔ 100% |
| Ctrl+rotellina | Zoom (trascina per spostarti) |
| I | Informazioni (nome, dimensioni, cartella, stato) |
| Canc | Sposta nel Cestino |
| Invio | Torna al browser su questa immagine |
| Esc | Chiudi |

Muovendo il mouse compare in basso una **barra dei comandi** con *Avvia/Ferma*, immagine e cartella precedente/successiva, intervallo e *Opzioni*. Mentre lo slideshow è fermo, in alto a destra resta visibile l'indicatore "In pausa". Il tasto destro sull'immagine apre un menu con tutti i comandi.

### Opzioni (tasto O, o menu Strumenti → Opzioni visualizzatore e slideshow)

- Nome della cartella al cambio: attivo o disattivo, posizione (in alto, al centro, in basso) e durata.
- Altri avvisi (pausa, intervallo, zoom) e indicatore "In pausa": attivi o disattivi.
- Colore del testo, colore e opacità dello sfondo, dimensione del testo, con anteprima su fondo chiaro e scuro e combinazioni rapide (per esempio giallo su nero).
- Barra dei comandi al movimento del mouse: attiva o disattiva.

## Rinomina in blocco

Seleziona i file (immagini e anche archivi CBZ/ZIP) e premi **F2**, oppure usa il tasto destro nel browser o in Esplora risorse. Come in ACDSee, la rinomina è un **elenco di operazioni** applicate in ordine: spunta quelle che ti servono, cambiane l'ordine con ↑ / ↓, aggiungine altre con **+** (anche più dello stesso tipo) e toglile con **−**. L'anteprima mostra subito i nuovi nomi.

| Operazione | Cosa fa |
|---|---|
| **Modello** | Nuovo nome da un modello. `*` = nome originale, `#` = contatore (`###` → 001, 002…, oppure aa, ab… con le lettere). Campi: `{nome}`, `{cartella}`, `{data}`, `{ora}`, `{anno}`, `{mese}`, `{giorno}`, `{larghezza}`, `{altezza}` (valgono anche i nomi inglesi `{name}`, `{folder}`, `{date}`…). *Parti da*: valore fisso oppure **rileva automaticamente**, che continua una numerazione già presente nella cartella (Foto_001…Foto_012 → riparte da 013). |
| **Cerca e sostituisci** | Sostituisce tutte le occorrenze. Opzioni: maiuscole/minuscole, includi estensione, espressione regolare (con `\1`, `\2` nel testo sostitutivo). |
| **Maiuscole / minuscole** | Nome: minuscolo, MAIUSCOLO, Iniziali Maiuscole, solo la prima maiuscola. Estensione: minuscola o maiuscola (per uniformare .JPG e .jpg). |
| **Inserisci testo** | All'inizio, alla fine, dopo N caratteri, dopo o prima di un testo. Opzioni: da destra verso sinistra, sovrascrivi i caratteri, includi estensione, maiuscole/minuscole. Il testo può contenere i campi del modello. |
| **Rimuovi testo** | Parte da una posizione o da un delimitatore e toglie un certo numero di caratteri, fino a un delimitatore o fino alla fine. Opzioni: da destra verso sinistra, rimuovi anche i delimitatori, includi estensione, maiuscole/minuscole. |
| **Spazi** | Elimina tutti gli spazi, elimina quelli all'inizio e alla fine, riduce gli spazi doppi, oppure sostituisce gli spazi con un carattere. |

**Avanzate**

- *Se il nuovo nome esiste già*: non rinominare nulla e segnala in rosso, salta quei file, oppure aggiungi un numero (`nome (2)`, `nome (3)`…).
- *Se cambia l'estensione*: consenti oppure salta quei file.

I nomi non validi per Windows (caratteri `< > : " / \ | ? *`, punto o spazio finale, nomi riservati come `CON`) vengono sempre segnalati. Gli scambi di nome (per esempio 1→2, 2→3) sono gestiti correttamente, e funzionano anche i cambi di sole maiuscole (`IMG.JPG` → `img.jpg`). Le operazioni usate restano salvate per la volta successiva.

## Altre operazioni in blocco

- **Converti**: salva in JPEG, PNG, WebP, BMP o TIFF, con qualità e riduzione del lato lungo regolabili, in una sottocartella, in un'altra cartella o accanto agli originali. Le foto vengono raddrizzate secondo l'EXIF, ma i dati EXIF non vengono copiati.
- **Copia / Sposta** (anche cartelle intere): se un file esiste già nella destinazione, puoi aggiungere un numero al nome, sovrascrivere o saltarlo.
- **Elimina**: sposta file o cartelle nel Cestino, quindi sono recuperabili.

## Lingua

*Strumenti → Lingua / Language*: **Automatica** (come Windows), **Italiano** o **English**. Il programma propone di riavviarsi per applicare la modifica.

Le traduzioni sono in `isv/lang_en.py`: le chiavi sono i testi italiani usati nel codice. Per aggiungere una lingua basta creare un dizionario analogo e registrarlo in `LANGUAGES` in `isv/i18n.py`.

## Formati

JPEG, PNG, GIF (anche animate), BMP, WebP, TIFF, ICO e TGA. Le foto vengono ruotate automaticamente secondo l'EXIF.
HEIC e AVIF vengono riconosciuti solo se è installato un plugin Qt per quei formati. I file RAW non sono supportati.

Archivi: ZIP e CBZ (sola lettura).

## Struttura

```
image_slideshow_viewer.pyw   avvio (doppio clic)
build_exe.bat                crea l'.exe con PyInstaller
isv/__init__.py              nome, versione, autore
isv/app.py                   avvio, riga di comando, coordinamento finestre, tema scuro
isv/browser.py               finestra principale (albero + miniature, menu)
isv/thumbs.py                miniature e cache su disco
isv/viewer.py                visualizzatore e slideshow
isv/navigator.py             logica di scorrimento immagini e cartelle
isv/batch.py                 finestre di rinomina / converti / copia / sposta / elimina
isv/rename.py                motore della rinomina (senza Qt, provabile da solo)
isv/shell.py                 menu contestuale di Esplora risorse (registro)
isv/single.py                riunisce in una finestra i file selezionati in Esplora risorse
isv/about.py                 finestra Informazioni
isv/i18n.py, lang_en.py      traduzioni
isv/archive.py               archivi ZIP / CBZ
isv/loader.py                caricamento e precaricamento immagini
isv/worker.py                esecuzione in background
isv/utils.py                 elenco file, ordinamento, navigazione cartelle
```

Le impostazioni vengono salvate automaticamente nel registro di Windows, sotto `HKCU\Software\LainX84\ImageSlideShowViewer`. Al primo avvio vengono importate quelle della versione precedente (FotoVista).

## Autore

**LainX84** — [github.com/LainX84](https://github.com/LainX84)

## Licenza

[MIT](LICENSE)
