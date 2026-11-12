"""Superficie di disegno del visualizzatore e dello slideshow.

Due versioni con lo stesso comportamento:
  * Canvas   disegno con la CPU (immagine ridimensionata in alta qualità e in cache);
  * GLCanvas disegno con la GPU (OpenGL, texture con mipmap: vedi gpu.py).

Funzioni: adatta alla finestra / larghezza / altezza / riempi, zoom e spostamento,
due immagini affiancate, sfondo (nero, grigio, bianco, a scacchi), lente
d'ingrandimento, istogramma, colore del pixel, transizioni (dissolvenza, scorrimento,
Ken Burns) e scritte in sovrimpressione.
"""
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import gpu
from .i18n import tr

FIT_MODES = ["fit", "width", "height", "fill"]
BACKGROUNDS = ["black", "gray", "white", "checker"]
TRANSITIONS = ["none", "fade", "slide", "kenburns"]
MAX_PRESCALE = 40_000_000       # oltre (pixel) si disegna dall'originale, senza cache


def fit_mode_name(m):
    return {"fit": tr("Adatta alla finestra"), "width": tr("Adatta alla larghezza"),
            "height": tr("Adatta all'altezza"), "fill": tr("Riempi lo schermo")}.get(m, m)


def background_name(b):
    return {"black": tr("Nero"), "gray": tr("Grigio"), "white": tr("Bianco"),
            "checker": tr("A scacchi")}.get(b, b)


def transition_name(t):
    return {"none": tr("Nessuna"), "fade": tr("Dissolvenza"), "slide": tr("Scorrimento"),
            "kenburns": tr("Ken Burns (zoom lento + dissolvenza)")}.get(t, t)


def make_canvas(parent=None):
    """Canvas disegnato dalla GPU (OpenGL) se attivo e disponibile, altrimenti dalla CPU."""
    if gpu.enabled():
        try:
            return GLCanvas(parent)
        except Exception:  # noqa: BLE001 - modulo OpenGL mancante nel pacchetto
            pass
    return Canvas(parent)


def _checker_brush():
    pm = QPixmap(32, 32)
    pm.fill(QColor(200, 200, 200))
    p = QPainter(pm)
    p.fillRect(0, 0, 16, 16, QColor(150, 150, 150))
    p.fillRect(16, 16, 16, 16, QColor(150, 150, 150))
    p.end()
    return QBrush(pm)


def histogram(img):
    """Istogramma (r, g, b, luminanza) a 256 livelli, da una copia ridotta."""
    small = img.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.FastTransformation).convertToFormat(QImage.Format.Format_RGBA8888)
    w, h, bpl = small.width(), small.height(), small.bytesPerLine()
    raw = bytes(small.constBits())[:bpl * h]
    try:
        import numpy as np
        a = np.frombuffer(raw, dtype=np.uint8).reshape(h, bpl)[:, :w * 4].reshape(-1, 4)
        r = np.bincount(a[:, 0], minlength=256)
        g = np.bincount(a[:, 1], minlength=256)
        b = np.bincount(a[:, 2], minlength=256)
        lum = np.bincount(((a[:, 0] * 77 + a[:, 1] * 150 + a[:, 2] * 29) >> 8), minlength=256)
        return [list(map(int, x)) for x in (r, g, b, lum)]
    except ImportError:
        r, g, b, lum = [0] * 256, [0] * 256, [0] * 256, [0] * 256
        for y in range(h):
            row = raw[y * bpl:y * bpl + w * 4]
            for i in range(0, len(row), 4):
                R, G, B = row[i], row[i + 1], row[i + 2]
                r[R] += 1
                g[G] += 1
                b[B] += 1
                lum[(R * 77 + G * 150 + B * 29) >> 8] += 1
        return [r, g, b, lum]


class _CanvasLogic:
    GAP = 6
    gl = False

    def _init_canvas(self):
        self.setMouseTracking(True)
        self.image = None
        self.image2 = None      # seconda immagine affiancata
        self.rtl = False        # modalità manga: la prima immagine della coppia a destra
        self._scaled = None
        self._scaled2 = None
        self._full = None
        self._full2 = None
        self.zoom = None        # None = secondo fit_mode
        self.fit_mode = "fit"
        self.enlarge = False
        self.offset = QPointF(0, 0)
        self._drag = None
        self.message = ""
        self.info_lines = []
        self.show_info = False
        self.osd = ""
        self.osd_kind = "msg"
        self.paused = False
        self.badge_on = False
        self.background = "black"
        self._checker = None
        self.loupe = False
        self.loupe_mag = 3.0
        self.show_pixel = False
        self.show_hist = False
        self._hist = None       # (cacheKey, dati)
        self.mouse = None
        self.trans = None       # transizione in corso
        self._snap = None       # immagine della schermata precedente (per la transizione)
        self._snap_kind = None
        self.kb = None          # Ken Burns
        from .options import DEFAULTS
        self.style_ = dict(DEFAULTS)
        self._osd_timer = QTimer(self, singleShot=True, interval=1600)
        self._osd_timer.timeout.connect(self._clear_osd)
        self._anim_timer = QTimer(self, interval=16 if self.gl else 33)
        self._anim_timer.timeout.connect(self._anim_tick)

    # --------------------------------------------------------------- stato
    def set_image(self, img, keep_view=False):
        self.image = img
        self.image2 = None
        self.message = ""
        self._full = self._full2 = None
        if not keep_view:
            self.offset = QPointF(0, 0)
            self.zoom = None
            self._align_start()
            self._start_pending_transition()
        self._rescale()
        self._clamp()
        self.update()

    def set_pair(self, img1, img2):
        self.image = img1
        self.image2 = img2 if img2 is not None and not img2.isNull() else None
        self.message = ""
        self._full = self._full2 = None
        self.offset = QPointF(0, 0)
        self.zoom = None
        self.kb = None
        self._start_pending_transition()
        self._rescale()
        self.update()

    def set_pair_image(self, slot, img):
        """Nuovo fotogramma per una delle due immagini affiancate (0 = prima, 1 = seconda)."""
        if img is None or img.isNull():
            return
        if slot == 0:
            self.image = img
            self._full = None
        elif self.image2 is not None:
            self.image2 = img
            self._full2 = None
        else:
            return
        if not self.gl and self.zoom is None and self.image2 is not None:
            half = max(1.0, (self.width() - self.GAP) / 2)
            pm = self._fit_pixmap(img, half, self.height())
            if slot == 0:
                self._scaled = pm
            else:
                self._scaled2 = pm
        self.update()

    def set_message(self, text):
        self.image = None
        self.image2 = None
        self._scaled = self._scaled2 = self._full = self._full2 = None
        self.message = text
        self._snap = None
        self.trans = None
        self.kb = None
        self.update()

    def flash(self, text, ms=1600, kind="msg"):
        if kind == "folder" and not self.style_["osd/folder"]:
            return
        if kind == "msg" and not self.style_["osd/messages"]:
            return
        self.osd = text
        self.osd_kind = kind
        self._osd_timer.start(ms)
        self.update()

    def _clear_osd(self):
        self.osd = ""
        self.update()

    # ------------------------------------------------------------ geometria
    def _fit_factor(self, img, w_avail, h_avail, mode="fit"):
        dpr = self.devicePixelRatioF()
        sw = w_avail * dpr / img.width()
        sh = h_avail * dpr / img.height()
        if mode == "width":
            return sw
        if mode == "height":
            return sh
        if mode == "fill":
            return max(sw, sh)
        s = min(sw, sh)
        return s if self.enlarge else min(s, 1.0)

    def fit_scale(self):
        if self.image is None or self.image.isNull():
            return 1.0
        return self._fit_factor(self.image, self.width(), self.height(), self.fit_mode)

    def current_scale(self):
        return self.fit_scale() if self.zoom is None else self.zoom

    def _content_size(self):
        dpr = self.devicePixelRatioF()
        s = self.current_scale()
        return self.image.width() * s / dpr, self.image.height() * s / dpr

    def _zoom_size(self):
        return self._content_size()

    def _scrollable(self):
        return self.image is not None and self.image2 is None and \
            (self.zoom is not None or self.fit_mode != "fit")

    def _clamp(self):
        if not self._scrollable():
            return
        w, h = self._content_size()
        mx = max(0.0, (w - self.width()) / 2)
        my = max(0.0, (h - self.height()) / 2)
        self.offset = QPointF(max(-mx, min(mx, self.offset.x())),
                              max(-my, min(my, self.offset.y())))

    def _align_start(self):
        """In "adatta alla larghezza" una pagina lunga parte dall'alto (in manga da destra)."""
        if self.image is None or self.zoom is not None or self.fit_mode == "fit" or self.image2 is not None:
            return
        w, h = self._content_size()
        mx = max(0.0, (w - self.width()) / 2)
        my = max(0.0, (h - self.height()) / 2)
        self.offset = QPointF(-mx if self.rtl else mx, my)

    def scroll_by(self, dx, dy):
        """Sposta la vista; False se si era già al bordo in quella direzione."""
        if not self._scrollable():
            return False
        before = QPointF(self.offset)
        self.offset = self.offset + QPointF(dx, dy)
        self._clamp()
        moved = (self.offset - before).manhattanLength() > 0.5
        if moved:
            self.update()
        return moved

    def at_edge(self, d):
        """True se la vista è in fondo (d>0) o in cima (d<0)."""
        if not self._scrollable():
            return True
        w, h = self._content_size()
        my = max(0.0, (h - self.height()) / 2)
        return self.offset.y() <= -my + 0.5 if d > 0 else self.offset.y() >= my - 0.5

    def scroll_to_end(self, bottom):
        if self._scrollable():
            w, h = self._content_size()
            my = max(0.0, (h - self.height()) / 2)
            self.offset = QPointF(self.offset.x(), -my if bottom else my)
            self.update()

    def _layout(self):
        """[(immagine, rettangolo in coordinate logiche)] da disegnare."""
        img = self.image
        if img is None or img.isNull():
            return []
        W, H = self.width(), self.height()
        dpr = self.devicePixelRatioF()
        if self.image2 is not None:
            half = max(1.0, (W - self.GAP) / 2)
            sizes = []
            for im in (self.image, self.image2):
                s = self._fit_factor(im, half, H)
                sizes.append((im, im.width() * s / dpr, im.height() * s / dpr))
            left, right = (sizes[1], sizes[0]) if self.rtl else (sizes[0], sizes[1])
            mid = W / 2
            items = [(left[0], QRectF(mid - self.GAP / 2 - left[1], (H - left[2]) / 2, left[1], left[2])),
                     (right[0], QRectF(mid + self.GAP / 2, (H - right[2]) / 2, right[1], right[2]))]
        else:
            w, h = self._content_size()
            r = QRectF((W - w) / 2 + self.offset.x(), (H - h) / 2 + self.offset.y(), w, h)
            if self.kb is not None and self.zoom is None and self.fit_mode == "fit":
                f = 1.0 + self.kb["amount"] * self._kb_t()
                nw, nh = w * f, h * f
                r = QRectF(r.x() - (nw - w) * self.kb["ax"], r.y() - (nh - h) * self.kb["ay"], nw, nh)
            items = [(img, r)]
        if self.trans is not None and self.trans["kind"] == "slide":
            dx = (1.0 - self._trans_t()) * W * self.trans["dir"]
            items = [(im, r.translated(dx, 0)) for im, r in items]
        return items

    def _fit_pixmap(self, img, w_avail, h_avail, mode="fit"):
        dpr = self.devicePixelRatioF()
        s = self._fit_factor(img, w_avail, h_avail, mode)
        w, h = max(1, round(img.width() * s)), max(1, round(img.height() * s))
        if w * h > MAX_PRESCALE:
            return None
        if (w, h) == (img.width(), img.height()):
            pm = QPixmap.fromImage(img)
        else:
            pm = QPixmap.fromImage(img.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        return pm

    def _rescale(self):
        self._scaled = None
        self._scaled2 = None
        if self.gl:     # con OpenGL ridimensiona la GPU al momento del disegno
            return
        if self.image is None or self.image.isNull() or self.zoom is not None:
            return
        if self.image2 is not None:
            half = max(1.0, (self.width() - self.GAP) / 2)
            self._scaled = self._fit_pixmap(self.image, half, self.height())
            self._scaled2 = self._fit_pixmap(self.image2, half, self.height())
            return
        self._scaled = self._fit_pixmap(self.image, self.width(), self.height(), self.fit_mode)

    def set_zoom(self, z):
        if self.image is None or self.image2 is not None:
            return
        self.kb = None
        if z is None:
            self.zoom = None
            self.offset = QPointF(0, 0)
            self._align_start()
            self._rescale()
        else:
            self.zoom = max(0.05, min(z, 16.0))
            self._clamp()
        self.flash(fit_mode_name(self.fit_mode) if self.zoom is None else f"Zoom {self.zoom * 100:.0f}%")
        self.update()

    def set_fit_mode(self, mode):
        self.fit_mode = mode if mode in FIT_MODES else "fit"
        self.zoom = None
        self.kb = None
        self.offset = QPointF(0, 0)
        self._align_start()
        self._rescale()
        self._clamp()
        self.update()

    # ----------------------------------------------------------- transizioni
    def prepare_transition(self, kind, ms=600, direction=1):
        """Fotografa la schermata attuale: la transizione parte con la prossima immagine."""
        if kind in (None, "none") or self.image is None or self.message:
            self._snap = None
            return
        try:
            self._snap = self.grabFramebuffer() if self.gl else self.grab().toImage()
        except Exception:  # noqa: BLE001
            self._snap = None
            return
        self._snap_kind = ("fade" if kind == "kenburns" else kind, max(50, int(ms)), direction)

    def _start_pending_transition(self):
        if self._snap is None:
            return
        kind, ms, d = self._snap_kind
        self.trans = {"kind": kind, "start": time.monotonic(), "ms": ms, "dir": d, "snap": self._snap}
        self._snap = None
        self._anim_timer.start()

    def _trans_t(self):
        if self.trans is None:
            return 1.0
        t = (time.monotonic() - self.trans["start"]) * 1000 / self.trans["ms"]
        t = max(0.0, min(1.0, t))
        return t * t * (3 - 2 * t)      # partenza e arrivo morbidi

    def start_kenburns(self, seconds, amount=0.12):
        """Zoom lento per la durata dell'immagine, verso un punto a caso."""
        if self.image is None or self.image2 is not None or self.zoom is not None or self.fit_mode != "fit":
            self.kb = None
            return
        self.kb = {"start": time.monotonic(), "dur": max(1.0, seconds), "amount": amount,
                   "ax": random.uniform(0.2, 0.8), "ay": random.uniform(0.2, 0.8), "frozen": None}
        self._anim_timer.start()

    def freeze_kenburns(self, frozen=True):
        if self.kb is None:
            return
        if frozen and self.kb["frozen"] is None:
            self.kb["frozen"] = self._kb_t()
        elif not frozen and self.kb["frozen"] is not None:
            # riparte da dove si era fermato
            self.kb["start"] = time.monotonic() - self.kb["frozen"] * self.kb["dur"]
            self.kb["frozen"] = None
            self._anim_timer.start()

    def _kb_t(self):
        if self.kb is None:
            return 0.0
        if self.kb["frozen"] is not None:
            return self.kb["frozen"]
        return max(0.0, min(1.0, (time.monotonic() - self.kb["start"]) / self.kb["dur"]))

    def _anim_tick(self):
        busy = False
        if self.trans is not None:
            if self._trans_t() >= 1.0:
                self.trans = None
            else:
                busy = True
        if self.kb is not None and self.kb["frozen"] is None and self._kb_t() < 1.0:
            busy = True
        if not busy:
            self._anim_timer.stop()
        self.update()

    # -------------------------------------------------------------- eventi
    def resizeEvent(self, e):
        self._rescale()
        self._clamp()
        super().resizeEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._scrollable():
            self._drag = (e.position(), QPointF(self.offset))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self.mouse = e.position()
        if self._drag:
            start, off = self._drag
            self.offset = off + (e.position() - start)
            self._clamp()
            self.update()
        elif self.loupe or self.show_pixel:
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.unsetCursor()
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        self.mouse = None
        if self.loupe or self.show_pixel:
            self.update()
        super().leaveEvent(e)

    # --------------------------------------------------------------- disegno
    def _bg_color(self):
        return {"black": QColor(0, 0, 0), "gray": QColor(64, 64, 66),
                "white": QColor(242, 242, 242)}.get(self.background, QColor(0, 0, 0))

    def _fill_bg(self, p):
        if self.background == "checker":
            if self._checker is None:
                self._checker = _checker_brush()
            p.fillRect(self.rect(), self._checker)
        else:
            p.fillRect(self.rect(), self._bg_color())

    def _text_color(self):
        return QColor(40, 40, 40) if self.background in ("white", "checker") else QColor(200, 200, 200)

    def _paint_cpu_images(self, p, items):
        for img, r in items:
            pm = None
            if self.zoom is None:
                cand = self._scaled if img is self.image else self._scaled2 if img is self.image2 else None
                if cand is not None:
                    pm = cand
            if pm is not None and abs(pm.width() / pm.devicePixelRatio() - r.width()) < 1.0:
                p.drawPixmap(QPointF(round(r.x()), round(r.y())), pm)
                continue
            if pm is not None:      # Ken Burns: la copia ridotta, leggermente ingrandita
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
                p.drawPixmap(r, pm, QRectF(pm.rect()))
                continue
            if img is self.image:
                if self._full is None:
                    self._full = QPixmap.fromImage(img)
                full = self._full
            else:
                if self._full2 is None:
                    self._full2 = QPixmap.fromImage(img)
                full = self._full2
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                            r.width() / max(1, img.width()) * self.devicePixelRatioF() < 2)
            p.drawPixmap(r, full, QRectF(full.rect()))

    def _paint_transition(self, p):
        """Schermata precedente sopra quella nuova, sempre più trasparente / che scorre via."""
        if self.trans is None:
            return
        t = self._trans_t()
        snap = self.trans["snap"]
        target = QRectF(0, 0, self.width(), self.height())
        if self.trans["kind"] == "fade":
            p.setOpacity(1.0 - t)
            p.drawImage(target, snap)
            p.setOpacity(1.0)
        elif self.trans["kind"] == "slide":
            p.drawImage(target.translated(-t * self.width() * self.trans["dir"], 0), snap)

    def _image_at(self, pos):
        for img, r in self._layout():
            if r.contains(pos):
                return img, r
        return None, None

    def _paint_loupe(self, p):
        if not self.loupe or self.mouse is None:
            return
        img, r = self._image_at(self.mouse)
        if img is None:
            return
        R = 120.0
        disp = r.width() / img.width()                  # pixel logici per pixel dell'immagine
        sx = (self.mouse.x() - r.x()) / disp
        sy = (self.mouse.y() - r.y()) / disp
        half = R / (disp * self.loupe_mag)
        target = QRectF(self.mouse.x() - R, self.mouse.y() - R, 2 * R, 2 * R)
        path = QPainterPath()
        path.addEllipse(target)
        p.save()
        p.setClipPath(path)
        self._fill_bg(p) if self.background != "checker" else p.fillRect(target, QColor(40, 40, 40))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, disp * self.loupe_mag < 2)
        p.drawImage(target, img, QRectF(sx - half, sy - half, 2 * half, 2 * half))
        p.restore()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 200), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(target)
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(target.x(), target.bottom() - 26, target.width(), 20),
                   Qt.AlignmentFlag.AlignCenter, f"×{self.loupe_mag:.3g}")

    def _paint_pixel(self, p):
        if not self.show_pixel or self.mouse is None:
            return
        img, r = self._image_at(self.mouse)
        if img is None:
            return
        x = int((self.mouse.x() - r.x()) / r.width() * img.width())
        y = int((self.mouse.y() - r.y()) / r.height() * img.height())
        if not (0 <= x < img.width() and 0 <= y < img.height()):
            return
        c = img.pixelColor(x, y)
        txt = f"X {x}  Y {y}    RGB {c.red()}, {c.green()}, {c.blue()}    {c.name().upper()}"
        if c.alpha() < 255:
            txt += f"    A {c.alpha()}"
        f = QFont(self.font())
        f.setPointSize(10)
        p.setFont(f)
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(txt) + 54, fm.height() + 18
        box = QRectF(self.width() - w - 12, self.height() - h - 12, w, h)
        path = QPainterPath()
        path.addRoundedRect(box, 8, 8)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(path, QColor(0, 0, 0, 180))
        sw = QRectF(box.x() + 10, box.y() + 9, h - 18, h - 18)
        p.fillRect(sw, c)
        p.setPen(QColor(255, 255, 255, 160))
        p.drawRect(sw)
        p.setPen(QColor(235, 235, 235))
        p.drawText(QRectF(sw.right() + 10, box.y(), w, h), Qt.AlignmentFlag.AlignVCenter, txt)

    def _paint_hist(self, p):
        if not self.show_hist or self.image is None or self.image.isNull():
            return
        k = self.image.cacheKey()
        if self._hist is None or self._hist[0] != k:
            self._hist = (k, histogram(self.image))
        data = self._hist[1]
        box = QRectF(12, 12, 276, 132)
        path = QPainterPath()
        path.addRoundedRect(box, 8, 8)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(path, QColor(0, 0, 0, 185))
        top = max(1, max(max(ch[1:255]) for ch in data))
        inner = box.adjusted(10, 10, -10, -10)
        for ch, col in zip(data, (QColor(255, 70, 70, 150), QColor(70, 220, 90, 150),
                                  QColor(80, 140, 255, 150), QColor(235, 235, 235, 200))):
            pp = QPainterPath()
            pp.moveTo(inner.left(), inner.bottom())
            for i, v in enumerate(ch):
                pp.lineTo(inner.left() + i / 255 * inner.width(),
                          inner.bottom() - min(1.0, v / top) * inner.height())
            pp.lineTo(inner.right(), inner.bottom())
            p.setPen(QPen(col, 1))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 40))
            p.drawPath(pp)

    def _paint_overlays(self, p):
        self._paint_transition(p)
        self._paint_loupe(p)
        self._paint_hist(p)
        self._paint_pixel(p)
        if self.message:
            p.setPen(self._text_color())
            f = QFont(self.font())
            f.setPointSize(14)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
        if self.show_info and self.info_lines:
            self._draw_box(p, self.info_lines, "info")
        if self.paused and self.badge_on and self.style_["osd/pause_badge"]:
            self._draw_box(p, ["❚❚  " + tr("In pausa")], "badge")
        if self.osd:
            pos = self.style_["osd/folder_pos"] if self.osd_kind == "folder" else "top"
            self._draw_box(p, [self.osd], pos, big=True)

    def release_gpu(self):
        """Libera la memoria della scheda video (il canvas CPU non ne usa)."""

    def _draw_box(self, p, lines, where, big=False):
        st = self.style_
        f = QFont(self.font())
        size = int(st["osd/size"])
        f.setPointSize(size if big else max(8, round(size * 0.67)))
        if big:
            f.setBold(True)
        p.setFont(f)
        fm = p.fontMetrics()
        pad = 10
        lh = fm.height()
        w = max(fm.horizontalAdvance(l) for l in lines) + pad * 2 + 6
        w = min(w, self.width() - 20)
        h = lh * len(lines) + pad * 2
        if where == "info":
            x, y = 12, self.height() - h - 12
        elif where == "badge":
            x, y = self.width() - w - 12, 12
        else:
            x = (self.width() - w) / 2
            y = {"top": 24, "center": (self.height() - h) / 2}.get(where, self.height() - h - 70)
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, h), 8, 8)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bg = QColor(st["osd/bg"])
        bg.setAlpha(round(int(st["osd/bg_alpha"]) * 2.55))
        p.fillPath(path, bg)
        p.setPen(QColor(st["osd/color"]))
        for i, l in enumerate(lines):
            t = fm.elidedText(l, Qt.TextElideMode.ElideMiddle, int(w - pad * 2))
            p.drawText(QPointF(x + pad, y + pad + fm.ascent() + i * lh), t)


class Canvas(_CanvasLogic, QWidget):
    """Canvas disegnato dalla CPU."""

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._init_canvas()

    def paintEvent(self, e):
        p = QPainter(self)
        self._fill_bg(p)
        self._paint_cpu_images(p, self._layout())
        self._paint_overlays(p)
        p.end()


try:
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
except ImportError:  # pragma: no cover
    QOpenGLWidget = None

if QOpenGLWidget is not None:
    class GLCanvas(_CanvasLogic, QOpenGLWidget):
        """Canvas disegnato dalla GPU."""

        gl = True

        def __init__(self, parent=None):
            QOpenGLWidget.__init__(self, parent)
            self._renderer = None
            self._init_canvas()

        def initializeGL(self):
            self.context().aboutToBeDestroyed.connect(self._cleanup)
            self._renderer = gpu.TextureRenderer()
            if not self._renderer.ok:
                self._renderer = None       # si disegna con QPainter (che usa comunque la GPU)

        def _cleanup(self):
            if self._renderer is not None and self.context() is not None:
                self.makeCurrent()
                self._renderer.destroy()
                self._renderer = None
                self.doneCurrent()

        def release_gpu(self):
            self._cleanup()

        def paintGL(self):
            p = QPainter(self)
            self._fill_bg(p)
            dpr = self.devicePixelRatioF()
            vw = max(1, round(self.width() * dpr))
            vh = max(1, round(self.height() * dpr))
            items = self._layout()
            if self._renderer is not None and items:
                p.beginNativePainting()
                f = self.context().functions()
                f.glViewport(0, 0, vw, vh)
                f.glEnable(gpu.GL_BLEND)
                f.glBlendFunc(gpu.GL_ONE, gpu.GL_ONE_MINUS_SRC_ALPHA)
                for img, r in items:
                    smooth = r.width() / max(1, img.width()) * dpr < 2
                    dr = QRectF(round(r.x() * dpr), round(r.y() * dpr),
                                round(r.width() * dpr), round(r.height() * dpr))
                    self._renderer.draw(f, img, dr, vw, vh, smooth)
                f.glDisable(gpu.GL_BLEND)
                p.endNativePainting()
            else:
                for img, r in items:
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,
                                    r.width() / max(1, img.width()) * dpr < 2)
                    p.drawImage(r, img)
            self._paint_overlays(p)
            p.end()
else:
    GLCanvas = Canvas
