"""Operazioni in blocco: rinomina, converti, copia/sposta, elimina."""
import json
import os
import shutil

from PySide6.QtCore import QFile, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QImageReader, QImageWriter, QPainter
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox,
                               QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QProgressDialog, QPushButton, QRadioButton, QSpinBox,
                               QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from . import rename as R
from .i18n import tr
from .utils import is_inside, natural_key, samepath, unique_path  # noqa: F401  (natural_key usato da app)


def move_to_trash(path):
    r = QFile.moveToTrash(path)
    return r[0] if isinstance(r, tuple) else bool(r)


def _progress(parent, title, n):
    d = QProgressDialog(title, tr("Annulla"), 0, n, parent)
    d.setWindowTitle(title)
    d.setWindowModality(Qt.WindowModality.WindowModal)
    d.setMinimumDuration(300)
    d.setValue(0)
    return d


def _report(parent, title, done, errors, verb):
    if errors:
        txt = "\n".join(errors[:15])
        if len(errors) > 15:
            txt += "\n" + tr("… e altri {n}", n=len(errors) - 15)
        QMessageBox.warning(parent, title, tr("{verb}: {done} file.\nErrori ({n}):\n\n{txt}",
                                               verb=verb, done=done, n=len(errors), txt=txt))


# RINOMINA: vedi RenameDialog più sotto e il motore in rename.py


# ================================================================= CONVERTI
FORMATS = [("JPEG", b"jpeg", ".jpg"), ("PNG", b"png", ".png"), ("WebP", b"webp", ".webp"),
           ("BMP", b"bmp", ".bmp"), ("TIFF", b"tiff", ".tif")]


def available_formats():
    sup = {bytes(f).lower() for f in QImageWriter.supportedImageFormats()}
    return [f for f in FORMATS if f[1] in sup]


def convert_one(src, out_dir, fmt, ext, quality=90, max_side=0, exists="rename"):
    """Converte un'immagine. Ritorna il percorso scritto, None se saltata; solleva OSError."""
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(out_dir, stem + ext)
    if os.path.exists(dst) and not samepath(dst, src):
        if exists == "skip":
            return None
        if exists == "rename":
            dst = unique_path(dst)
    r = QImageReader(src)
    r.setAutoTransform(True)
    img = r.read()
    if img.isNull():
        raise OSError(r.errorString() or tr("lettura non riuscita"))
    if max_side and max(img.width(), img.height()) > max_side:
        img = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    if fmt in (b"jpeg", b"bmp") and img.hasAlphaChannel():
        flat = QImage(img.size(), QImage.Format.Format_RGB32)
        flat.fill(QColor(255, 255, 255))
        p = QPainter(flat)
        p.drawImage(0, 0, img)
        p.end()
        img = flat
    os.makedirs(out_dir, exist_ok=True)
    w = QImageWriter(dst, fmt)
    if fmt in (b"jpeg", b"webp"):
        w.setQuality(quality)
    if not w.write(img):
        raise OSError(w.errorString())
    return dst


class ConvertDialog(QDialog):
    def __init__(self, paths, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Converti formato – {n} file", n=len(paths)))
        self.paths, self.settings = paths, settings
        self.formats = available_formats()
        self.fmt = QComboBox()
        self.fmt.addItems([f[0] for f in self.formats])
        self.fmt.setCurrentIndex(max(0, min(settings.value("batch/conv_fmt", 0, type=int),
                                            len(self.formats) - 1)))
        self.quality = QSpinBox(minimum=1, maximum=100, value=settings.value("batch/conv_q", 90, type=int))
        self.resize_chk = QCheckBox(tr("Riduci se il lato lungo supera"))
        self.max_side = QSpinBox(minimum=16, maximum=20000, value=settings.value("batch/conv_side", 1920, type=int))
        self.max_side.setSuffix(" px")
        rs = QHBoxLayout()
        rs.addWidget(self.resize_chk)
        rs.addWidget(self.max_side)
        rs.addStretch()
        self.r_sub = QRadioButton(tr("Sottocartella:"))
        self.r_dir = QRadioButton(tr("Cartella:"))
        self.r_same = QRadioButton(tr("Stessa cartella degli originali"))
        grp = QButtonGroup(self)
        for b in (self.r_sub, self.r_dir, self.r_same):
            grp.addButton(b)
        self.r_sub.setChecked(True)
        self.sub_name = QLineEdit(settings.value("batch/conv_sub", tr("convertite")))
        self.dir_edit = QLineEdit(settings.value("batch/conv_dir", ""))
        browse = QPushButton(tr("Sfoglia…"))
        browse.clicked.connect(self._browse)
        l1 = QHBoxLayout(); l1.addWidget(self.r_sub); l1.addWidget(self.sub_name)
        l2 = QHBoxLayout(); l2.addWidget(self.r_dir); l2.addWidget(self.dir_edit); l2.addWidget(browse)
        self.exists = QComboBox()
        self.exists.addItems([tr("Aggiungi un numero al nome"), tr("Salta"), tr("Sovrascrivi")])
        self.del_orig = QCheckBox(tr("Sposta gli originali nel Cestino dopo la conversione"))
        self.del_orig.setToolTip(tr("Solo per i file convertiti senza errori; si possono "
                                    "recuperare dal Cestino."))
        note = QLabel(tr("Nota: la conversione raddrizza le foto ruotate ma non copia i dati EXIF."))
        note.setStyleSheet("color: gray")
        form = QFormLayout()
        form.addRow(tr("Formato:"), self.fmt)
        form.addRow(tr("Qualità (JPEG/WebP):"), self.quality)
        form.addRow(tr("Dimensioni:"), rs)
        out = QVBoxLayout(); out.addLayout(l1); out.addLayout(l2); out.addWidget(self.r_same)
        ow = QWidget(); ow.setLayout(out)
        form.addRow(tr("Salva in:"), ow)
        form.addRow(tr("Se il file esiste:"), self.exists)
        form.addRow(tr("Originali:"), self.del_orig)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Converti"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(note)
        lay.addWidget(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Cartella di destinazione"), self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)
            self.r_dir.setChecked(True)

    def run(self):
        if not self.formats:
            QMessageBox.warning(self.parent(), tr("Converti"), tr("Nessun formato di scrittura disponibile."))
            return False
        if self.exec() != QDialog.DialogCode.Accepted:
            return False
        s = self.settings
        s.setValue("batch/conv_fmt", self.fmt.currentIndex())
        s.setValue("batch/conv_q", self.quality.value())
        s.setValue("batch/conv_side", self.max_side.value())
        s.setValue("batch/conv_sub", self.sub_name.text())
        s.setValue("batch/conv_dir", self.dir_edit.text())
        _, fmt, ext = self.formats[self.fmt.currentIndex()]
        side = self.max_side.value() if self.resize_chk.isChecked() else 0
        policy = ["rename", "skip", "overwrite"][self.exists.currentIndex()]
        if self.r_dir.isChecked() and not self.dir_edit.text().strip():
            QMessageBox.warning(self.parent(), tr("Converti"), tr("Scegli una cartella di destinazione."))
            return False
        prog = _progress(self.parent(), tr("Conversione in corso…"), len(self.paths))
        done, errors, converted = 0, [], []
        for i, p in enumerate(self.paths):
            if prog.wasCanceled():
                break
            prog.setLabelText(os.path.basename(p))
            prog.setValue(i)
            QApplication.processEvents()
            src_dir = os.path.dirname(p)
            if self.r_sub.isChecked():
                out_dir = os.path.join(src_dir, self.sub_name.text().strip() or tr("convertite"))
            elif self.r_dir.isChecked():
                out_dir = self.dir_edit.text().strip()
            else:
                out_dir = src_dir
            try:
                dst = convert_one(p, out_dir, fmt, ext, self.quality.value(), side, policy)
                if dst:
                    done += 1
                    if self.del_orig.isChecked() and not samepath(dst, p):
                        converted.append(p)
            except OSError as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        prog.setValue(len(self.paths))
        trashed = 0
        for p in converted:
            if move_to_trash(p):
                trashed += 1
            else:
                errors.append(f"{os.path.basename(p)}: " + tr("impossibile spostare l'originale nel Cestino"))
        _report(self.parent(), tr("Converti"), done, errors, tr("Convertiti"))
        if trashed and not errors:
            QMessageBox.information(self.parent(), tr("Converti"),
                                    tr("Convertiti: {done} file.\nOriginali spostati nel Cestino: {n}.",
                                       done=done, n=trashed))
        return True


# =========================================================== COPIA / SPOSTA
def copy_move_files(paths, dest, move=False, exists="rename", progress=None):
    done, errors = 0, []
    for i, p in enumerate(paths):
        if progress and progress(i, p):
            break
        if os.path.isdir(p) and is_inside(dest, p):
            errors.append(f"{os.path.basename(p)}: " + tr("la destinazione è dentro la cartella stessa"))
            continue
        dst = os.path.join(dest, os.path.basename(p))
        if samepath(os.path.dirname(p), dest):
            if move:
                continue
            dst = unique_path(dst)      # copia nella stessa cartella: "nome (2).jpg"
        elif os.path.exists(dst):
            if exists == "skip":
                continue
            if exists == "rename":
                dst = unique_path(dst)
        try:
            if move:
                shutil.move(p, dst)
            elif os.path.isdir(p):
                shutil.copytree(p, dst, dirs_exist_ok=(exists == "overwrite"))
            else:
                shutil.copy2(p, dst)
            done += 1
        except (OSError, shutil.Error) as e:
            errors.append(f"{os.path.basename(p)}: {e}")
    return done, errors


def copy_move_dialog(parent, paths, settings, move=False):
    title = tr("Sposta in") if move else tr("Copia in")
    dest = QFileDialog.getExistingDirectory(parent, f"{title}…", settings.value("batch/last_dest", ""))
    if not dest:
        return False
    settings.setValue("batch/last_dest", dest)
    return transfer(parent, paths, dest, move)


def transfer(parent, paths, dest, move=False):
    """Copia o sposta in dest chiedendo cosa fare con i file già presenti (anche per Incolla)."""
    title = tr("Sposta in") if move else tr("Copia in")
    conflicts = [p for p in paths if os.path.exists(os.path.join(dest, os.path.basename(p)))
                 and not samepath(os.path.dirname(p), dest)]
    policy = "rename"
    if conflicts:
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(tr("{n} file esistono già nella destinazione.", n=len(conflicts)))
        b_ren = box.addButton(tr("Aggiungi numero"), QMessageBox.ButtonRole.AcceptRole)
        b_over = box.addButton(tr("Sovrascrivi"), QMessageBox.ButtonRole.DestructiveRole)
        b_skip = box.addButton(tr("Salta"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Annulla"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        c = box.clickedButton()
        if c == b_ren:
            policy = "rename"
        elif c == b_over:
            policy = "overwrite"
        elif c == b_skip:
            policy = "skip"
        else:
            return False
    prog = _progress(parent, tr("Spostamento…") if move else tr("Copia…"), len(paths))

    def step(i, p):
        prog.setValue(i)
        prog.setLabelText(os.path.basename(p))
        QApplication.processEvents()
        return prog.wasCanceled()

    done, errors = copy_move_files(paths, dest, move, policy, step)
    prog.setValue(len(paths))
    _report(parent, title, done, errors, tr("Spostati") if move else tr("Copiati"))
    return True


# ================================================================== ELIMINA
def delete_dialog(parent, paths):
    if not paths:
        return False
    what = os.path.basename(paths[0]) if len(paths) == 1 else tr("{n} elementi", n=len(paths))
    r = QMessageBox.question(parent, tr("Elimina"), tr("Spostare nel Cestino {what}?", what=what))
    if r != QMessageBox.StandardButton.Yes:
        return False
    errors = [os.path.basename(p) for p in paths if not move_to_trash(p)]
    if errors:
        _report(parent, tr("Elimina"), len(paths) - len(errors), errors, tr("Eliminati"))
    return True


# ================================================================= RINOMINA
def op_title(kind):
    return {"template": tr("Modello"), "replace": tr("Cerca e sostituisci"),
            "case": tr("Maiuscole / minuscole"), "insert": tr("Inserisci testo"),
            "remove": tr("Rimuovi testo"), "spaces": tr("Spazi")}[kind]


def _combo(items, current, on_change):
    """items: [(chiave, etichetta)]"""
    cb = QComboBox()
    for k, label in items:
        cb.addItem(label, k)
    i = cb.findData(current)
    cb.setCurrentIndex(max(0, i))
    cb.currentIndexChanged.connect(lambda _i: on_change(cb.currentData()))
    return cb


class OpEditor(QWidget):
    """Campi di una singola operazione; ogni modifica aggiorna il dizionario e l'anteprima."""

    def __init__(self, op, changed, parent=None):
        super().__init__(parent)
        self.op, self._changed = op, changed
        self.form = QFormLayout(self)
        self.form.setContentsMargins(4, 0, 4, 0)
        self._enablers = []
        getattr(self, "_build_" + op["type"])()
        self._refresh()

    # ---------------------------------------------------------- aiuti
    def _set(self, key, value):
        self.op[key] = value
        self._refresh()
        self._changed()

    def _refresh(self):
        for fn in self._enablers:
            fn()

    def _line(self, key, placeholder=""):
        e = QLineEdit(self.op[key])
        e.setPlaceholderText(placeholder)
        e.textChanged.connect(lambda t: self._set(key, t))
        return e

    def _check(self, key, text, tip=""):
        c = QCheckBox(text)
        c.setChecked(bool(self.op[key]))
        if tip:
            c.setToolTip(tip)
        c.toggled.connect(lambda v: self._set(key, v))
        return c

    def _spin(self, key, lo=0, hi=9_999_999):
        sp = QSpinBox(minimum=lo, maximum=hi)
        sp.setValue(int(self.op[key]))
        sp.valueChanged.connect(lambda v: self._set(key, v))
        return sp

    def _fields_button(self, target, with_counter=False):
        b = QToolButton()
        b.setText(tr("Inserisci campo") + " ▾")
        b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(b)
        items = []
        if with_counter:
            items += [("*", tr("Nome originale")), ("###", tr("Contatore (### = 001, 002…)"))]
        items += [("{" + tr("nome") + "}", tr("Nome attuale")),
                  ("{" + tr("cartella") + "}", tr("Nome della cartella")),
                  ("{" + tr("data") + "}", tr("Data del file (AAAA-MM-GG)")),
                  ("{" + tr("ora") + "}", tr("Ora del file (HHMMSS)")),
                  ("{" + tr("anno") + "}", tr("Anno")), ("{" + tr("mese") + "}", tr("Mese")),
                  ("{" + tr("giorno") + "}", tr("Giorno")),
                  ("{" + tr("larghezza") + "}", tr("Larghezza immagine (px)")),
                  ("{" + tr("altezza") + "}", tr("Altezza immagine (px)"))]
        for code, label in items:
            m.addAction(f"{code}    {label}", lambda c=code: target.insert(c))
        b.setMenu(m)
        return b

    @staticmethod
    def _row(*widgets):
        h = QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            if w == "stretch":
                h.addStretch()
            else:
                h.addWidget(w)
        return h

    # ---------------------------------------------------------- tipi
    def _build_template(self):
        e = self._line("template", "Foto_###")
        self.form.addRow(tr("Modello:"), self._row(e, self._fields_button(e, True)))
        hint = QLabel(tr("<b>*</b> = nome originale &nbsp; <b>#</b> = contatore (### → 001, 002…) "
                         "&nbsp; <b>{data}</b>, <b>{cartella}</b>… = campi del file"))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        self.form.addRow("", hint)
        self.form.addRow(tr("Sostituisci i # con:"), _combo(
            [("numbers", tr("numeri (001, 002…)")), ("letters", tr("lettere (aa, ab…)"))],
            self.op["seq"], lambda v: self._set("seq", v)))
        sp = self._spin("start", 0)
        mode = _combo([("fixed", tr("Valore fisso")),
                       ("auto", tr("Rileva automaticamente (continua la numerazione esistente)"))],
                      self.op["start_mode"], lambda v: self._set("start_mode", v))
        self.form.addRow(tr("Parti da:"), self._row(mode, sp, "stretch"))

    def _build_replace(self):
        self.form.addRow(tr("Cerca:"), self._line("search"))
        self.form.addRow(tr("Sostituisci con:"), self._line("replace", tr("(vuoto = elimina)")))
        self.form.addRow("", self._row(
            self._check("case", tr("Maiuscole/minuscole")),
            self._check("ext", tr("Includi estensione")),
            self._check("regex", tr("Espressione regolare"),
                        tr("Usa la sintassi delle espressioni regolari di Python; "
                           "nel testo sostitutivo \\1, \\2… richiamano i gruppi.")),
            "stretch"))

    def _build_case(self):
        self.form.addRow(tr("Nome:"), _combo(
            [("keep", tr("Nessuna modifica")), ("lower", tr("minuscolo")),
             ("upper", tr("MAIUSCOLO")), ("title", tr("Iniziali Maiuscole")),
             ("sentence", tr("Solo la prima maiuscola"))],
            self.op["name"], lambda v: self._set("name", v)))
        self.form.addRow(tr("Estensione:"), _combo(
            [("keep", tr("Nessuna modifica")), ("lower", tr("minuscola (.jpg)")),
             ("upper", tr("MAIUSCOLA (.JPG)"))],
            self.op["ext"], lambda v: self._set("ext", v)))

    def _build_insert(self):
        e = self._line("text")
        self.form.addRow(tr("Inserisci:"), self._row(e, self._fields_button(e)))
        pos = self._spin("pos", 0, 999)
        anchor = self._line("anchor")
        where = _combo([("prefix", tr("All'inizio")), ("suffix", tr("Alla fine")),
                        ("position", tr("In posizione (dopo N caratteri)")),
                        ("after", tr("Dopo il testo")), ("before", tr("Prima del testo"))],
                       self.op["where"], lambda v: self._set("where", v))
        self.form.addRow(tr("Dove:"), self._row(where, pos, anchor))
        rtl = self._check("rtl", tr("Da destra verso sinistra"),
                          tr("Conta la posizione dalla fine del nome; con «Dopo/Prima del testo» "
                             "usa l'ultima occorrenza."))
        over = self._check("overwrite", tr("Sovrascrivi i caratteri"),
                           tr("Il testo sostituisce altrettanti caratteri del nome invece di aggiungersi."))
        case = self._check("case", tr("Maiuscole/minuscole"))
        self.form.addRow("", self._row(rtl, over, self._check("ext", tr("Includi estensione")),
                                       case, "stretch"))

        def en():
            w = self.op["where"]
            pos.setVisible(w == "position")
            anchor.setVisible(w in ("after", "before"))
            case.setEnabled(w in ("after", "before"))
            rtl.setEnabled(w in ("position", "after", "before"))
        self._enablers.append(en)

    def _build_remove(self):
        sp = self._spin("start_pos", 0, 999)
        sd = self._line("start_delim")
        sm = _combo([("position", tr("Posizione (dopo N caratteri)")), ("delimiter", tr("Delimitatore"))],
                    self.op["start_mode"], lambda v: self._set("start_mode", v))
        self.form.addRow(tr("Inizia da:"), self._row(sm, sp, sd))
        cnt = self._spin("count", 0, 999)
        ud = self._line("until_delim")
        um = _combo([("count", tr("Numero di caratteri")), ("delimiter", tr("Delimitatore")),
                     ("end", tr("La fine del nome"))],
                    self.op["until_mode"], lambda v: self._set("until_mode", v))
        self.form.addRow(tr("Rimuovi fino a:"), self._row(um, cnt, ud))
        rd = self._check("remove_delims", tr("Rimuovi anche i delimitatori"))
        case = self._check("case", tr("Maiuscole/minuscole"))
        self.form.addRow("", self._row(
            self._check("rtl", tr("Da destra verso sinistra")), rd,
            self._check("ext", tr("Includi estensione")), case, "stretch"))

        def en():
            sp.setVisible(self.op["start_mode"] == "position")
            sd.setVisible(self.op["start_mode"] == "delimiter")
            cnt.setVisible(self.op["until_mode"] == "count")
            ud.setVisible(self.op["until_mode"] == "delimiter")
            uses = self.op["start_mode"] == "delimiter" or self.op["until_mode"] == "delimiter"
            rd.setEnabled(uses)
            case.setEnabled(uses)
        self._enablers.append(en)

    def _build_spaces(self):
        w = self._line("with")
        w.setMaximumWidth(80)
        mode = _combo([("all", tr("Elimina tutti gli spazi")),
                       ("trim", tr("Elimina gli spazi all'inizio e alla fine")),
                       ("collapse", tr("Riduci gli spazi doppi a uno")),
                       ("replace", tr("Sostituisci gli spazi con:"))],
                      self.op["mode"], lambda v: self._set("mode", v))
        self.form.addRow(tr("Spazi:"), self._row(mode, w, "stretch"))
        self._enablers.append(lambda: w.setVisible(self.op["mode"] == "replace"))


def op_summary(op):
    k = op["type"]
    if k == "template":
        return op["template"] or "—"
    if k == "replace":
        return f"{op['search']} → {op['replace']}" if op["search"] else "—"
    if k == "insert":
        return op["text"] or "—"
    if k == "case":
        return "" if op["name"] == "keep" and op["ext"] == "keep" else "Aa"
    if k == "remove":
        return ""
    return ""


def status_text(st, detail):
    if st == R.INVALID:
        return {"empty": tr("nome vuoto"), "chars": tr("caratteri non ammessi  < > : \" / \\ | ? *"),
                "end": tr("non può finire con spazio o punto"),
                "reserved": tr("nome riservato di Windows"),
                "long": tr("nome troppo lungo")}.get(detail, tr("nome non valido"))
    return {R.CONFLICT: tr("nome già usato"), R.SKIP_CONFLICT: tr("saltato: nome già usato"),
            R.SKIP_EXT: tr("saltato: cambierebbe l'estensione"), R.NUMBERED: tr("aggiunto un numero"),
            R.SAME: tr("invariato")}.get(st, "")


class RenameDialog(QDialog):
    """Rinomina in blocco a operazioni, come in ACDSee: modello, cerca e sostituisci,
    maiuscole/minuscole, inserisci, rimuovi, spazi. Le operazioni si applicano in ordine."""

    KEY = "batch/rename_ops"

    def __init__(self, paths, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Rinomina in blocco – {n} file", n=len(paths)))
        self.resize(900, 680)
        self.paths, self.settings = paths, settings
        self.ops = self._load_ops()
        self._pairs, self._blocked = [], True

        # --- elenco operazioni
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        self.list.itemChanged.connect(self._item_checked)
        self.stack = QStackedWidget()
        b_add = QToolButton()
        b_add.setText("+")
        b_add.setToolTip(tr("Aggiungi operazione"))
        b_add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        add_menu = QMenu(b_add)
        for kind in R.OP_TYPES:
            add_menu.addAction(op_title(kind), lambda k=kind: self._add(k))
        b_add.setMenu(add_menu)
        b_del = QToolButton(text="−", toolTip=tr("Rimuovi operazione"))
        b_del.clicked.connect(self._remove)
        b_up = QToolButton(text="↑", toolTip=tr("Sposta su"))
        b_up.clicked.connect(lambda: self._move(-1))
        b_dn = QToolButton(text="↓", toolTip=tr("Sposta giù"))
        b_dn.clicked.connect(lambda: self._move(1))
        b_reset = QToolButton(text=tr("Predefiniti"))
        b_reset.clicked.connect(self._reset)
        tools = QHBoxLayout()
        for b in (b_add, b_del, b_up, b_dn):
            tools.addWidget(b)
        tools.addStretch()
        tools.addWidget(b_reset)
        left = QVBoxLayout()
        lab = QLabel(tr("Operazioni (in ordine):"))
        left.addWidget(lab)
        left.addWidget(self.list, 1)
        left.addLayout(tools)
        lw = QWidget()
        lw.setLayout(left)
        lw.setMinimumWidth(220)
        self.editor_box = QGroupBox()
        eb = QVBoxLayout(self.editor_box)
        eb.addWidget(self.stack)
        eb.addStretch()
        top = QSplitter()
        top.addWidget(lw)
        top.addWidget(self.editor_box)
        top.setStretchFactor(1, 1)
        top.setSizes([240, 640])

        # --- opzioni avanzate
        self.cb_conf = _combo([("block", tr("Non rinominare nulla e segnala in rosso")),
                               ("skip", tr("Salta quei file")),
                               ("number", tr("Aggiungi un numero: nome (2), nome (3)…"))],
                              settings.value("batch/rename_conflicts", "block"), lambda v: self._schedule())
        self.cb_ext = _combo([("allow", tr("Consenti")), ("skip", tr("Salta quei file"))],
                             settings.value("batch/rename_ext", "allow"), lambda v: self._schedule())
        adv = QGroupBox(tr("Avanzate"))
        g = QGridLayout(adv)
        g.addWidget(QLabel(tr("Se il nuovo nome esiste già:")), 0, 0)
        g.addWidget(self.cb_conf, 0, 1)
        g.addWidget(QLabel(tr("Se cambia l'estensione:")), 1, 0)
        g.addWidget(self.cb_ext, 1, 1)
        g.setColumnStretch(2, 1)

        # --- anteprima
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Nome attuale"), tr("Nuovo nome"), tr("Note")])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.status = QLabel()
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                        QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Rinomina"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        vs = QSplitter(Qt.Orientation.Vertical)
        vs.addWidget(top)
        pv = QWidget()
        pl = QVBoxLayout(pv)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(adv)
        pl.addWidget(QLabel(tr("Anteprima:")))
        pl.addWidget(self.table, 1)
        vs.addWidget(pv)
        vs.setSizes([300, 380])
        lay = QVBoxLayout(self)
        lay.addWidget(vs, 1)
        lay.addWidget(self.status)
        lay.addWidget(self.buttons)

        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self._update)
        self._fill_list(0)
        self._update()

    # ------------------------------------------------------- operazioni
    def _default_ops(self):
        t = R.new_op("template")
        old = self.settings.value("batch/rename_pattern", "")   # versione precedente
        t["template"] = (old.replace("{nome}", "*") if old else "Foto_###")
        ops = [t]
        ops += [R.new_op(k, on=False) for k in R.OP_TYPES[1:]]
        return ops

    def _load_ops(self):
        raw = self.settings.value(self.KEY, "")
        try:
            ops = [o for o in (R.normalize(x) for x in json.loads(raw)) if o] if raw else []
        except (ValueError, TypeError, AttributeError):
            ops = []
        return ops or self._default_ops()

    def _fill_list(self, select=0):
        self.list.blockSignals(True)
        self.list.clear()
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        for op in self.ops:
            it = QListWidgetItem()
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if op["on"] else Qt.CheckState.Unchecked)
            self.list.addItem(it)
            self.stack.addWidget(OpEditor(op, self._op_changed))
            self._label(self.list.count() - 1)
        self.list.blockSignals(False)
        if self.ops:
            self.list.setCurrentRow(max(0, min(select, len(self.ops) - 1)))
            self._select(self.list.currentRow())
        else:
            self.editor_box.setTitle("")

    def _label(self, row):
        op = self.ops[row]
        s = op_summary(op)
        it = self.list.item(row)
        self.list.blockSignals(True)
        it.setText(op_title(op["type"]) + (f":  {s}" if s and s != "—" else ""))
        self.list.blockSignals(False)

    def _select(self, row):
        if 0 <= row < len(self.ops):
            self.stack.setCurrentIndex(row)
            self.editor_box.setTitle(op_title(self.ops[row]["type"]))

    def _item_checked(self, it):
        row = self.list.row(it)
        if 0 <= row < len(self.ops):
            self.ops[row]["on"] = it.checkState() == Qt.CheckState.Checked
            self._schedule()

    def _op_changed(self):
        row = self.stack.currentIndex()
        if 0 <= row < len(self.ops):
            # modificare un'operazione la attiva, come ci si aspetta
            if not self.ops[row]["on"]:
                self.ops[row]["on"] = True
                self.list.blockSignals(True)
                self.list.item(row).setCheckState(Qt.CheckState.Checked)
                self.list.blockSignals(False)
            self._label(row)
        self._schedule()

    def _add(self, kind):
        self.ops.append(R.new_op(kind))
        self._fill_list(len(self.ops) - 1)
        self._schedule()

    def _remove(self):
        row = self.list.currentRow()
        if 0 <= row < len(self.ops):
            del self.ops[row]
            self._fill_list(row)
            self._schedule()

    def _move(self, d):
        row = self.list.currentRow()
        j = row + d
        if 0 <= row < len(self.ops) and 0 <= j < len(self.ops):
            self.ops[row], self.ops[j] = self.ops[j], self.ops[row]
            self._fill_list(j)
            self._schedule()

    def _reset(self):
        self.ops = [R.new_op("template", on=True)] + [R.new_op(k, on=False) for k in R.OP_TYPES[1:]]
        self._fill_list(0)
        self._schedule()

    # ------------------------------------------------------- anteprima
    def _schedule(self):
        self._timer.start()

    def _compute(self):
        return R.plan(self.paths, self.ops, self.cb_conf.currentData(), self.cb_ext.currentData())

    def _update(self):
        rows, blocked = self._compute()
        self._pairs, self._blocked = rows, blocked
        shown = rows[:3000]
        self.table.setRowCount(len(shown))
        red, orange, gray, blue = (QBrush(QColor(225, 90, 90)), QBrush(QColor(230, 160, 60)),
                                   QBrush(QColor(140, 140, 140)), QBrush(QColor(110, 170, 240)))
        color = {R.INVALID: red, R.CONFLICT: red, R.SKIP_CONFLICT: orange, R.SKIP_EXT: orange,
                 R.SAME: gray, R.NUMBERED: blue}
        for i, (o, n, st, det) in enumerate(shown):
            a, b = QTableWidgetItem(os.path.basename(o)), QTableWidgetItem(os.path.basename(n))
            c = QTableWidgetItem(status_text(st, det))
            br = color.get(st)
            if br is not None:
                b.setForeground(br)
                c.setForeground(br)
            a.setToolTip(o)
            self.table.setItem(i, 0, a)
            self.table.setItem(i, 1, b)
            self.table.setItem(i, 2, c)
        todo = sum(1 for r in rows if r[2] in (R.OK, R.NUMBERED))
        bad = sum(1 for r in rows if r[2] in (R.INVALID, R.CONFLICT))
        skipped = sum(1 for r in rows if r[2] in (R.SKIP_CONFLICT, R.SKIP_EXT) or
                      (r[2] == R.INVALID and not blocked))
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not blocked and todo > 0)
        if blocked:
            self.status.setText("<span style='color:#e06060'>" +
                                tr("{n} nomi non validi o già esistenti (in rosso): correggi le "
                                   "operazioni oppure scegli cosa fare in «Avanzate».", n=bad) + "</span>")
        else:
            txt = tr("{n} file da rinominare", n=todo)
            if skipped:
                txt += "  ·  " + tr("{n} saltati", n=skipped)
            if len(rows) > len(shown):
                txt += "  ·  " + tr("anteprima dei primi {n}", n=len(shown))
            self.status.setText(txt)

    # ------------------------------------------------------- esecuzione
    def _save(self):
        s = self.settings
        s.setValue(self.KEY, json.dumps(self.ops))
        s.setValue("batch/rename_conflicts", self.cb_conf.currentData())
        s.setValue("batch/rename_ext", self.cb_ext.currentData())

    def run(self):
        r = self.exec()
        self._save()   # anche annullando: le impostazioni restano per la prossima volta
        if r != QDialog.DialogCode.Accepted:
            return False
        rows, blocked = self._compute()
        if blocked:
            return False
        pairs = [(o, n) for o, n, st, _ in rows if st in (R.OK, R.NUMBERED)]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            done, errors = R.apply_renames(pairs)
        finally:
            QApplication.restoreOverrideCursor()
        _report(self.parent(), tr("Rinomina"), done, errors, tr("Rinominati"))
        return True
