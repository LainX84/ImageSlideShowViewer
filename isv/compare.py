"""Confronto di due immagini: affiancate con zoom e spostamento sincronizzati, oppure
sovrapposte con una tendina che si trascina (utile per scegliere fra scatti simili).

Tasti: T cambia modalità, S scambia, Z adatta / 100%, + / − zoom, Esc chiude.
Rotellina = zoom sul punto del mouse, trascina = sposta, trascina la linea = tendina.
"""
import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import APP_NAME, codecs
from .archive import stat_any
from .i18n import tr
from .utils import human_size


class CompareView(QWidget):
    def __init__(self, a, b, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(600, 400)
        self.imgs = [a, b]
        self.pix = [QPixmap.fromImage(a), QPixmap.fromImage(b)]
        self.mode = "side"          # side | slider
        self.z = 1.0                # zoom relativo all'adattamento
        self.c = QPointF(0.5, 0.5)  # centro della vista in coordinate normalizzate
        self.split = 0.5
        self._drag = None

    # ------------------------------------------------------------ geometria
    def _areas(self):
        W, H = self.width(), self.height()
        if self.mode == "side":
            half = (W - 6) / 2
            return [QRectF(0, 0, half, H), QRectF(half + 6, 0, half, H)]
        return [QRectF(0, 0, W, H), QRectF(0, 0, W, H)]

    def _fit(self, i, area):
        im = self.imgs[i]
        return min(area.width() / im.width(), area.height() / im.height())

    def _rect(self, i):
        area = self._areas()[i]
        im = self.imgs[i]
        if self.mode == "slider":
            # nella tendina entrambe usano lo stesso riquadro della prima immagine
            s0 = self._fit(0, area) * self.z
            w, h = self.imgs[0].width() * s0, self.imgs[0].height() * s0
        else:
            s = self._fit(i, area) * self.z
            w, h = im.width() * s, im.height() * s
        cx = area.x() + area.width() / 2 - (self.c.x() - 0.5) * w
        cy = area.y() + area.height() / 2 - (self.c.y() - 0.5) * h
        return QRectF(cx - w / 2, cy - h / 2, w, h)

    def scale100(self):
        """Zoom relativo che mostra la prima immagine al 100%."""
        area = self._areas()[0]
        return 1.0 / max(1e-6, self._fit(0, area) * self.devicePixelRatioF())

    def set_zoom(self, z, anchor=None):
        z = max(0.1, min(64.0, z))
        if anchor is not None:
            # il punto sotto il mouse resta fermo
            i = 0 if self.mode == "slider" or anchor.x() < self.width() / 2 else 1
            r = self._rect(i)
            nx = (anchor.x() - r.x()) / r.width()
            ny = (anchor.y() - r.y()) / r.height()
            k = self.z / z
            self.c = QPointF(nx + (self.c.x() - nx) * k, ny + (self.c.y() - ny) * k)
        self.z = z
        if z <= 1.0:
            self.c = QPointF(0.5, 0.5)
        self.update()

    def swap(self):
        self.imgs.reverse()
        self.pix.reverse()
        self.update()

    # --------------------------------------------------------------- mouse
    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.set_zoom(self.z * f, e.position())

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        sx = self.split * self.width()
        if self.mode == "slider" and abs(e.position().x() - sx) < 10:
            self._drag = ("split", None, None)
        else:
            self._drag = ("pan", e.position(), QPointF(self.c))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            near = self.mode == "slider" and abs(e.position().x() - self.split * self.width()) < 10
            self.setCursor(Qt.CursorShape.SplitHCursor if near else Qt.CursorShape.ArrowCursor)
            return
        kind, start, c0 = self._drag
        if kind == "split":
            self.split = min(1.0, max(0.0, e.position().x() / max(1, self.width())))
        else:
            r = self._rect(0)
            d = e.position() - start
            self.c = QPointF(c0.x() - d.x() / r.width(), c0.y() - d.y() / r.height())
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, e):
        self.set_zoom(1.0 if self.z > 1.01 else self.scale100(), e.position())

    # -------------------------------------------------------------- disegno
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(16, 16, 18))
        smooth = self.z < 2
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, smooth)
        areas = self._areas()
        if self.mode == "side":
            for i in (0, 1):
                p.save()
                p.setClipRect(areas[i])
                p.drawPixmap(self._rect(i), self.pix[i], QRectF(self.pix[i].rect()))
                p.restore()
        else:
            sx = self.split * self.width()
            p.save()
            p.setClipRect(QRectF(sx, 0, self.width() - sx, self.height()))
            p.drawPixmap(self._rect(1), self.pix[1], QRectF(self.pix[1].rect()))
            p.restore()
            p.save()
            p.setClipRect(QRectF(0, 0, sx, self.height()))
            p.drawPixmap(self._rect(0), self.pix[0], QRectF(self.pix[0].rect()))
            p.restore()
            p.setPen(QPen(QColor(255, 255, 255, 220), 2))
            p.drawLine(QPointF(sx, 0), QPointF(sx, self.height()))
            path = QPainterPath()
            path.addEllipse(QPointF(sx, self.height() / 2), 12, 12)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillPath(path, QColor(255, 255, 255, 220))
            p.setPen(QColor(30, 30, 30))
            p.drawText(QRectF(sx - 12, self.height() / 2 - 12, 24, 24), Qt.AlignmentFlag.AlignCenter, "⇔")
        f = QFont(self.font())
        f.setPointSize(10)
        p.setFont(f)
        p.setPen(QColor(230, 230, 230))
        pct = self._fit(0, areas[0]) * self.z * self.devicePixelRatioF() * 100
        p.drawText(QRectF(10, self.height() - 26, 300, 20), Qt.AlignmentFlag.AlignLeft, f"{pct:.0f}%")


class CompareWindow(QWidget):
    def __init__(self, path_a, path_b, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("Confronta – {app}", app=APP_NAME))
        self.paths = [path_a, path_b]
        a, ea = codecs.read_qimage(path_a)
        b, eb = codecs.read_qimage(path_b)
        self.ok = not a.isNull() and not b.isNull()
        if not self.ok:
            return
        self.view = CompareView(a, b)
        self.cb = QComboBox()
        self.cb.addItems([tr("Affiancate (zoom sincronizzato)"), tr("Tendina (sovrapposte)")])
        self.cb.currentIndexChanged.connect(self._mode)
        b_fit = QPushButton(tr("Adatta"))
        b_fit.clicked.connect(lambda: self.view.set_zoom(1.0))
        b_100 = QPushButton("100%")
        b_100.clicked.connect(lambda: self.view.set_zoom(self.view.scale100()))
        b_swap = QPushButton(tr("Scambia"))
        b_swap.clicked.connect(self._swap)
        self.la, self.lb = QLabel(), QLabel()
        for lb in (self.la, self.lb):
            lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top = QHBoxLayout()
        top.addWidget(self.cb)
        top.addWidget(b_fit)
        top.addWidget(b_100)
        top.addWidget(b_swap)
        top.addStretch()
        top.addWidget(QLabel(tr("T modalità · S scambia · Z adatta/100% · rotellina zoom · Esc chiudi")))
        names = QHBoxLayout()
        names.addWidget(self.la, 1)
        names.addWidget(self.lb, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addLayout(top)
        lay.addLayout(names)
        lay.addWidget(self.view, 1)
        self._labels()
        self.resize(1400, 860)

    def _labels(self):
        for lb, p, im in zip((self.la, self.lb), self.paths, self.view.imgs):
            try:
                size = human_size(stat_any(p)[1])
            except OSError:
                size = "?"
            name = os.path.basename(p.split("|")[-1])
            lb.setText(f"<b>{name}</b> — {im.width()}×{im.height()} px — {size}")
        self.lb.setAlignment(Qt.AlignmentFlag.AlignRight if self.view.mode == "side" else Qt.AlignmentFlag.AlignLeft)

    def _mode(self, i):
        self.view.mode = "side" if i == 0 else "slider"
        self.view.update()
        self._labels()

    def _swap(self):
        self.view.swap()
        self.paths.reverse()
        self._labels()

    def keyPressEvent(self, e):
        k = e.key()
        K = Qt.Key
        if k == K.Key_Escape:
            self.close()
        elif k == K.Key_T:
            self.cb.setCurrentIndex(1 - self.cb.currentIndex())
        elif k == K.Key_S:
            self._swap()
        elif k in (K.Key_Z, K.Key_0):
            self.view.set_zoom(1.0 if self.view.z > 1.01 else self.view.scale100())
        elif k in (K.Key_Plus, K.Key_Equal):
            self.view.set_zoom(self.view.z * 1.25)
        elif k == K.Key_Minus:
            self.view.set_zoom(self.view.z / 1.25)
        elif k in (K.Key_F, K.Key_F11):
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else:
            super().keyPressEvent(e)
