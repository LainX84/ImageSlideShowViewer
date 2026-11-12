"""Ricerca di immagini e video per nome, data, dimensioni, fotocamera, valutazione,
etichetta. I risultati compaiono nel browser come un elenco (anche da cartelle diverse).
"""
import fnmatch
import os

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QWidget)

from . import APP_NAME, library
from .i18n import tr
from .utils import is_image, is_video, list_subdirs, natural_key


def walk_media(root, sub=True, progress=None):
    """Tutti i file multimediali sotto root (sottocartelle comprese se sub)."""
    out, stack, seen = [], [root], 0
    while stack:
        f = stack.pop()
        seen += 1
        if progress and progress(seen, 0, f):
            raise InterruptedError
        try:
            with os.scandir(f) as it:
                for e in it:
                    try:
                        if e.is_file() and not e.name.startswith(".") and (is_image(e.name) or is_video(e.name)):
                            st = e.stat()
                            out.append((e.path, st.st_size, st.st_mtime))
                    except OSError:
                        continue
        except OSError:
            continue
        if sub:
            stack.extend(p for p in reversed(list_subdirs(f)) if os.path.isdir(p))
    return out


class SearchDialog(QDialog):
    def __init__(self, settings, folder, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Cerca"))
        s = settings
        self.ed_dir = QLineEdit(folder or s.value("search/dir", ""))
        b_dir = QPushButton(tr("Sfoglia…"))
        b_dir.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.ed_dir)
        row.addWidget(b_dir)
        w_dir = QWidget()
        w_dir.setLayout(row)
        self.ck_sub = QCheckBox(tr("Includi sottocartelle"))
        self.ck_sub.setChecked(s.value("search/sub", True, type=bool))
        self.ed_name = QLineEdit(s.value("search/name", ""))
        self.ed_name.setPlaceholderText(tr("parte del nome, oppure *.gif, IMG_2024*…"))
        self.cb_type = QComboBox()
        self.cb_type.addItems([tr("Immagini e video"), tr("Solo immagini"), tr("Solo video"),
                               tr("Solo GIF / WebP animate")])
        self.ck_from = QCheckBox(tr("Dal"))
        self.ck_to = QCheckBox(tr("al"))
        self.d_from = QDateEdit(QDate.currentDate().addYears(-1))
        self.d_to = QDateEdit(QDate.currentDate())
        for d in (self.d_from, self.d_to):
            d.setCalendarPopup(True)
        drow = QHBoxLayout()
        for w in (self.ck_from, self.d_from, self.ck_to, self.d_to):
            drow.addWidget(w)
        drow.addStretch()
        w_date = QWidget()
        w_date.setLayout(drow)
        self.ck_exif = QCheckBox(tr("Usa la data dello scatto (EXIF) quando c'è"))
        self.ck_exif.setChecked(True)
        self.sp_w = QSpinBox(maximum=100000)
        self.sp_h = QSpinBox(maximum=100000)
        for sp in (self.sp_w, self.sp_h):
            sp.setSuffix(" px")
            sp.setSpecialValueText(tr("qualsiasi"))
        srow = QHBoxLayout()
        srow.addWidget(self.sp_w)
        srow.addWidget(self.sp_h)
        w_size = QWidget()
        w_size.setLayout(srow)
        self.ed_cam = QLineEdit()
        self.ed_cam.setPlaceholderText(tr("es. Canon, iPhone, Pixel…"))
        self.cb_rating = QComboBox()
        self.cb_rating.addItems([tr("Qualsiasi")] + [f"≥ {'★' * i}" for i in range(1, 6)] + [tr("Senza valutazione")])
        self.cb_label = QComboBox()
        self.cb_label.addItems([tr("Qualsiasi")] + [library.label_name(i) for i in range(1, 6)] +
                               [tr("Senza etichetta")])
        form = QFormLayout()
        form.addRow(tr("Cerca in:"), w_dir)
        form.addRow("", self.ck_sub)
        form.addRow(tr("Nome:"), self.ed_name)
        form.addRow(tr("Tipo:"), self.cb_type)
        form.addRow(tr("Data:"), w_date)
        form.addRow("", self.ck_exif)
        form.addRow(tr("Larghezza / altezza minime:"), w_size)
        form.addRow(tr("Fotocamera:"), self.ed_cam)
        form.addRow(tr("Valutazione:"), self.cb_rating)
        form.addRow(tr("Etichetta:"), self.cb_label)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Cerca"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.setLayout(form)
        self.resize(620, 0)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Cerca in"), self.ed_dir.text())
        if d:
            self.ed_dir.setText(d)

    def criteria(self):
        import time
        c = {"root": self.ed_dir.text().strip(), "sub": self.ck_sub.isChecked(),
             "name": self.ed_name.text().strip(), "type": self.cb_type.currentIndex(),
             "from": None, "to": None, "exif": self.ck_exif.isChecked(),
             "min_w": self.sp_w.value(), "min_h": self.sp_h.value(),
             "camera": self.ed_cam.text().strip().lower(),
             "rating": self.cb_rating.currentIndex(), "label": self.cb_label.currentIndex()}
        if self.ck_from.isChecked():
            d = self.d_from.date()
            c["from"] = time.mktime((d.year(), d.month(), d.day(), 0, 0, 0, 0, 0, -1))
        if self.ck_to.isChecked():
            d = self.d_to.date()
            c["to"] = time.mktime((d.year(), d.month(), d.day(), 23, 59, 59, 0, 0, -1))
        return c

    def run(self):
        """Ritorna (titolo, [percorsi]) oppure None."""
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        c = self.criteria()
        if not c["root"] or not os.path.isdir(c["root"]):
            QMessageBox.warning(self.parent(), APP_NAME, tr("Scegli una cartella in cui cercare."))
            return None
        s = self.settings
        s.setValue("search/dir", c["root"])
        s.setValue("search/sub", c["sub"])
        s.setValue("search/name", c["name"])
        from .worker import run_with_progress
        res = run_with_progress(self.parent(), tr("Ricerca in corso…"), search, c)
        if res is None:
            return None
        title = tr("Ricerca") + (f": {c['name']}" if c["name"] else "") + f" ({len(res)})"
        return title, res


def search(progress, c):
    from . import anim, exifutil
    from .codecs import read_size
    files = walk_media(c["root"], c["sub"], lambda i, n, t: progress(0, 0, tr("Elenco dei file…") + "\n" + t))
    pat = c["name"].lower()
    if pat and not any(ch in pat for ch in "*?["):
        pat = f"*{pat}*"
    meta = library.get_many([f[0] for f in files]) if (c["rating"] or c["label"]) else {}
    need_exif = bool(c["camera"]) or ((c["from"] or c["to"]) and c["exif"])
    out = []
    for i, (p, size, mt) in enumerate(files):
        if progress(i, len(files), tr("Controllo: {name}", name=os.path.basename(p))):
            raise InterruptedError
        name = os.path.basename(p).lower()
        if pat and not fnmatch.fnmatch(name, pat):
            continue
        t = c["type"]
        video = is_video(p)
        if t == 1 and video or t == 2 and not video:
            continue
        if t == 3 and (video or not anim.is_animated(p)):
            continue
        r, lb = meta.get(p, (0, 0))
        if c["rating"]:
            if c["rating"] == 6 and r:
                continue
            if c["rating"] < 6 and r < c["rating"]:
                continue
        if c["label"]:
            if c["label"] == 6 and lb:
                continue
            if c["label"] < 6 and lb != c["label"]:
                continue
        ex = exifutil.read(p) if need_exif and not video else None
        if c["from"] or c["to"]:
            d = (ex["date"] if ex and ex["date"] else mt)
            if c["from"] and d < c["from"] or c["to"] and d > c["to"]:
                continue
        if c["camera"] and (not ex or c["camera"] not in ex["camera"].lower()):
            continue
        if (c["min_w"] or c["min_h"]) and not video:
            sz = read_size(p)
            if not sz.isValid() or sz.width() < c["min_w"] or sz.height() < c["min_h"]:
                continue
        out.append(p)
    out.sort(key=lambda p: natural_key(p))
    return out



