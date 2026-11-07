"""Slideshow di 2 cartelle affiancate: a sinistra le immagini di una cartella, a destra
quelle di un'altra. Ogni lato scorre in automatico oppure solo a mano; quando un lato
arriva in fondo ricomincia dalla prima immagine (la cartella più corta va in loop).
Qui non c'è il salto cartella."""
import os
import random

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from . import APP_NAME
from .archive import is_archive
from .i18n import num, tr
from .utils import list_images
from .viewer import INTERVALS, Canvas

AUTO, MANUAL = "auto", "manual"


# ===================================================================== scelta
class DualDialog(QDialog):
    """Scelta delle due cartelle (o archivi CBZ/ZIP) e di come devono scorrere."""

    def __init__(self, settings, left="", right="", parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(tr("Slideshow di 2 cartelle affiancate"))
        self.setMinimumWidth(620)
        s = settings
        self.sides = []
        lay = QVBoxLayout(self)
        for key, title, start in (("left", tr("Cartella a sinistra"), left),
                                  ("right", tr("Cartella a destra"), right)):
            g = QGroupBox(title)
            f = QFormLayout(g)
            ed = QLineEdit(start or s.value(f"dual/{key}", ""))
            b_dir = QPushButton(tr("Cartella…"))
            b_arc = QPushButton(tr("Archivio…"))
            b_dir.clicked.connect(lambda _=False, e=ed: self._pick_dir(e))
            b_arc.clicked.connect(lambda _=False, e=ed: self._pick_archive(e))
            row = QHBoxLayout()
            row.addWidget(ed, 1)
            row.addWidget(b_dir)
            row.addWidget(b_arc)
            f.addRow(tr("Percorso:"), row)
            mode = QComboBox()
            mode.addItem(tr("Automatico (scorre con lo slideshow)"), AUTO)
            mode.addItem(tr("Manuale (solo con i tasti o il mouse)"), MANUAL)
            mode.setCurrentIndex(max(0, mode.findData(s.value(f"dual/{key}_mode", AUTO))))
            f.addRow(tr("Avanzamento:"), mode)
            lay.addWidget(g)
            self.sides.append((key, ed, mode))

        g = QGroupBox(tr("Slideshow"))
        f = QFormLayout(g)
        self.sp_interval = QDoubleSpinBox(minimum=0.5, maximum=600, singleStep=0.5, decimals=1)
        self.sp_interval.setSuffix(" s")
        self.sp_interval.setValue(s.value("slideshow/interval", 4.0, type=float))
        self.ck_paused = QCheckBox(tr("Parti fermo (avvia con Spazio)"))
        self.ck_paused.setChecked(s.value("dual/paused", False, type=bool))
        self.ck_random = QCheckBox(tr("Ordine casuale"))
        self.ck_random.setChecked(s.value("dual/random", False, type=bool))
        f.addRow(tr("Intervallo:"), self.sp_interval)
        f.addRow("", self.ck_paused)
        f.addRow("", self.ck_random)
        lay.addWidget(g)
        hint = QLabel(tr("Quando una cartella ha meno immagini dell'altra ricomincia dalla prima. "
                         "Tasti: → ← entrambe · Q / W sinistra · O / P destra · clic su un lato = "
                         "avanti su quel lato · Spazio avvia/ferma."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray")
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Avvia"))
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick_dir(self, ed):
        d = QFileDialog.getExistingDirectory(self, tr("Scegli la cartella"), ed.text())
        if d:
            ed.setText(os.path.normpath(d))

    def _pick_archive(self, ed):
        f, _ = QFileDialog.getOpenFileName(self, tr("Scegli l'archivio"), os.path.dirname(ed.text()),
                                           tr("Archivi") + " (*.cbz *.zip)")
        if f:
            ed.setText(os.path.normpath(f))

    def _ok(self):
        for _key, ed, _m in self.sides:
            p = ed.text().strip().strip('"')
            if not (os.path.isdir(p) or (is_archive(p) and os.path.isfile(p))):
                QMessageBox.warning(self, APP_NAME, tr("Cartella non trovata o non accessibile:\n{path}", path=p))
                return
        self.accept()

    def values(self):
        s = self.settings
        out = []
        for key, ed, mode in self.sides:
            p = ed.text().strip().strip('"')
            s.setValue(f"dual/{key}", p)
            s.setValue(f"dual/{key}_mode", mode.currentData())
            out.append((p, mode.currentData()))
        s.setValue("slideshow/interval", self.sp_interval.value())
        s.setValue("dual/paused", self.ck_paused.isChecked())
        s.setValue("dual/random", self.ck_random.isChecked())
        return out, self.sp_interval.value(), self.ck_paused.isChecked(), self.ck_random.isChecked()


# ==================================================================== finestra
class Side:
    def __init__(self, folder, mode, images, canvas):
        self.folder, self.mode, self.images, self.canvas = folder, mode, images, canvas
        self.i = 0

    def current(self):
        return self.images[self.i] if self.images else None

    def peek(self, d=1):
        return self.images[(self.i + d) % len(self.images)] if self.images else None

    def step(self, d):
        if self.images:
            self.i = (self.i + d) % len(self.images)   # in fondo ricomincia dalla prima


class DualViewerWindow(QWidget):
    closed = Signal(str)

    def __init__(self, sides, loader, settings, interval, paused=False, shuffle=False, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("Slideshow di 2 cartelle affiancate") + f" - {APP_NAME}")
        self.setMinimumSize(QSize(600, 300))
        self.setStyleSheet("background: black;")
        self.loader, self.settings = loader, settings
        self.interval = interval
        self.playing = not paused
        self.started_as_slideshow = True
        sort = settings.value("browser/sort", "name")
        rev = settings.value("browser/sort_reverse", False, type=bool)
        from .options import load_style
        style = load_style(settings)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.sides = []
        for folder, mode in sides:
            c = Canvas(self)
            c.style_ = style
            c.show_info = settings.value("viewer/show_info", False, type=bool)
            c.installEventFilter(self)
            imgs = list_images(folder, sort, rev)
            if shuffle:
                random.shuffle(imgs)
            lay.addWidget(c, 1)
            self.sides.append(Side(folder, mode, imgs, c))
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._tick)
        self.cursor_timer = QTimer(self, singleShot=True, interval=2000)
        self.cursor_timer.timeout.connect(self._hide_cursor)
        self.setMouseTracking(True)
        loader.ready.connect(self._on_ready)
        QTimer.singleShot(0, self._start)

    # ------------------------------------------------------------ immagini
    def _start(self):
        for s in self.sides:
            self._show(s)
            name = os.path.basename(s.folder) or s.folder
            extra = "" if s.mode == AUTO else "  ·  " + tr("manuale")
            s.canvas.flash(tr("Cartella: ") + name + extra, 2500, "folder")
        self._restart_timer()

    def _show(self, s):
        path = s.current()
        if not path:
            s.canvas.set_message(tr("Nessuna immagine in questa cartella"))
            self._info(s)
            return
        img, err = self.loader.get(path), self.loader.error(path)
        if img is not None:
            s.canvas.set_image(img)
        elif err:
            s.canvas.set_message(tr("Impossibile aprire\n{name}\n\n{err}", name=os.path.basename(path), err=err))
        else:
            self.loader.request(path, keep_wanted=True)
        nxt = s.peek(1)
        if nxt and nxt != path:
            self.loader.request(nxt, keep_wanted=True)
        self._info(s)

    def _on_ready(self, path, img, err):
        for s in self.sides:
            if s.current() == path:
                if err:
                    s.canvas.set_message(tr("Impossibile aprire\n{name}\n\n{err}",
                                            name=os.path.basename(path), err=err))
                else:
                    s.canvas.set_image(img)
                self._info(s)

    def _info(self, s):
        path = s.current()
        lines = []
        if path:
            mode = tr("automatico") if s.mode == AUTO else tr("manuale")
            lines.append(f"{os.path.basename(path)}   [{s.i + 1}/{len(s.images)}]   {mode}")
        lines.append(tr("Cartella: ") + s.folder)
        if s is self.sides[0]:
            state = "▶ " + tr("in corso") if self.playing else "❚❚ " + tr("in pausa")
            lines.append(f"Slideshow {state} · {self._fmt_interval()}")
        s.canvas.info_lines = lines
        s.canvas.paused = not self.playing and s is self.sides[-1]
        s.canvas.update()

    # --------------------------------------------------------- movimento
    def advance(self, d, which=None):
        """which: None = entrambi i lati, altrimenti l'indice del lato."""
        targets = self.sides if which is None else [self.sides[which]]
        for s in targets:
            s.step(d)
            self._show(s)
        if self.playing:
            self._restart_timer()

    def _tick(self):
        if not self.playing:
            return
        for s in self.sides:
            if s.mode == AUTO:
                s.step(1)
                self._show(s)
        self._restart_timer()

    def _restart_timer(self):
        self.timer.stop()
        if self.playing and any(s.mode == AUTO for s in self.sides):
            self.timer.start(int(self.interval * 1000))

    def toggle_play(self):
        self.playing = not self.playing
        if self.playing and not any(s.mode == AUTO for s in self.sides):
            self.sides[0].canvas.flash(tr("Entrambi i lati sono in modalità manuale"), 2000)
        else:
            self.sides[0].canvas.flash("▶ " + tr("Slideshow avviato") if self.playing
                                       else "❚❚ " + tr("Slideshow fermo"))
        self._restart_timer()
        for s in self.sides:
            self._info(s)

    def toggle_mode(self, i):
        s = self.sides[i]
        s.mode = MANUAL if s.mode == AUTO else AUTO
        s.canvas.flash(tr("Avanzamento automatico") if s.mode == AUTO else tr("Avanzamento manuale"))
        self._info(s)
        self._restart_timer()

    def _fmt_interval(self):
        return f"{num(self.interval)} s"

    def change_interval(self, d):
        cur = self.interval
        if d > 0:
            self.interval = next((v for v in INTERVALS if v > cur + 1e-6), INTERVALS[-1])
        else:
            self.interval = next((v for v in reversed(INTERVALS) if v < cur - 1e-6), INTERVALS[0])
        self.settings.setValue("slideshow/interval", self.interval)
        self.sides[0].canvas.flash(tr("Intervallo") + f": {self._fmt_interval()}")
        self._info(self.sides[0])
        self._restart_timer()

    def swap(self):
        self.sides.reverse()
        lay = self.layout()
        for s in self.sides:
            lay.removeWidget(s.canvas)
        for s in self.sides:
            lay.addWidget(s.canvas, 1)
        for s in self.sides:
            self._info(s)

    def apply_options(self):
        from .options import load_style
        st = load_style(self.settings)
        for s in self.sides:
            s.canvas.style_ = st
            s.canvas.update()

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
            self.unsetCursor()
        else:
            self.showFullScreen()
            self.cursor_timer.start()

    def toggle_info(self):
        on = not self.sides[0].canvas.show_info
        self.settings.setValue("viewer/show_info", on)
        for s in self.sides:
            s.canvas.show_info = on
            self._info(s)

    # -------------------------------------------------------------- input
    def keyPressEvent(self, e):
        k, K = e.key(), Qt.Key
        if k == K.Key_Escape:
            self.close()
        elif k in (K.Key_Right, K.Key_PageDown):
            self.advance(1)
        elif k in (K.Key_Left, K.Key_PageUp, K.Key_Backspace):
            self.advance(-1)
        elif k == K.Key_W:
            self.advance(1, 0)
        elif k == K.Key_Q:
            self.advance(-1, 0)
        elif k == K.Key_P:
            self.advance(1, 1)
        elif k == K.Key_O:
            self.advance(-1, 1)
        elif k == K.Key_Home:
            for s in self.sides:
                s.i = 0
                self._show(s)
        elif k in (K.Key_Space, K.Key_MediaTogglePlayPause, K.Key_MediaPlay):
            self.toggle_play()
        elif k in (K.Key_S, K.Key_MediaStop, K.Key_MediaPause):
            if self.playing:
                self.toggle_play()
        elif k in (K.Key_Plus, K.Key_Equal):
            self.change_interval(1)
        elif k == K.Key_Minus:
            self.change_interval(-1)
        elif k in (K.Key_F, K.Key_F11):
            self.toggle_fullscreen()
        elif k == K.Key_I:
            self.toggle_info()
        elif k == K.Key_X:
            self.swap()
        else:
            super().keyPressEvent(e)

    def _side_of(self, obj):
        for i, s in enumerate(self.sides):
            if s.canvas is obj:
                return i
        return None

    def eventFilter(self, obj, ev):
        t = ev.type()
        i = self._side_of(obj)
        if t == ev.Type.MouseMove:
            if self.cursor().shape() == Qt.CursorShape.BlankCursor:
                self.unsetCursor()
            if self.isFullScreen():
                self.cursor_timer.start()
        elif t == ev.Type.MouseButtonPress and i is not None and ev.button() == Qt.MouseButton.LeftButton:
            back = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.advance(-1 if back else 1, i)
            return True
        elif t == ev.Type.Wheel and i is not None:
            dy = ev.angleDelta().y()
            if dy:
                self.advance(-1 if dy > 0 else 1, i)
            return True
        elif t == ev.Type.MouseButtonDblClick:
            self.toggle_fullscreen()
            return True
        elif t == ev.Type.ContextMenu:
            self._context_menu(ev.globalPos(), i)
            return True
        return super().eventFilter(obj, ev)

    def _hide_cursor(self):
        if self.isFullScreen():
            self.setCursor(Qt.CursorShape.BlankCursor)

    def _context_menu(self, pos, i):
        m = QMenu(self)
        m.addAction(tr("Successiva su entrambi  (→)"), lambda: self.advance(1))
        m.addAction(tr("Precedente su entrambi  (←)"), lambda: self.advance(-1))
        m.addSeparator()
        for j, (lbl, keys) in enumerate(((tr("Sinistra"), "Q / W"), (tr("Destra"), "O / P"))):
            if j >= len(self.sides):
                break
            sm = m.addMenu(f"{lbl}  ({keys})")
            sm.addAction(tr("Successiva"), lambda j=j: self.advance(1, j))
            sm.addAction(tr("Precedente"), lambda j=j: self.advance(-1, j))
            a = sm.addAction(tr("Avanzamento automatico"))
            a.setCheckable(True)
            a.setChecked(self.sides[j].mode == AUTO)
            a.toggled.connect(lambda _v, j=j: self.toggle_mode(j))
        m.addSeparator()
        m.addAction(tr("Ferma slideshow  (Spazio)") if self.playing else tr("Avvia / riprendi slideshow  (Spazio)"),
                    self.toggle_play)
        m.addAction(tr("Intervallo più lungo  (+)"), lambda: self.change_interval(1))
        m.addAction(tr("Intervallo più corto  (−)"), lambda: self.change_interval(-1))
        m.addAction(tr("Scambia i lati  (X)"), self.swap)
        m.addSeparator()
        m.addAction(tr("Schermo intero  (F)"), self.toggle_fullscreen)
        m.addAction(tr("Mostra informazioni  (I)"), self.toggle_info)
        m.addSeparator()
        m.addAction(tr("Chiudi  (Esc)"), self.close)
        m.exec(pos)

    def closeEvent(self, e):
        self.timer.stop()
        try:
            self.loader.ready.disconnect(self._on_ready)
        except (RuntimeError, TypeError):
            pass
        self.closed.emit("")
        super().closeEvent(e)
