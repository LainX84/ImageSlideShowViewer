"""Ritocchi rapidi: ritaglio con proporzioni fisse, rotazione, luminosità / contrasto /
saturazione / nitidezza, correzione automatica e ridimensionamento.

Si lavora con Pillow sull'immagine a piena risoluzione; l'anteprima usa una copia
ridotta, così i cursori rispondono subito. Salvando si conservano EXIF e profilo colore.
"""
import os

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from . import APP_NAME, codecs
from .i18n import tr

RATIOS = [("Libero", None), ("Originale", "orig"), ("1:1", (1, 1)), ("4:3", (4, 3)),
          ("3:2", (3, 2)), ("16:9", (16, 9)), ("5:4", (5, 4)), ("21:9", (21, 9)),
          ("3:4", (3, 4)), ("2:3", (2, 3)), ("9:16", (9, 16))]
PREVIEW_MAX = 1400


class CropView(QWidget):
    """Mostra l'anteprima e permette di disegnare / spostare / ridimensionare il ritaglio."""
    changed = Signal()

    HANDLE = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(520, 400)
        self.setMouseTracking(True)
        self.pix = None
        self.img_size = (1, 1)      # dimensioni dell'immagine piena
        self.crop = None            # QRectF in coordinate normalizzate 0..1
        self.ratio = None           # (w, h) in pixel dell'immagine, oppure None
        self._drag = None

    def set_image(self, qimg, full_size):
        self.pix = QPixmap.fromImage(qimg)
        self.img_size = full_size
        self.update()

    def _rect(self):
        if self.pix is None:
            return QRectF()
        W, H = self.width() - 20, self.height() - 20
        s = min(W / self.pix.width(), H / self.pix.height())
        w, h = self.pix.width() * s, self.pix.height() * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_norm(self, p):
        r = self._rect()
        return QPointF(min(1, max(0, (p.x() - r.x()) / r.width())), min(1, max(0, (p.y() - r.y()) / r.height())))

    def _crop_px(self):
        r = self._rect()
        c = self.crop
        return QRectF(r.x() + c.x() * r.width(), r.y() + c.y() * r.height(),
                      c.width() * r.width(), c.height() * r.height())

    def set_ratio(self, ratio):
        self.ratio = ratio
        if self.crop is not None and ratio:
            self.crop = self._fit_ratio(self.crop, anchor="center")
            self.changed.emit()
            self.update()

    def _fit_ratio(self, c, anchor="tl"):
        """Adatta il rettangolo normalizzato c alle proporzioni scelte (in pixel reali)."""
        if not self.ratio:
            return c
        iw, ih = self.img_size
        rw, rh = self.ratio
        target = (rw / rh) * (ih / iw)     # larghezza/altezza in coordinate normalizzate
        w, h = c.width(), c.height()
        if w / max(h, 1e-9) > target:
            w = h * target
        else:
            h = w / target
        if anchor == "center":
            cx, cy = c.center().x(), c.center().y()
            x, y = cx - w / 2, cy - h / 2
        else:
            x, y = c.x(), c.y()
        x = min(max(0, x), 1 - w)
        y = min(max(0, y), 1 - h)
        return QRectF(x, y, min(w, 1), min(h, 1))

    def select_all(self):
        self.crop = self._fit_ratio(QRectF(0, 0, 1, 1), anchor="center") if self.ratio else None
        self.changed.emit()
        self.update()

    def _handle_at(self, pos):
        if self.crop is None:
            return None
        c = self._crop_px()
        for name, pt in (("tl", c.topLeft()), ("tr", c.topRight()), ("bl", c.bottomLeft()),
                         ("br", c.bottomRight())):
            if (pt - pos).manhattanLength() <= self.HANDLE * 1.6:
                return name
        if c.contains(pos):
            return "move"
        return None

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.pix is None:
            return
        h = self._handle_at(e.position())
        n = self._to_norm(e.position())
        if h is None:
            self._drag = ("new", n, None)
            self.crop = QRectF(n, n)
        else:
            self._drag = (h, n, QRectF(self.crop))

    def mouseMoveEvent(self, e):
        if self._drag is None:
            h = self._handle_at(e.position())
            self.setCursor({"move": Qt.CursorShape.SizeAllCursor, "tl": Qt.CursorShape.SizeFDiagCursor,
                            "br": Qt.CursorShape.SizeFDiagCursor, "tr": Qt.CursorShape.SizeBDiagCursor,
                            "bl": Qt.CursorShape.SizeBDiagCursor}.get(h, Qt.CursorShape.CrossCursor))
            return
        kind, start, orig = self._drag
        n = self._to_norm(e.position())
        if kind == "move":
            d = n - start
            c = QRectF(orig.translated(d))
            c.moveLeft(min(max(0, c.x()), 1 - c.width()))
            c.moveTop(min(max(0, c.y()), 1 - c.height()))
            self.crop = c
        else:
            if kind == "new":
                a = start
            else:   # angolo opposto fisso
                a = {"tl": orig.bottomRight(), "tr": orig.bottomLeft(), "bl": orig.topRight(),
                     "br": orig.topLeft()}[kind]
            c = QRectF(a, n).normalized()
            if self.ratio:
                fitted = self._fit_ratio(QRectF(0, 0, c.width(), c.height()))
                w, h = fitted.width(), fitted.height()
                x = a.x() if n.x() >= a.x() else a.x() - w
                y = a.y() if n.y() >= a.y() else a.y() - h
                c = QRectF(x, y, w, h)
            self.crop = c
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag and self.crop is not None and (self.crop.width() < 0.01 or self.crop.height() < 0.01):
            self.crop = None
            self.changed.emit()
        self._drag = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(30, 30, 32))
        if self.pix is None:
            return
        r = self._rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(r, self.pix, QRectF(self.pix.rect()))
        if self.crop is None:
            return
        c = self._crop_px()
        shade = QPainterPath()
        shade.addRect(r)
        hole = QPainterPath()
        hole.addRect(c)
        p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 140))
        p.setPen(QPen(QColor(255, 255, 255), 1.5))
        p.drawRect(c)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for i in (1, 2):    # regola dei terzi
            p.drawLine(QPointF(c.x() + c.width() * i / 3, c.y()), QPointF(c.x() + c.width() * i / 3, c.bottom()))
            p.drawLine(QPointF(c.x(), c.y() + c.height() * i / 3), QPointF(c.right(), c.y() + c.height() * i / 3))
        p.setBrush(QColor(255, 255, 255))
        p.setPen(Qt.PenStyle.NoPen)
        for pt in (c.topLeft(), c.topRight(), c.bottomLeft(), c.bottomRight()):
            p.drawRect(QRectF(pt.x() - 4, pt.y() - 4, 8, 8))
        iw, ih = self.img_size
        txt = f"{round(self.crop.width() * iw)} × {round(self.crop.height() * ih)} px"
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(c.x(), c.bottom() + 4, max(140, c.width()), 18), Qt.AlignmentFlag.AlignLeft, txt)


class EditorDialog(QDialog):
    def __init__(self, path, settings, parent=None):
        super().__init__(parent)
        self.path, self.settings = path, settings
        self.setWindowTitle(tr("Modifica – {name}", name=os.path.basename(path)))
        self.resize(1200, 780)
        self.saved = None
        self.history = []
        self.ok = False
        if not codecs.have_pillow():
            QMessageBox.warning(parent, APP_NAME, tr("Per modificare le immagini serve la libreria Pillow."))
            return
        try:
            self.base, self.exif, self.icc = codecs.open_pil(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(parent, APP_NAME, tr("Impossibile aprire\n{name}\n\n{err}",
                                                     name=os.path.basename(path), err=e))
            return
        self.ok = True
        self.view = CropView()
        self.view.changed.connect(self._crop_changed)

        # --- ritaglio
        self.cb_ratio = QComboBox()
        self.cb_ratio.addItems([tr(n) if n in ("Libero", "Originale") else n for n, _r in RATIOS])
        self.cb_ratio.currentIndexChanged.connect(self._ratio_changed)
        b_swap = QPushButton("↔")
        b_swap.setToolTip(tr("Scambia orizzontale / verticale"))
        b_swap.setFixedWidth(36)
        b_swap.clicked.connect(self._swap_ratio)
        b_all = QPushButton(tr("Tutta"))
        b_all.clicked.connect(self.view.select_all)
        self.b_crop = QPushButton(tr("Applica ritaglio"))
        self.b_crop.clicked.connect(self.apply_crop)
        self.b_crop.setEnabled(False)
        g1 = QGroupBox(tr("Ritaglia"))
        l1 = QGridLayout(g1)
        l1.addWidget(QLabel(tr("Proporzioni:")), 0, 0)
        l1.addWidget(self.cb_ratio, 0, 1)
        l1.addWidget(b_swap, 0, 2)
        l1.addWidget(QLabel(tr("Trascina sull'immagine per scegliere l'area.")), 1, 0, 1, 3)
        l1.addWidget(b_all, 2, 0)
        l1.addWidget(self.b_crop, 2, 1, 1, 2)

        # --- rotazione
        g2 = QGroupBox(tr("Ruota e specchia"))
        l2 = QHBoxLayout(g2)
        for text, tip, op in (("⟲", tr("Ruota a sinistra"), "left"), ("⟳", tr("Ruota a destra"), "right"),
                              ("180°", tr("Ruota di 180°"), "180"), ("↔", tr("Specchia in orizzontale"), "flip_h"),
                              ("↕", tr("Specchia in verticale"), "flip_v")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, op=op: self.transform(op))
            l2.addWidget(b)

        # --- regolazioni
        g3 = QGroupBox(tr("Regolazioni"))
        f3 = QFormLayout(g3)
        self.sliders = {}
        for key, label in (("brightness", tr("Luminosità")), ("contrast", tr("Contrasto")),
                           ("saturation", tr("Saturazione")), ("sharpness", tr("Nitidezza"))):
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(-100, 100)
            s.setValue(0)
            s.valueChanged.connect(self._schedule)
            s.setToolTip("0")
            s.valueChanged.connect(lambda v, s=s: s.setToolTip(str(v)))
            self.sliders[key] = s
            f3.addRow(label, s)
        self.ck_auto = QCheckBox(tr("Correzione automatica (livelli e contrasto)"))
        self.ck_auto.toggled.connect(self._schedule)
        f3.addRow(self.ck_auto)
        b_reset = QPushButton(tr("Azzera le regolazioni"))
        b_reset.clicked.connect(self._reset_adjust)
        f3.addRow(b_reset)

        # --- ridimensiona
        g4 = QGroupBox(tr("Ridimensiona al salvataggio"))
        f4 = QFormLayout(g4)
        self.ck_resize = QCheckBox(tr("Ridimensiona"))
        self.sp_w = QSpinBox(minimum=1, maximum=60000)
        self.sp_h = QSpinBox(minimum=1, maximum=60000)
        self.sp_pct = QSpinBox(minimum=1, maximum=400, value=100)
        self.sp_pct.setSuffix(" %")
        self.ck_keep = QCheckBox(tr("Mantieni le proporzioni"))
        self.ck_keep.setChecked(True)
        f4.addRow(self.ck_resize)
        f4.addRow(tr("Larghezza:"), self.sp_w)
        f4.addRow(tr("Altezza:"), self.sp_h)
        f4.addRow(tr("Percentuale:"), self.sp_pct)
        f4.addRow(self.ck_keep)
        self.sp_w.valueChanged.connect(lambda v: self._size_changed("w"))
        self.sp_h.valueChanged.connect(lambda v: self._size_changed("h"))
        self.sp_pct.valueChanged.connect(lambda v: self._size_changed("pct"))
        for w in (self.sp_w, self.sp_h, self.sp_pct, self.ck_keep):
            w.setEnabled(False)
        self.ck_resize.toggled.connect(lambda on: [w.setEnabled(on) for w in
                                                   (self.sp_w, self.sp_h, self.sp_pct, self.ck_keep)])

        # --- salva
        self.sp_quality = QSpinBox(minimum=1, maximum=100, value=settings.value("edit/quality", 92, type=int))
        self.lb_size = QLabel()
        self.b_undo = QPushButton(tr("Annulla ultima modifica"))
        self.b_undo.clicked.connect(self.undo)
        self.b_undo.setEnabled(False)
        b_save = QPushButton(tr("Salva"))
        b_save.setDefault(True)
        b_save.clicked.connect(lambda: self.save(False))
        b_saveas = QPushButton(tr("Salva con nome…"))
        b_saveas.clicked.connect(lambda: self.save(True))
        b_close = QPushButton(tr("Chiudi"))
        b_close.clicked.connect(self.reject)
        key = codecs.key_for_ext(os.path.splitext(path)[1])
        if not key or key not in {k for _n, k, _e in codecs.write_formats()}:
            b_save.setEnabled(False)
            b_save.setToolTip(tr("Questo formato non si può salvare: usa «Salva con nome…»"))

        side = QVBoxLayout()
        for g in (g1, g2, g3, g4):
            side.addWidget(g)
        side.addStretch()
        q = QHBoxLayout()
        q.addWidget(QLabel(tr("Qualità:")))
        q.addWidget(self.sp_quality)
        q.addStretch()
        side.addLayout(q)
        side.addWidget(self.lb_size)
        side.addWidget(self.b_undo)
        row = QHBoxLayout()
        row.addWidget(b_save)
        row.addWidget(b_saveas)
        row.addWidget(b_close)
        side.addLayout(row)
        sw = QWidget()
        sw.setLayout(side)
        sw.setFixedWidth(360)
        lay = QHBoxLayout(self)
        lay.addWidget(self.view, 1)
        lay.addWidget(sw)

        self._timer = QTimer(self, singleShot=True, interval=60)
        self._timer.timeout.connect(self._update_preview)
        self._rebuild()

    # -------------------------------------------------------------- stato
    def _rebuild(self):
        """Dopo un ritaglio / rotazione: nuova copia ridotta per l'anteprima."""
        from PIL import Image
        im = self.base
        if max(im.size) > PREVIEW_MAX:
            im = im.copy()
            im.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.Resampling.LANCZOS)
        self.small = im
        self.view.crop = None
        self._ratio_changed()
        self.b_crop.setEnabled(False)
        for w, v in ((self.sp_w, self.base.width), (self.sp_h, self.base.height)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        self.sp_pct.blockSignals(True)
        self.sp_pct.setValue(100)
        self.sp_pct.blockSignals(False)
        self._update_preview()

    def _adjust(self, im):
        from PIL import ImageEnhance, ImageOps
        alpha = im.getchannel("A") if "A" in im.getbands() else None
        rgb = im.convert("RGB") if im.mode != "RGB" else im
        if self.ck_auto.isChecked():
            rgb = ImageOps.autocontrast(rgb, cutoff=0.5, preserve_tone=True)
        for key, cls in (("brightness", ImageEnhance.Brightness), ("contrast", ImageEnhance.Contrast),
                         ("saturation", ImageEnhance.Color), ("sharpness", ImageEnhance.Sharpness)):
            v = self.sliders[key].value()
            if v:
                f = 1 + v / 100 if key != "sharpness" else 1 + v / 50
                rgb = cls(rgb).enhance(max(0.0, f))
        if alpha is not None:
            rgb = rgb.convert("RGBA")
            rgb.putalpha(alpha)
        return rgb

    def _adjusted(self):
        return self.ck_auto.isChecked() or any(s.value() for s in self.sliders.values())

    def _update_preview(self):
        im = self._adjust(self.small) if self._adjusted() else self.small
        self.view.set_image(codecs.pil_to_qimage(im), self.base.size)
        self._update_size_label()

    def _schedule(self, *_):
        self._timer.start()

    def _reset_adjust(self):
        for s in self.sliders.values():
            s.blockSignals(True)
            s.setValue(0)
            s.blockSignals(False)
        self.ck_auto.setChecked(False)
        self._update_preview()

    def _ratio_changed(self, *_):
        r = RATIOS[self.cb_ratio.currentIndex()][1]
        if r == "orig":
            r = self.base.size
        self.view.set_ratio(r)

    def _swap_ratio(self):
        r = self.view.ratio
        if r:
            self.view.set_ratio((r[1], r[0]))

    def _crop_changed(self):
        self.b_crop.setEnabled(self.view.crop is not None)

    def _push(self):
        self.history.append(self.base)
        self.history = self.history[-10:]
        self.b_undo.setEnabled(True)

    def apply_crop(self):
        c = self.view.crop
        if c is None:
            return
        w, h = self.base.size
        box = (round(c.x() * w), round(c.y() * h), round(c.right() * w), round(c.bottom() * h))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return
        self._push()
        self.base = self.base.crop(box)
        self._rebuild()

    def transform(self, op):
        from PIL import Image
        T = Image.Transpose
        t = {"left": T.ROTATE_90, "right": T.ROTATE_270, "180": T.ROTATE_180,
             "flip_h": T.FLIP_LEFT_RIGHT, "flip_v": T.FLIP_TOP_BOTTOM}[op]
        self._push()
        self.base = self.base.transpose(t)
        self._rebuild()

    def undo(self):
        if self.history:
            self.base = self.history.pop()
            self.b_undo.setEnabled(bool(self.history))
            self._rebuild()

    def _size_changed(self, which):
        w0, h0 = self.base.size
        widgets = (self.sp_w, self.sp_h, self.sp_pct)
        for x in widgets:
            x.blockSignals(True)
        if which == "pct":
            p = self.sp_pct.value() / 100
            self.sp_w.setValue(max(1, round(w0 * p)))
            self.sp_h.setValue(max(1, round(h0 * p)))
        elif self.ck_keep.isChecked():
            if which == "w":
                self.sp_h.setValue(max(1, round(self.sp_w.value() * h0 / w0)))
            else:
                self.sp_w.setValue(max(1, round(self.sp_h.value() * w0 / h0)))
            self.sp_pct.setValue(max(1, round(self.sp_w.value() / w0 * 100)))
        for x in widgets:
            x.blockSignals(False)
        self._update_size_label()

    def _final_size(self):
        if self.ck_resize.isChecked():
            return self.sp_w.value(), self.sp_h.value()
        return self.base.size

    def _update_size_label(self):
        w, h = self._final_size()
        self.lb_size.setText(tr("Dimensioni finali: {w} × {h} px", w=w, h=h))

    # -------------------------------------------------------------- salva
    def _result(self):
        from PIL import Image
        im = self._adjust(self.base) if self._adjusted() else self.base
        size = self._final_size()
        if size != im.size:
            im = im.resize(size, Image.Resampling.LANCZOS)
        return im

    def save(self, ask):
        dst = self.path
        if ask:
            fmts = codecs.write_formats()
            filt = ";;".join(f"{n} (*{e})" for n, _k, e in fmts)
            start = os.path.splitext(self.path)[0] + "_modificata" + os.path.splitext(self.path)[1]
            dst, _f = QFileDialog.getSaveFileName(self, tr("Salva con nome"), start, filt)
            if not dst:
                return
        key = codecs.key_for_ext(os.path.splitext(dst)[1]) or "jpeg"
        if not os.path.splitext(dst)[1]:
            dst += ".jpg"
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            im = self._result()
            tmp = dst + ".isvtmp" + os.path.splitext(dst)[1]
            codecs.save_pil(im, tmp, key, self.sp_quality.value(), False, self.exif, self.icc)
            os.replace(tmp, dst)
        except Exception as e:  # noqa: BLE001
            self.unsetCursor()
            QMessageBox.warning(self, APP_NAME, tr("Salvataggio non riuscito:\n{err}", err=e))
            return
        self.unsetCursor()
        self.settings.setValue("edit/quality", self.sp_quality.value())
        self.saved = dst
        self.accept()

    def run(self):
        if not self.ok:
            return None
        self.exec()
        return self.saved
