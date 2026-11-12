"""Tasti di scelta rapida: un unico elenco per browser e visualizzatore.

Da qui li leggono i menu (che mostrano i tasti accanto alle voci), il visualizzatore,
l'aiuto (F1) e la finestra "Tasti di scelta rapida", dove ognuno si può cambiare.
Le modifiche stanno nelle impostazioni come "keys/<ambito>/<id>" = "Ctrl+R; R".
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
                               QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .i18n import tr

P = QKeySequence.SequenceFormat.PortableText
N = QKeySequence.SequenceFormat.NativeText

# (id, testo, tasti predefiniti) – i testi passano da tr() quando si mostrano
VIEWER = [
    ("next", "Immagine successiva", ["Right", "PgDown"]),
    ("prev", "Immagine precedente", ["Left", "PgUp", "Backspace"]),
    ("next_folder", "Cartella successiva", ["Down", "Ctrl+Right", "Ctrl+PgDown"]),
    ("prev_folder", "Cartella precedente", ["Up", "Ctrl+Left", "Ctrl+PgUp"]),
    ("first", "Prima immagine della cartella", ["Home"]),
    ("last", "Ultima immagine della cartella", ["End"]),
    ("play", "Avvia / ferma lo slideshow", ["Space", "P", "Media Play", "Toggle Media Play/Pause"]),
    ("stop", "Ferma lo slideshow", ["S", "Media Stop", "Media Pause"]),
    ("plus", "Intervallo più lungo (slideshow) / zoom avanti", ["+", "="]),
    ("minus", "Intervallo più corto (slideshow) / zoom indietro", ["-"]),
    ("pair", "Due immagini affiancate sì / no", ["D"]),
    ("manga", "Modalità manga (da destra a sinistra)", ["M"]),
    ("fit_mode", "Adatta: finestra → larghezza → altezza → riempi", ["W"]),
    ("zoom_toggle", "Adatta alla finestra ↔ 100%", ["Z", "*", "0"]),
    ("zoom_in", "Zoom avanti", ["Ctrl++", "Ctrl+="]),
    ("zoom_out", "Zoom indietro", ["Ctrl+-"]),
    ("fullscreen", "Schermo intero", ["F", "F11"]),
    ("info", "Mostra / nascondi informazioni", ["I"]),
    ("rotate_right", "Ruota a destra (90°)", ["R"]),
    ("rotate_left", "Ruota a sinistra (90°)", ["Shift+R"]),
    ("flip_h", "Specchia in orizzontale", ["H"]),
    ("flip_v", "Specchia in verticale", ["Shift+H"]),
    ("save_orientation", "Salva la rotazione nel file", ["Ctrl+S"]),
    ("loupe", "Lente d'ingrandimento", ["L"]),
    ("background", "Colore dello sfondo", ["B"]),
    ("histogram", "Istogramma", ["G"]),
    ("pixel", "Colore del pixel sotto il mouse (contagocce)", ["K"]),
    ("webtoon", "Lettura verticale continua (webtoon)", ["V"]),
    ("edit", "Modifica immagine (ritaglia, regola, ridimensiona)…", ["E"]),
    ("favorite", "Aggiungi / togli dai Preferiti", ["Ctrl+D"]),
    *[(f"rating_{i}", f"Valutazione: {i} stelle" if i else "Valutazione: nessuna", [f"Ctrl+{i}"])
      for i in range(6)],
    *[(f"label_{i}", f"Etichetta {i}", [f"Alt+{i}"]) for i in range(6)],
    *[(f"sort_{i}", f"Smista nella cartella {i}", [str(i)]) for i in range(1, 10)],
    ("delete", "Sposta nel Cestino", ["Del"]),
    ("undo", "Annulla eliminazione / smistamento", ["Ctrl+Z"]),
    ("rename", "Rinomina", ["F2"]),
    ("copy_image", "Copia l'immagine negli appunti", ["Ctrl+C"]),
    ("image_info", "Informazioni immagine (EXIF)", ["Alt+Return"]),
    ("music", "Musica dello slideshow sì / no", ["Ctrl+M"]),
    ("video_audio", "Audio del video sì / no", ["A"]),
    ("options", "Opzioni", ["O"]),
    ("to_browser", "Torna al browser su questa immagine", ["Return", "Enter"]),
    ("close", "Chiudi / esci dallo slideshow", ["Esc"]),
]

BROWSER = [
    ("back", "Indietro", ["Alt+Left"]),
    ("up", "Cartella superiore", ["Alt+Up", "Backspace"]),
    ("pictures", "Cartella Immagini", []),
    ("refresh", "Aggiorna", ["Ctrl+R"]),
    ("open_dir", "Apri cartella…", ["Ctrl+O"]),
    ("new_folder", "Nuova cartella…", ["Ctrl+Shift+N"]),
    ("view", "Visualizza", []),
    ("slideshow", "Slideshow", ["F5", "Ctrl+S"]),
    ("dual", "Slideshow di 2 cartelle affiancate…", ["Shift+F5"]),
    ("webtoon", "Lettura verticale continua (webtoon)", ["Ctrl+L"]),
    ("compare", "Confronta 2 immagini", ["Ctrl+K"]),
    ("preview", "Pannello anteprima", ["F3"]),
    ("info", "Informazioni immagine (EXIF)…", ["Alt+Return"]),
    ("undo", "Annulla eliminazione / spostamento", ["Ctrl+Z"]),
    ("cut", "Taglia", ["Ctrl+X"]),
    ("copy", "Copia", ["Ctrl+C"]),
    ("paste", "Incolla", ["Ctrl+V"]),
    ("select_all", "Seleziona tutto", ["Ctrl+A"]),
    ("rename", "Rinomina", ["F2"]),
    ("batch_rename", "Rinomina in blocco…", ["Ctrl+F2"]),
    ("convert", "Converti formato…", ["Ctrl+Shift+C"]),
    ("to_cbz", "Converti archivio in CBZ", []),
    ("edit", "Modifica immagine…", ["Ctrl+E"]),
    ("rotate_right", "Ruota a destra (90°)", ["Ctrl+Alt+Right"]),
    ("rotate_left", "Ruota a sinistra (90°)", ["Ctrl+Alt+Left"]),
    ("rotate_180", "Ruota di 180°", []),
    ("flip_h", "Specchia in orizzontale", []),
    ("flip_v", "Specchia in verticale", []),
    ("copy_to", "Copia in…", ["Ctrl+Shift+K"]),
    ("move_to", "Sposta in…", ["Ctrl+Shift+M"]),
    ("delete", "Sposta nel Cestino", ["Del"]),
    ("favorite", "Aggiungi / togli dai Preferiti", ["Ctrl+D"]),
    *[(f"rating_{i}", f"Valutazione: {i} stelle" if i else "Valutazione: nessuna", [f"Ctrl+{i}"])
      for i in range(6)],
    *[(f"label_{i}", f"Etichetta {i}", [f"Alt+{i}"]) for i in range(6)],
    ("copy_path", "Copia percorso", []),
    ("wallpaper", "Imposta come sfondo del desktop", []),
    ("print", "Stampa…", ["Ctrl+P"]),
    ("properties", "Proprietà", []),
    ("explorer", "Mostra in Esplora risorse", []),
    ("search", "Cerca…", ["Ctrl+F"]),
    ("duplicates", "Trova duplicati…", []),
    ("calendar", "Calendario (foto per data)…", []),
    ("map", "Mappa delle foto…", []),
    ("options", "Opzioni…", ["Ctrl+,"]),
    ("shortcuts", "Tasti di scelta rapida…", []),
    ("help", "Scorciatoie da tastiera", ["F1"]),
    ("quit", "Esci", ["Ctrl+Q"]),
]

SCOPES = {"viewer": VIEWER, "browser": BROWSER}


def label(scope, aid):
    """Testo tradotto di un comando (anche per le etichette colorate)."""
    for i, text, _d in SCOPES[scope]:
        if i == aid:
            if aid.startswith("label_"):
                from .library import label_name
                n = int(aid.split("_")[1])
                return tr("Etichetta: {name}", name=label_name(n))
            if aid.startswith("rating_"):
                n = int(aid.split("_")[1])
                return tr("Valutazione: nessuna") if n == 0 else tr("Valutazione: {n} stelle", n=n)
            if aid.startswith("sort_"):
                return tr("Smista nella cartella {n}", n=aid.split("_")[1])
            return tr(text)
    return aid


def defaults(scope, aid):
    for i, _t, d in SCOPES[scope]:
        if i == aid:
            return list(d)
    return []


def keys(settings, scope, aid):
    """Tasti attuali (testi "portable") di un comando."""
    v = settings.value(f"keys/{scope}/{aid}", None)
    if v is None:
        return defaults(scope, aid)
    return [k.strip() for k in str(v).split(";") if k.strip()]


def sequences(settings, scope, aid):
    return [QKeySequence(k) for k in keys(settings, scope, aid)]


def native(settings, scope, aid, first_only=False):
    """Tasti come si mostrano nei menu ("Ctrl+D")."""
    ks = [QKeySequence(k).toString(N) for k in keys(settings, scope, aid)]
    ks = [k for k in ks if k]
    return (ks[0] if ks else "") if first_only else ", ".join(ks)


def keymap(settings, scope):
    """{testo portable del tasto: id} per il visualizzatore."""
    out = {}
    for aid, _t, _d in SCOPES[scope]:
        for k in keys(settings, scope, aid):
            s = QKeySequence(k).toString(P)
            if s:
                out.setdefault(s, aid)
    return out


def event_keys(e):
    """Testi portable di un tasto premuto, dal più preciso al più tollerante."""
    mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
    key = e.key()
    if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta, 0,
               Qt.Key.Key_unknown):
        return []
    out = [QKeySequence(mods.value | key).toString(P)]
    if mods & Qt.KeyboardModifier.ShiftModifier and not (Qt.Key.Key_A <= key <= Qt.Key.Key_Z) \
            and not (Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35):
        # "+" e "*" si scrivono con Maiusc su molte tastiere
        out.append(QKeySequence((mods & ~Qt.KeyboardModifier.ShiftModifier).value | key).toString(P))
    return out


# --------------------------------------------------------------- finestre
class _EditKeys(QDialog):
    def __init__(self, title, current, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Premi la combinazione di tasti. Fino a 3 alternative.")))
        form = QFormLayout()
        self.edits = []
        for i in range(3):
            ed = QKeySequenceEdit(QKeySequence(current[i]) if i < len(current) else QKeySequence())
            try:
                ed.setMaximumSequenceLength(1)
                ed.setClearButtonEnabled(True)
            except AttributeError:
                pass
            form.addRow(tr("Tasto {n}:", n=i + 1), ed)
            self.edits.append(ed)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def value(self):
        out = []
        for ed in self.edits:
            s = ed.keySequence().toString(P)
            if s and s not in out:
                out.append(s)
        return out


class ShortcutsDialog(QDialog):
    """Elenco di tutti i comandi con i loro tasti; doppio clic per cambiarli."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Tasti di scelta rapida"))
        self.resize(760, 640)
        self.work = {sc: {aid: keys(settings, sc, aid) for aid, _t, _d in lst}
                     for sc, lst in SCOPES.items()}
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(tr("Cerca un comando o un tasto…"))
        self.filter.textChanged.connect(self._apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Comando"), tr("Tasti")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._edit)
        b_edit = QPushButton(tr("Cambia…"))
        b_edit.clicked.connect(lambda: self._edit(self.tree.currentItem()))
        b_clear = QPushButton(tr("Nessun tasto"))
        b_clear.clicked.connect(self._clear)
        b_def = QPushButton(tr("Predefinito"))
        b_def.clicked.connect(self._default_one)
        b_all = QToolButton()
        b_all.setText(tr("Ripristina tutti i predefiniti"))
        b_all.clicked.connect(self._default_all)
        row = QHBoxLayout()
        for b in (b_edit, b_clear, b_def):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(b_all)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.filter)
        lay.addWidget(self.tree)
        lay.addLayout(row)
        lay.addWidget(bb)
        self._fill()

    def _fill(self):
        self.tree.clear()
        for sc, title in (("browser", tr("Browser")), ("viewer", tr("Visualizzatore e slideshow"))):
            top = QTreeWidgetItem(self.tree, [title])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            for aid, _t, _d in SCOPES[sc]:
                it = QTreeWidgetItem(top, [label(sc, aid), self._fmt(self.work[sc][aid])])
                it.setData(0, Qt.ItemDataRole.UserRole, (sc, aid))
            top.setExpanded(True)
        self._apply_filter(self.filter.text())

    @staticmethod
    def _fmt(ks):
        return ", ".join(QKeySequence(k).toString(N) for k in ks)

    def _apply_filter(self, text):
        t = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                c = top.child(j)
                c.setHidden(bool(t) and t not in c.text(0).lower() and t not in c.text(1).lower())

    def _cur(self, item=None):
        item = item or self.tree.currentItem()
        d = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return (item, d) if d else (None, None)

    def _edit(self, item):
        item, d = self._cur(item)
        if not d:
            return
        sc, aid = d
        dlg = _EditKeys(label(sc, aid), self.work[sc][aid], self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new = dlg.value()
        for k in new:
            for other, ks in self.work[sc].items():
                if other != aid and k in ks:
                    r = QMessageBox.question(self, self.windowTitle(),
                                             tr("Il tasto {k} è già usato da «{cmd}».\n\nToglierlo da lì?",
                                                k=QKeySequence(k).toString(N), cmd=label(sc, other)))
                    if r != QMessageBox.StandardButton.Yes:
                        return
                    ks.remove(k)
        self.work[sc][aid] = new
        self._refresh()

    def _clear(self):
        _item, d = self._cur()
        if d:
            self.work[d[0]][d[1]] = []
            self._refresh()

    def _default_one(self):
        _item, d = self._cur()
        if d:
            self.work[d[0]][d[1]] = defaults(*d)
            self._refresh()

    def _default_all(self):
        self.work = {sc: {aid: list(dd) for aid, _t, dd in lst} for sc, lst in SCOPES.items()}
        self._refresh()

    def _refresh(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                c = top.child(j)
                sc, aid = c.data(0, Qt.ItemDataRole.UserRole)
                c.setText(1, self._fmt(self.work[sc][aid]))

    def run(self):
        if self.exec() != QDialog.DialogCode.Accepted:
            return False
        for sc, d in self.work.items():
            for aid, ks in d.items():
                if ks == defaults(sc, aid):
                    self.settings.remove(f"keys/{sc}/{aid}")
                else:
                    self.settings.setValue(f"keys/{sc}/{aid}", "; ".join(ks))
        return True


def help_html(settings):
    """Tabella dei tasti per F1, sempre allineata a quelli impostati."""
    def table(sc):
        rows = []
        for aid, _t, _d in SCOPES[sc]:
            k = native(settings, sc, aid)
            if k:
                rows.append(f"<tr><td><b>{k}</b></td><td>{label(sc, aid)}</td></tr>")
        return "<table cellspacing=3>" + "".join(rows) + "</table>"
    extra = (f"<tr><td><b>{tr('Ctrl+rotellina')}</b></td><td>{tr('zoom (trascina per spostarti)')}</td></tr>"
             f"<tr><td><b>{tr('Maiusc+rotellina')}</b></td><td>{tr('ingrandimento della lente')}</td></tr>"
             f"<tr><td><b>{tr('tasto destro')}</b></td><td>{tr('menu con tutti i comandi')}</td></tr>")
    return (f"<h3>{tr('Browser')}</h3>{table('browser')}"
            f"<h3>{tr('Visualizzatore e slideshow')}</h3>{table('viewer')}"
            f"<table cellspacing=3>{extra}</table>")
