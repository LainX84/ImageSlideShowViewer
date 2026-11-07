"""Visualizzatore a schermo intero con slideshow."""
import os
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QImageReader, QMovie,
                           QPainter, QPainterPath, QPixmap)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox, QToolButton,
                               QVBoxLayout, QWidget)

from .archive import is_virtual, parent_of, stat_any
from . import APP_NAME
from .i18n import num, tr
from .utils import human_size

INTERVALS = [0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 45, 60, 120]


def is_animated(path):
    if is_virtual(path) or os.path.splitext(path)[1].lower() not in (".gif", ".webp"):
        return False
    r = QImageReader(path)
    return r.supportsAnimation() and r.imageCount() > 1


class Canvas(QWidget):
    """Disegna l'immagine (adatta alla finestra o zoom) e le scritte in sovrimpressione."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self.image = None
        self._scaled = None
        self._full = None
        self.zoom = None  # None = adatta alla finestra
        self.enlarge = False
        self.offset = QPointF(0, 0)
        self._drag = None
        self.message = ""
        self.info_lines = []
        self.show_info = False
        self.osd = ""
        self.osd_kind = "msg"
        self.paused = False
        from .options import DEFAULTS
        self.style_ = dict(DEFAULTS)
        self._osd_timer = QTimer(self, singleShot=True, interval=1600)
        self._osd_timer.timeout.connect(self._clear_osd)

    # --------------------------------------------------------------- stato
    def set_image(self, img, keep_view=False):
        self.image = img
        self.message = ""
        self._full = None
        if not keep_view:
            self.offset = QPointF(0, 0)
            self.zoom = None
        self._rescale()
        self.update()

    def set_message(self, text):
        self.image = None
        self._scaled = self._full = None
        self.message = text
        self.update()

    def flash(self, text, ms=1600, kind="msg"):
        """kind: 'folder' (nome cartella) o 'msg' (altri avvisi); ognuno disattivabile."""
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

    def fit_scale(self):
        if self.image is None or self.image.isNull():
            return 1.0
        dpr = self.devicePixelRatioF()
        s = min(self.width() * dpr / self.image.width(),
                self.height() * dpr / self.image.height())
        return s if self.enlarge else min(s, 1.0)

    def _rescale(self):
        self._scaled = None
        if self.image is None or self.image.isNull() or self.zoom is not None:
            return
        s = self.fit_scale()
        dpr = self.devicePixelRatioF()
        w = max(1, round(self.image.width() * s))
        h = max(1, round(self.image.height() * s))
        if (w, h) == (self.image.width(), self.image.height()):
            pm = QPixmap.fromImage(self.image)
        else:
            pm = QPixmap.fromImage(self.image.scaled(
                w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
        pm.setDevicePixelRatio(dpr)
        self._scaled = pm

    def set_zoom(self, z):
        if self.image is None:
            return
        if z is None:
            self.zoom = None
            self.offset = QPointF(0, 0)
            self._rescale()
        else:
            self.zoom = max(0.05, min(z, 16.0))
            self._clamp()
        self.flash(tr("Adatta alla finestra") if self.zoom is None else f"Zoom {self.zoom * 100:.0f}%")
        self.update()

    def current_scale(self):
        return self.fit_scale() if self.zoom is None else self.zoom

    def _zoom_size(self):
        dpr = self.devicePixelRatioF()
        return (self.image.width() * self.zoom / dpr, self.image.height() * self.zoom / dpr)

    def _clamp(self):
        if self.image is None or self.zoom is None:
            return
        w, h = self._zoom_size()
        mx = max(0.0, (w - self.width()) / 2)
        my = max(0.0, (h - self.height()) / 2)
        self.offset = QPointF(max(-mx, min(mx, self.offset.x())),
                              max(-my, min(my, self.offset.y())))

    # ------------------------------------------------------------- eventi
    def resizeEvent(self, e):
        self._rescale()
        self._clamp()
        super().resizeEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.zoom is not None:
            self._drag = (e.position(), QPointF(self.offset))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag:
            start, off = self._drag
            self.offset = off + (e.position() - start)
            self._clamp()
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = None
            self.unsetCursor()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0))
        W, H = self.width(), self.height()
        if self.image is not None and not self.image.isNull():
            if self.zoom is None and self._scaled is not None:
                dpr = self._scaled.devicePixelRatio()
                w, h = self._scaled.width() / dpr, self._scaled.height() / dpr
                p.drawPixmap(QPointF((W - w) / 2, (H - h) / 2), self._scaled)
            elif self.zoom is not None:
                if self._full is None:
                    self._full = QPixmap.fromImage(self.image)
                w, h = self._zoom_size()
                x = (W - w) / 2 + self.offset.x()
                y = (H - h) / 2 + self.offset.y()
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 2)
                p.drawPixmap(QRectF(x, y, w, h), self._full, QRectF(self._full.rect()))
        if self.message:
            p.setPen(QColor(200, 200, 200))
            f = QFont(self.font())
            f.setPointSize(14)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.message)
        if self.show_info and self.info_lines:
            self._draw_box(p, self.info_lines, "info")
        if self.paused and self.style_["osd/pause_badge"]:
            self._draw_box(p, ["❚❚  " + tr("In pausa")], "badge")
        if self.osd:
            pos = self.style_["osd/folder_pos"] if self.osd_kind == "folder" else "top"
            self._draw_box(p, [self.osd], pos, big=True)
        p.end()

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


class ControlBar(QFrame):
    """Barra comandi semitrasparente che compare muovendo il mouse."""

    def __init__(self, viewer):
        super().__init__(viewer)
        self.v = viewer
        self.setObjectName("bar")
        self.setStyleSheet(
            "#bar { background: rgba(20,20,22,210); border-radius: 10px; }"
            "QToolButton { color: #eee; background: transparent; border: none;"
            " padding: 6px 10px; font-size: 11pt; border-radius: 6px; }"
            "QToolButton:hover { background: rgba(255,255,255,40); }"
            "QLabel { color: #ccc; font-size: 10pt; padding: 0 4px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(2)

        def btn(text, tip, slot):
            b = QToolButton(self)
            b.setText(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        btn("↑ " + tr("Cartella"), tr("Cartella precedente (↑)"), lambda: viewer.go_folder(-1))
        btn("◀", tr("Immagine precedente (←)"), lambda: viewer.go(-1))
        self.play = btn("", tr("Avvia / ferma lo slideshow (Spazio)"), viewer.toggle_play)
        btn("▶", tr("Immagine successiva (→)"), lambda: viewer.go(1))
        btn(tr("Cartella") + " ↓", tr("Cartella successiva (↓)"), lambda: viewer.go_folder(1))
        lay.addSpacing(10)
        btn("−", tr("Intervallo più corto (−)"), lambda: viewer.change_interval(-1))
        self.interval = QLabel(self)
        lay.addWidget(self.interval)
        btn("+", tr("Intervallo più lungo (+)"), lambda: viewer.change_interval(1))
        lay.addSpacing(10)
        btn(tr("Opzioni"), tr("Avvisi, colori, barra comandi (O)"), viewer.open_options)
        btn("✕", tr("Chiudi (Esc)"), viewer.close)
        self.hide()

    def refresh(self):
        self.play.setText("❚❚ " + tr("Ferma") if self.v.playing else "▶ " + tr("Avvia"))
        self.interval.setText(self.v._fmt_interval())
        self.adjustSize()
        self.place()

    def place(self):
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 16)


class ViewerWindow(QWidget):
    to_browser = Signal(str)
    closed = Signal(str)
    files_changed = Signal(str)  # cartella modificata

    def __init__(self, nav, loader, settings, slideshow=False, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(QSize(400, 300))
        self.nav = nav
        self.loader = loader
        self.settings = settings
        self.playing = slideshow
        self.slideshow_mode = slideshow
        self.started_as_slideshow = slideshow
        self.interval = float(settings.value("slideshow/interval", 4.0, type=float))
        self.canvas = Canvas(self)
        self.canvas.show_info = settings.value("viewer/show_info", False, type=bool)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.bar = ControlBar(self)
        self.bar_timer = QTimer(self, singleShot=True, interval=2500)
        self.bar_timer.timeout.connect(self._hide_bar)
        self.apply_options()
        self.movie = None
        self._shown_path = None
        self._was_maximized = True

        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._auto_next)
        self.cursor_timer = QTimer(self, singleShot=True, interval=2000)
        self.cursor_timer.timeout.connect(self._hide_cursor)
        self.setMouseTracking(True)
        self.canvas.installEventFilter(self)

        loader.ready.connect(self._on_ready)
        QTimer.singleShot(0, self._start)

    def _start(self):
        self._show_current()
        if self.playing:
            pos = self.nav.folder_position()
            extra = "  ·  " + tr("{n} cartelle", n=pos[1]) if pos else ""
            self.canvas.flash(f"▶ Slideshow  ·  {self._fmt_interval()}{extra}", 2000)

    # ------------------------------------------------------------ immagini
    def _stop_movie(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None

    def _show_current(self):
        self.timer.stop()
        self._stop_movie()
        path = self.nav.current()
        self._shown_path = path
        if not path:
            self.canvas.set_message(tr("Nessuna immagine in questa cartella\n\n"
                                       "↓ / ↑  per cambiare cartella   ·   Esc per uscire"))
            self.setWindowTitle(f"{os.path.basename(self.nav.folder)} - {APP_NAME}")
            self._update_info()
            return
        self.setWindowTitle(f"{os.path.basename(path)} - {APP_NAME}")
        if is_animated(path):
            self.movie = QMovie(path, parent=self)
            self.movie.frameChanged.connect(self._on_frame)
            self.movie.start()
            self._update_info()
            self._after_display()
            return
        img = self.loader.get(path)
        err = self.loader.error(path)
        if img is not None:
            self._display(path, img)
        elif err:
            self._display_error(path, err)
        else:
            self.loader.request(path)
            self._update_info()

    def _on_frame(self, _n):
        if self.movie is not None:
            first = self.canvas.image is None or self.canvas.message
            self.canvas.set_image(self.movie.currentImage(), keep_view=not first)

    def _on_ready(self, path, img, err):
        if path != self._shown_path or self.movie is not None:
            return
        if err:
            self._display_error(path, err)
        else:
            self._display(path, img)

    def _display(self, path, img):
        self.canvas.set_image(img)
        self._update_info()
        self._after_display()

    def _display_error(self, path, err):
        self.canvas.set_message(tr("Impossibile aprire\n{name}\n\n{err}", name=os.path.basename(path), err=err))
        self._update_info()
        self._after_display()

    def _after_display(self):
        nxt = self.nav.peek(1)
        if nxt and not is_animated(nxt):
            self.loader.request(nxt, keep_wanted=True)
        if self.playing:
            self.timer.start(int(self.interval * 1000))

    def _update_info(self):
        path = self.nav.current()
        i, n = self.nav.position()
        lines = []
        if path:
            try:
                mt, sz = stat_any(path)
                size = human_size(sz)
                date = time.strftime(tr("%d/%m/%Y %H:%M"), time.localtime(mt))
            except OSError:
                size = date = "?"
            dims = ""
            img = self.canvas.image
            if img is not None and not img.isNull():
                dims = f"   {img.width()}×{img.height()}   {self.canvas.current_scale() * 100:.0f}%"
            lines.append(f"{os.path.basename(path)}   [{i}/{n}]{dims}   {size}   {date}")
        fpos = self.nav.folder_position()
        ftxt = tr("Cartella {i}/{n}: ", i=fpos[0], n=fpos[1]) if fpos else tr("Cartella: ")
        lines.append(ftxt + self.nav.folder)
        if self.slideshow_mode:
            state = "▶ " + tr("in corso") if self.playing else "❚❚ " + tr("in pausa")
            opts = []
            if self.nav.shuffle:
                opts.append(tr("casuale"))
            if self.nav.loop:
                opts.append(tr("ripeti"))
            if self.nav.include_sub:
                opts.append(tr("sottocartelle"))
            o = f"  ({', '.join(opts)})" if opts else ""
            lines.append(f"Slideshow {state} · {self._fmt_interval()}{o}")
        self.canvas.info_lines = lines
        self.canvas.paused = self.slideshow_mode and not self.playing
        if self.bar.isVisible():
            self.bar.refresh()
        self.canvas.update()

    # ---------------------------------------------------------- navigazione
    def go(self, d):
        if self.nav.step(d):
            self._show_current()
            if self.nav.folder_changed:
                self._flash_folder()
        else:
            self.canvas.flash(tr("Ultima immagine") if d > 0 else tr("Prima immagine"), 900)
            if self.playing:
                self.timer.start(int(self.interval * 1000))

    def go_folder(self, d):
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            moved = self.nav.jump_folder(d)
        finally:
            self.unsetCursor()
        if moved:
            self._show_current()
            self._flash_folder()
        else:
            self.canvas.flash(tr("Nessuna altra cartella con immagini"), 1200)

    def _flash_folder(self):
        name = os.path.basename(self.nav.folder) or self.nav.folder
        pos = self.nav.folder_position()
        p = f"  ({pos[0]}/{pos[1]})" if pos else ""
        self.canvas.flash(tr("Cartella: ") + f"{name}{p}", int(self.canvas.style_["osd/folder_ms"]), "folder")

    def _auto_next(self):
        if not self.playing:
            return
        if self.nav.step(1):
            self._show_current()
            if self.nav.folder_changed:
                self._flash_folder()
        else:
            self.playing = False
            self._update_info()
            self.canvas.flash(tr("Fine dello slideshow"), 3000)

    def toggle_play(self):
        self.set_playing(not self.playing)

    def set_playing(self, on):
        """Avvia (on=True) o ferma lo scorrimento automatico."""
        self.slideshow_mode = True
        self.playing = on
        if on:
            self.canvas.flash("▶ " + tr("Slideshow avviato") + f" · {self._fmt_interval()}")
            self.timer.start(int(self.interval * 1000))
        else:
            self.timer.stop()
            self.canvas.flash("❚❚ " + tr("Slideshow fermo"))
        self._update_info()

    def apply_options(self):
        from .options import load_style
        self.canvas.style_ = load_style(self.settings)
        if not self.canvas.style_["viewer/controls"]:
            self.bar.hide()
        self.canvas.update()

    def open_options(self):
        from .options import OptionsDialog
        was = self.playing
        self.timer.stop()
        self.unsetCursor()
        if OptionsDialog(self.settings, self).run():
            self.apply_options()
        if was:
            self.timer.start(int(self.interval * 1000))

    def _show_bar(self):
        if not self.canvas.style_["viewer/controls"]:
            return
        self.bar.refresh()
        self.bar.show()
        self.bar.raise_()
        self.bar_timer.start()

    def _hide_bar(self):
        if self.bar.underMouse():
            self.bar_timer.start()
        else:
            self.bar.hide()

    def _fmt_interval(self):
        return f"{num(self.interval)} s"

    def change_interval(self, d):
        cur = self.interval
        if d > 0:
            nxt = next((v for v in INTERVALS if v > cur + 1e-6), INTERVALS[-1])
        else:
            nxt = next((v for v in reversed(INTERVALS) if v < cur - 1e-6), INTERVALS[0])
        self.interval = nxt
        self.settings.setValue("slideshow/interval", nxt)
        self.canvas.flash(tr("Intervallo") + f": {self._fmt_interval()}")
        self._update_info()
        if self.playing:
            self.timer.start(int(self.interval * 1000))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self._was_maximized else self.showNormal()
            self.unsetCursor()
        else:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
            self.cursor_timer.start()

    def toggle_info(self):
        self.canvas.show_info = not self.canvas.show_info
        self.settings.setValue("viewer/show_info", self.canvas.show_info)
        self._update_info()

    def zoom_step(self, factor):
        if self.canvas.image is None:
            return
        self.canvas.set_zoom(self.canvas.current_scale() * factor)
        self._update_info()

    def toggle_zoom(self):
        self.canvas.set_zoom(None if self.canvas.zoom is not None else 1.0)
        self._update_info()

    def delete_current(self):
        path = self.nav.current()
        if not path:
            return
        if is_virtual(path):
            self.canvas.flash(tr("Le immagini dentro un archivio non si possono eliminare"), 2000)
            return
        was_playing = self.playing
        self.timer.stop()
        r = QMessageBox.question(self, tr("Elimina"),
                                 tr("Spostare nel Cestino?") + f"\n\n{os.path.basename(path)}")
        if r == QMessageBox.StandardButton.Yes:
            from .batch import move_to_trash
            if move_to_trash(path):
                self.loader.forget(path)
                self.nav.remove_current()
                self.files_changed.emit(parent_of(path))
                self._show_current()
                self.canvas.flash(tr("Spostata nel Cestino"), 1000)
                return
            QMessageBox.warning(self, tr("Elimina"), tr("Impossibile spostare il file nel Cestino."))
        if was_playing:
            self.timer.start(int(self.interval * 1000))

    def _toggle_folder_osd(self, on):
        self.settings.setValue("osd/folder", on)
        self.apply_options()

    def back_to_browser(self):
        self.to_browser.emit(self.nav.current() or self.nav.folder)
        self.close()

    # -------------------------------------------------------------- input
    def keyPressEvent(self, e):
        k = e.key()
        K = Qt.Key
        ctrl = bool(e.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if k == K.Key_Escape:
            self.close()
        elif k in (K.Key_Right, K.Key_PageDown) and ctrl:
            self.go_folder(1)
        elif k in (K.Key_Left, K.Key_PageUp) and ctrl:
            self.go_folder(-1)
        elif k in (K.Key_Right, K.Key_PageDown):
            self.go(1)
        elif k in (K.Key_Left, K.Key_PageUp, K.Key_Backspace):
            self.go(-1)
        elif k == K.Key_Down:
            self.go_folder(1)
        elif k == K.Key_Up:
            self.go_folder(-1)
        elif k == K.Key_Home:
            self.nav.first()
            self._show_current()
        elif k == K.Key_End:
            self.nav.last()
            self._show_current()
        elif k in (K.Key_Space, K.Key_P, K.Key_MediaTogglePlayPause, K.Key_MediaPlay):
            self.toggle_play()
        elif k in (K.Key_S, K.Key_MediaStop, K.Key_MediaPause):
            self.set_playing(False)
        elif k == K.Key_O:
            self.open_options()
        elif k in (K.Key_F, K.Key_F11):
            self.toggle_fullscreen()
        elif k in (K.Key_Return, K.Key_Enter):
            self.back_to_browser()
        elif k == K.Key_I:
            self.toggle_info()
        elif k in (K.Key_Asterisk, K.Key_Z, K.Key_0):
            self.toggle_zoom()
        elif k in (K.Key_Plus, K.Key_Equal):
            self.change_interval(1) if self.slideshow_mode and not ctrl else self.zoom_step(1.25)
        elif k == K.Key_Minus:
            self.change_interval(-1) if self.slideshow_mode and not ctrl else self.zoom_step(0.8)
        elif k == K.Key_Delete:
            self.delete_current()
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if not dy:
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_step(1.15 if dy > 0 else 1 / 1.15)
        else:
            self.go(-1 if dy > 0 else 1)

    def mouseDoubleClickEvent(self, e):
        self.toggle_fullscreen()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == ev.Type.MouseMove:
            if self.cursor().shape() == Qt.CursorShape.BlankCursor:
                self.unsetCursor()
            if self.isFullScreen():
                self.cursor_timer.start()
            self._show_bar()
        elif t == ev.Type.MouseButtonDblClick:
            self.toggle_fullscreen()
            return True
        elif t == ev.Type.ContextMenu:
            self._context_menu(ev.globalPos())
            return True
        return super().eventFilter(obj, ev)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.bar.isVisible():
            self.bar.place()

    def _hide_cursor(self):
        if self.bar.isVisible():
            self.cursor_timer.start()
            return
        if self.isFullScreen() and self.canvas._drag is None:
            self.setCursor(Qt.CursorShape.BlankCursor)

    def _context_menu(self, pos):
        m = QMenu(self)
        m.addAction(tr("Successiva  (→)"), lambda: self.go(1))
        m.addAction(tr("Precedente  (←)"), lambda: self.go(-1))
        m.addAction(tr("Cartella successiva  (↓)"), lambda: self.go_folder(1))
        m.addAction(tr("Cartella precedente  (↑)"), lambda: self.go_folder(-1))
        m.addSeparator()
        m.addAction(tr("Ferma slideshow  (Spazio)") if self.playing else tr("Avvia / riprendi slideshow  (Spazio)"),
                    self.toggle_play)
        m.addAction(tr("Intervallo più lungo  (+)"), lambda: self.change_interval(1))
        m.addAction(tr("Intervallo più corto  (−)"), lambda: self.change_interval(-1))
        m.addSeparator()
        m.addAction(tr("Adatta / 100%  (Z)"), self.toggle_zoom)
        m.addAction(tr("Schermo intero  (F)"), self.toggle_fullscreen)
        m.addAction(tr("Mostra informazioni  (I)"), self.toggle_info)
        a = m.addAction(tr("Mostra nome cartella al cambio"))
        a.setCheckable(True)
        a.setChecked(self.canvas.style_["osd/folder"])
        a.toggled.connect(self._toggle_folder_osd)
        m.addAction(tr("Opzioni avvisi e colori…  (O)"), self.open_options)
        m.addSeparator()
        m.addAction(tr("Elimina  (Canc)"), self.delete_current)
        m.addAction(tr("Torna al browser  (Invio)"), self.back_to_browser)
        m.addAction(tr("Chiudi  (Esc)"), self.close)
        m.exec(pos)

    def closeEvent(self, e):
        self.timer.stop()
        self._stop_movie()
        try:
            self.loader.ready.disconnect(self._on_ready)
        except (RuntimeError, TypeError):
            pass
        self.closed.emit(self.nav.current() or "")
        super().closeEvent(e)
