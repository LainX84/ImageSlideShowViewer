"""Trova duplicati: file identici (stesso contenuto) oppure immagini simili (anche
ridimensionate, ricompresse o in formati diversi), confrontando una piccola "impronta"
dell'immagine (dHash a 64 bit).

Nei risultati si scelgono i file da spostare nel Cestino; ci sono scorciatoie per
tenere, in ogni gruppo, il file più grande o quello più vecchio.
"""
import hashlib
import os
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSlider, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import APP_NAME, codecs
from .i18n import tr
from .search import walk_media
from .utils import human_size, is_video


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dhash(path):
    """Impronta a 64 bit: confronta la luminosità di pixel vicini su una copia 9×8."""
    img, _e = codecs.read_qimage(path, 256)
    if img.isNull():
        return None
    g = img.convertToFormat(QImage.Format.Format_Grayscale8).scaled(
        9, 8, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    bpl = g.bytesPerLine()
    raw = bytes(g.constBits())[:bpl * 8]
    v = 0
    for y in range(8):
        row = raw[y * bpl:y * bpl + 9]
        for x in range(8):
            v = (v << 1) | (row[x] > row[x + 1])
    return v


def find(progress, roots, sub, mode, threshold):
    files = []
    for r in roots:
        files += walk_media(r, sub, lambda i, n, t: progress(0, 0, tr("Elenco dei file…") + "\n" + t))
    files = [f for f in files if not is_video(f[0])] if mode == "similar" else files
    groups = []
    if mode == "exact":
        by_size = {}
        for p, size, mt in files:
            by_size.setdefault(size, []).append(p)
        cands = [ps for s, ps in by_size.items() if len(ps) > 1 and s > 0]
        total = sum(len(c) for c in cands)
        done = 0
        for ps in cands:
            by_hash = {}
            for p in ps:
                done += 1
                if progress(done, total, tr("Confronto: {name}", name=os.path.basename(p))):
                    raise InterruptedError
                try:
                    by_hash.setdefault(_sha1(p), []).append(p)
                except OSError:
                    pass
            groups += [g for g in by_hash.values() if len(g) > 1]
    else:
        hashes = []
        for i, (p, _s, _m) in enumerate(files):
            if progress(i, len(files), tr("Analisi: {name}", name=os.path.basename(p))):
                raise InterruptedError
            h = dhash(p)
            if h is not None:
                hashes.append((p, h))
        parent = list(range(len(hashes)))

        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        n = len(hashes)
        try:
            import numpy as np
            arr = np.array([h for _p, h in hashes], dtype=np.uint64)
            for i in range(n):
                if i % 200 == 0 and progress(i, n, tr("Confronto delle impronte…")):
                    raise InterruptedError
                x = np.bitwise_xor(arr[i + 1:], arr[i])
                bits = np.unpackbits(x.view(np.uint8).reshape(-1, 8), axis=1).sum(axis=1)
                for j in np.nonzero(bits <= threshold)[0]:
                    a, b = root(i), root(i + 1 + int(j))
                    if a != b:
                        parent[b] = a
        except ImportError:
            for i in range(n):
                if i % 100 == 0 and progress(i, n, tr("Confronto delle impronte…")):
                    raise InterruptedError
                hi = hashes[i][1]
                for j in range(i + 1, n):
                    if (hi ^ hashes[j][1]).bit_count() <= threshold:
                        a, b = root(i), root(j)
                        if a != b:
                            parent[b] = a
        by_root = {}
        for i, (p, _h) in enumerate(hashes):
            by_root.setdefault(root(i), []).append(p)
        groups = [g for g in by_root.values() if len(g) > 1]
    groups.sort(key=lambda g: -len(g))
    return groups


class FindDialog(QDialog):
    def __init__(self, settings, folders, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Trova duplicati"))
        self.ed = QLineEdit("; ".join(folders))
        b = QPushButton(tr("Sfoglia…"))
        b.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.ed)
        row.addWidget(b)
        w = QWidget()
        w.setLayout(row)
        self.ck_sub = QCheckBox(tr("Includi sottocartelle"))
        self.ck_sub.setChecked(True)
        self.cb_mode = QComboBox()
        self.cb_mode.addItems([tr("Identici (stesso contenuto, byte per byte)"),
                               tr("Simili (anche ridimensionati, ricompressi o convertiti)")])
        self.cb_mode.setCurrentIndex(settings.value("dups/mode", 0, type=int))
        self.sl = QSlider(Qt.Orientation.Horizontal)
        self.sl.setRange(0, 16)
        self.sl.setValue(settings.value("dups/threshold", 6, type=int))
        self.lb = QLabel()
        self.sl.valueChanged.connect(self._lbl)
        srow = QHBoxLayout()
        srow.addWidget(QLabel(tr("molto simili")))
        srow.addWidget(self.sl)
        srow.addWidget(QLabel(tr("vagamente simili")))
        sw = QWidget()
        sw.setLayout(srow)
        self.cb_mode.currentIndexChanged.connect(lambda i: sw.setEnabled(i == 1))
        sw.setEnabled(self.cb_mode.currentIndex() == 1)
        form = QFormLayout(self)
        form.addRow(tr("Cartelle:"), w)
        form.addRow("", self.ck_sub)
        form.addRow(tr("Cerca:"), self.cb_mode)
        form.addRow(tr("Somiglianza:"), sw)
        form.addRow("", self.lb)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Cerca"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._lbl()
        self.resize(640, 0)

    def _lbl(self):
        self.lb.setText(tr("Differenza massima: {n} bit su 64", n=self.sl.value()))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, tr("Cartella"), self.ed.text().split(";")[0].strip())
        if d:
            self.ed.setText(d)

    def run(self):
        if self.exec() != QDialog.DialogCode.Accepted:
            return None
        roots = [r.strip() for r in self.ed.text().split(";") if r.strip() and os.path.isdir(r.strip())]
        if not roots:
            QMessageBox.warning(self.parent(), APP_NAME, tr("Scegli almeno una cartella."))
            return None
        mode = "exact" if self.cb_mode.currentIndex() == 0 else "similar"
        self.settings.setValue("dups/mode", self.cb_mode.currentIndex())
        self.settings.setValue("dups/threshold", self.sl.value())
        from .worker import run_with_progress
        return run_with_progress(self.parent(), tr("Ricerca dei duplicati…"), find, roots,
                                 self.ck_sub.isChecked(), mode, self.sl.value())


class ResultsWindow(QDialog):
    """Gruppi di duplicati con le caselle per scegliere cosa eliminare."""

    def __init__(self, groups, open_cb=None, show_cb=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("Duplicati trovati: {n} gruppi", n=len(groups)))
        self.open_cb, self.show_cb = open_cb, show_cb
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("File"), tr("Cartella"), tr("Dimensione"), tr("Pixel"), tr("Data")])
        self.tree.setIconSize(QSize(64, 64))
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tree.itemDoubleClicked.connect(self._open)
        self.items = []
        for gi, g in enumerate(groups):
            top = QTreeWidgetItem(self.tree, [tr("Gruppo {i} ({n} file)", i=gi + 1, n=len(g))])
            top.setFirstColumnSpanned(True)
            for p in g:
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                sz = codecs.read_size(p) if not is_video(p) else QSize()
                it = QTreeWidgetItem(top, [os.path.basename(p), os.path.dirname(p), human_size(st.st_size),
                                           f"{sz.width()}×{sz.height()}" if sz.isValid() else "",
                                           time.strftime(tr("%d/%m/%Y %H:%M"), time.localtime(st.st_mtime))])
                it.setData(0, Qt.ItemDataRole.UserRole, (p, st.st_size, st.st_mtime,
                                                         sz.width() * sz.height() if sz.isValid() else 0))
                it.setCheckState(0, Qt.CheckState.Unchecked)
                self.items.append(it)
            top.setExpanded(True)
        self._thumb_queue = list(self.items)
        QTimer.singleShot(50, self._thumbs)
        b_big = QPushButton(tr("Seleziona tutti tranne il più grande"))
        b_big.clicked.connect(lambda: self._keep("big"))
        b_old = QPushButton(tr("Seleziona tutti tranne il più vecchio"))
        b_old.clicked.connect(lambda: self._keep("old"))
        b_none = QPushButton(tr("Deseleziona tutto"))
        b_none.clicked.connect(lambda: [i.setCheckState(0, Qt.CheckState.Unchecked) for i in self.items])
        b_show = QPushButton(tr("Mostra nel browser"))
        b_show.clicked.connect(self._show)
        b_del = QPushButton(tr("Sposta i selezionati nel Cestino"))
        b_del.clicked.connect(self._delete)
        b_close = QPushButton(tr("Chiudi"))
        b_close.clicked.connect(self.close)
        row = QHBoxLayout()
        for b in (b_big, b_old, b_none):
            row.addWidget(b)
        row.addStretch()
        row2 = QHBoxLayout()
        row2.addWidget(b_show)
        row2.addStretch()
        row2.addWidget(b_del)
        row2.addWidget(b_close)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("Doppio clic per vedere un'immagine. Spunta i file da eliminare.")))
        lay.addWidget(self.tree)
        lay.addLayout(row)
        lay.addLayout(row2)
        self.resize(1100, 720)

    def _thumbs(self):
        for _ in range(6):
            if not self._thumb_queue:
                return
            it = self._thumb_queue.pop(0)
            p = it.data(0, Qt.ItemDataRole.UserRole)[0]
            if not is_video(p):
                img, _e = codecs.read_qimage(p, 128)
                if not img.isNull():
                    it.setIcon(0, QIcon(QPixmap.fromImage(img)))
        QTimer.singleShot(10, self._thumbs)

    def _keep(self, how):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            kids = [top.child(j) for j in range(top.childCount())]
            if not kids:
                continue
            data = [k.data(0, Qt.ItemDataRole.UserRole) for k in kids]
            if how == "big":
                keep = max(range(len(kids)), key=lambda j: (data[j][3], data[j][1]))
            else:
                keep = min(range(len(kids)), key=lambda j: data[j][2])
            for j, k in enumerate(kids):
                k.setCheckState(0, Qt.CheckState.Unchecked if j == keep else Qt.CheckState.Checked)

    def _checked(self):
        return [i for i in self.items if i.checkState(0) == Qt.CheckState.Checked]

    def _open(self, it, _col):
        d = it.data(0, Qt.ItemDataRole.UserRole)
        if d and self.open_cb:
            self.open_cb(d[0])

    def _show(self):
        if self.show_cb:
            self.show_cb([i.data(0, Qt.ItemDataRole.UserRole)[0] for i in self.items])

    def _delete(self):
        sel = self._checked()
        if not sel:
            return
        r = QMessageBox.question(self, self.windowTitle(),
                                 tr("Spostare nel Cestino {n} file?", n=len(sel)))
        if r != QMessageBox.StandardButton.Yes:
            return
        from .batch import move_to_trash
        failed = 0
        for it in sel:
            p = it.data(0, Qt.ItemDataRole.UserRole)[0]
            if move_to_trash(p):
                it.parent().removeChild(it)
                self.items.remove(it)
            else:
                failed += 1
        if failed:
            QMessageBox.warning(self, self.windowTitle(), tr("Non spostati: {n}", n=failed))
