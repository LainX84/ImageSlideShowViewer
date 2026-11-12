"""Lettura verticale continua: le immagini della cartella (o dell'archivio) una sotto
l'altra, da scorrere come un webtoon o una striscia lunga.

Le immagini si caricano solo quando stanno per comparire; le dimensioni si leggono in
background, così si può iniziare a leggere subito.
Tasti: ↓ / ↑ e rotellina scorrono, Spazio / PagGiù una schermata, Home / Fine,
+ / − larghezza della colonna, F schermo intero, Esc chiude.
"""
from collections import OrderedDict

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from . import APP_NAME, codecs, library
from .archive import is_virtual, split
from .i18n import tr
from .loader import ImageLoader
from .worker import BgWorker

GAP = 0


def _size(path):
    return path, codecs.read_size(path)


class WebtoonView(QWidget):
    closed = Signal(str)

    def __init__(self, paths, start, settings, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("Lettura verticale – {app}", app=APP_NAME))
        self.setMouseTracking(True)
        self.paths = [p for p in paths if not codecs.is_video(p)]
        self.settings = settings
        self.pct = settings.value("webtoon/width", 70, type=int)
        self.sizes = {}             # percorso -> QSize
        self.y = 0.0                # posizione di scorrimento (pixel logici)
        self.loader = ImageLoader(cache_size=24, parent=self)
        self.loader.max_bytes = 600 * 1024 * 1024
        self.loader.ready.connect(lambda *_: self.update())
        self.scaled = OrderedDict()  # (percorso, larghezza) -> QPixmap
        self.worker = BgWorker(2, self)
        for p in self.paths:
            self.worker.submit(_size, self._sized, p)
        self._layout_cache = None
        self._pending_start = max(0, min(start, len(self.paths) - 1)) if self.paths else 0
        self._osd_timer = QTimer(self, singleShot=True, interval=1500)
        self._osd_timer.timeout.connect(self.update)
        self._osd = ""
        self._smooth = QTimer(self, interval=15)
        self._smooth.timeout.connect(self._smooth_step)
        self._target = None
        QTimer.singleShot(0, lambda: self.jump_to(self._pending_start))

    # ------------------------------------------------------------ geometria
    def col_width(self):
        return max(200, self.width() * self.pct / 100)

    def _height_of(self, p, w):
        s = self.sizes.get(p)
        if s is None or not s.isValid() or s.width() <= 0:
            return w * 1.45
        return w * s.height() / s.width()

    def _layout(self):
        w = self.col_width()
        key = (w, len(self.sizes))
        if self._layout_cache and self._layout_cache[0] == key:
            return self._layout_cache[1]
        tops, y = [], 0.0
        for p in self.paths:
            tops.append(y)
            y += self._height_of(p, w) + GAP
        self._layout_cache = (key, (tops, y))
        return tops, y

    def _anchor(self):
        """(indice, frazione) dell'immagine in alto: serve a non "saltare" quando cambiano
        le dimensioni o la larghezza."""
        tops, total = self._layout()
        if not tops:
            return 0, 0.0
        i = max(0, min(len(tops) - 1, self._index_at(self.y)))
        h = self._height_of(self.paths[i], self.col_width())
        return i, (self.y - tops[i]) / max(1.0, h)

    def _restore(self, anchor):
        i, f = anchor
        tops, _total = self._layout()
        if tops:
            self.y = tops[i] + f * self._height_of(self.paths[i], self.col_width())
        self._clamp()

    def _index_at(self, y):
        tops, _ = self._layout()
        lo, hi = 0, len(tops) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if tops[mid] <= y:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def _clamp(self):
        _tops, total = self._layout()
        self.y = max(0.0, min(self.y, max(0.0, total - self.height())))

    def current_index(self):
        return self._index_at(self.y + self.height() * 0.3) if self.paths else 0

    def jump_to(self, i):
        tops, _ = self._layout()
        if tops:
            self.y = tops[max(0, min(i, len(tops) - 1))]
            self._clamp()
        self.update()

    # ---------------------------------------------------------------- eventi
    def _sized(self, res):
        if isinstance(res, Exception):
            return
        p, s = res
        anchor = self._anchor()
        self.sizes[p] = s
        self._layout_cache = None
        self._restore(anchor)
        self.update()

    def scroll(self, dy, smooth=True):
        if smooth:
            self._target = (self._target if self._target is not None else self.y) + dy
            _t, total = self._layout()
            self._target = max(0.0, min(self._target, max(0.0, total - self.height())))
            self._smooth.start()
        else:
            self.y += dy
            self._clamp()
            self.update()

    def _smooth_step(self):
        if self._target is None:
            self._smooth.stop()
            return
        d = self._target - self.y
        if abs(d) < 1:
            self.y = self._target
            self._target = None
            self._smooth.stop()
        else:
            self.y += d * 0.25
        self.update()

    def set_width(self, pct):
        anchor = self._anchor()
        self.pct = max(30, min(100, pct))
        self.settings.setValue("webtoon/width", self.pct)
        self._layout_cache = None
        self.scaled.clear()
        self._restore(anchor)
        self._flash(tr("Larghezza: {n}%", n=self.pct))

    def _flash(self, text):
        self._osd = text
        self._osd_timer.start()
        self.update()

    def resizeEvent(self, e):
        anchor = self._anchor() if self._layout_cache else None
        self._layout_cache = None
        self.scaled.clear()
        if anchor:
            self._restore(anchor)
        super().resizeEvent(e)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_width(self.pct + (5 if dy > 0 else -5))
            return
        self.scroll(-dy * 1.2)

    def keyPressEvent(self, e):
        k = e.key()
        K = Qt.Key
        H = self.height()
        if k == K.Key_Escape:
            self.close()
        elif k in (K.Key_Down, K.Key_J):
            self.scroll(H * 0.15)
        elif k in (K.Key_Up, K.Key_K):
            self.scroll(-H * 0.15)
        elif k in (K.Key_Space, K.Key_PageDown):
            self.scroll(-H * 0.9 if e.modifiers() & Qt.KeyboardModifier.ShiftModifier else H * 0.9)
        elif k == K.Key_PageUp:
            self.scroll(-H * 0.9)
        elif k == K.Key_Home:
            self.jump_to(0)
        elif k == K.Key_End:
            _t, total = self._layout()
            self.y = total
            self._clamp()
            self.update()
        elif k in (K.Key_Right,):
            self.jump_to(self.current_index() + 1)
        elif k in (K.Key_Left,):
            self.jump_to(self.current_index() - 1)
        elif k in (K.Key_Plus, K.Key_Equal):
            self.set_width(self.pct + 5)
        elif k == K.Key_Minus:
            self.set_width(self.pct - 5)
        elif k in (K.Key_F, K.Key_F11):
            self.showMaximized() if self.isFullScreen() else self.showFullScreen()
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        self.showMaximized() if self.isFullScreen() else self.showFullScreen()

    # --------------------------------------------------------------- disegno
    def _pixmap(self, p, w, h):
        k = (p, int(w))
        pm = self.scaled.get(k)
        if pm is not None:
            self.scaled.move_to_end(k)
            return pm
        img = self.loader.get(p)
        if img is None:
            return None
        dpr = self.devicePixelRatioF()
        pm = QPixmap.fromImage(img.scaled(QSize(round(w * dpr), round(h * dpr)),
                                          Qt.AspectRatioMode.IgnoreAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        self.scaled[k] = pm
        while len(self.scaled) > 30:
            self.scaled.popitem(last=False)
        return pm

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(12, 12, 14))
        if not self.paths:
            p.setPen(QColor(200, 200, 200))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("Nessuna immagine"))
            return
        tops, _total = self._layout()
        w = self.col_width()
        x = (self.width() - w) / 2
        H = self.height()
        first = self._index_at(self.y)
        i = first
        wanted = []
        while i < len(self.paths) and tops[i] < self.y + H * 3:
            path = self.paths[i]
            h = self._height_of(path, w)
            top = tops[i] - self.y
            if top < H and top + h > 0:
                pm = self._pixmap(path, w, h)
                r = QRectF(x, top, w, h)
                if pm is not None:
                    p.drawPixmap(r.topLeft(), pm)
                else:
                    p.fillRect(r, QColor(28, 28, 30))
                    p.setPen(QColor(120, 120, 120))
                    p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{i + 1}")
            wanted.append(path)
            i += 1
        # carica le visibili per prime, poi qualche pagina prima e dopo
        for j in range(max(0, first - 2), first):
            wanted.append(self.paths[j])
        for k, path in enumerate(wanted):
            self.loader.request(path, keep_wanted=k > 0)
        cur = self.current_index()
        f = QFont(self.font())
        f.setPointSize(10)
        p.setFont(f)
        p.setPen(QColor(220, 220, 220))
        txt = f"{cur + 1} / {len(self.paths)}"
        if self._osd_timer.isActive() and self._osd:
            txt = self._osd + "    " + txt
        p.fillRect(QRectF(self.width() - 230, 8, 222, 24), QColor(0, 0, 0, 150))
        p.drawText(QRectF(self.width() - 226, 8, 214, 24), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)

    def closeEvent(self, e):
        cur = self.paths[self.current_index()] if self.paths else ""
        if cur and is_virtual(cur) and settings_resume(self.settings):
            a, m = split(cur)
            try:
                library.set_last_page(a, m, self.current_index() + 1, len(self.paths))
            except Exception:  # noqa: BLE001
                pass
        self.worker.shutdown()
        self.closed.emit(cur)
        super().closeEvent(e)


def settings_resume(settings):
    return settings.value("comics/resume", True, type=bool)


def start_index(paths, settings):
    """Per un archivio aperto dall'inizio: l'ultima pagina letta."""
    if not paths or not is_virtual(paths[0]) or not settings_resume(settings):
        return 0
    a, _m = split(paths[0])
    lp = library.last_page(a)
    if lp:
        target = a + "|" + lp[0]
        for i, p in enumerate(paths):
            if p == target:
                return i
    return 0
