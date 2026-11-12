"""Visualizzatore a schermo intero con slideshow."""
import os
import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QMovie, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
                               QSlider, QToolButton, QVBoxLayout, QWidget)

from . import APP_NAME, anim, codecs, gpu, library, orient, shortcuts
from .archive import is_virtual, parent_of, read_bytes, split, stat_any
from .canvas import (BACKGROUNDS, FIT_MODES, TRANSITIONS, Canvas, GLCanvas,  # noqa: F401 (riesportati)
                     background_name, fit_mode_name, make_canvas, transition_name)
from .i18n import num, tr
from .undo import manager as undo_manager
from .utils import human_size, samepath, show_in_explorer

INTERVALS = [1, 3, 5, 10, 15, 30, 60]


def is_animated(path):
    return anim.is_animated(path)


def stars(n):
    return "★" * n + "☆" * (5 - n)


def color_icon(color, size=14):
    pm = QPixmap(size, size)
    pm.fill(QColor(color) if color else QColor(0, 0, 0, 0))
    return QIcon(pm)


class SeekSlider(QSlider):
    """Barra del tempo che disegna la zona del ciclo A-B."""

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.loop = (None, None)

    def set_loop(self, a, b):
        self.loop = (a, b)
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        a, b = self.loop
        if a is None and b is None or self.maximum() <= 0:
            return
        from PySide6.QtGui import QPainter
        from PySide6.QtWidgets import QStyle
        hw = 14                                   # larghezza della maniglia (vedi stile)
        span = max(1, self.width() - hw)

        def x(v):
            return hw // 2 + QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), int(v), span)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() // 2
        if a is not None and b is not None:
            p.fillRect(x(a), cy - 5, max(2, x(b) - x(a)), 10, QColor(255, 170, 40, 110))
        p.setPen(QColor(255, 170, 40))
        f = p.font()
        f.setPointSizeF(7)
        f.setBold(True)
        p.setFont(f)
        for v, t in ((a, "A"), (b, "B")):
            if v is not None:
                xx = x(v)
                p.drawLine(xx, cy - 8, xx, cy + 8)
                p.drawText(xx + 2, cy - 1 if t == "A" else cy + 9, t)
        p.end()


class ControlBar(QFrame):
    """Barra comandi semitrasparente che compare muovendo il mouse."""

    def __init__(self, viewer):
        super().__init__(viewer)
        self.v = viewer
        self.setObjectName("bar")
        self.setStyleSheet(
            "#bar { background: rgba(20,20,22,210); border-radius: 10px; }"
            "QToolButton { color: #eee; background: transparent; border: none;"
            " padding: 6px 7px; font-size: 11pt; border-radius: 6px; }"
            "QToolButton:hover { background: rgba(255,255,255,40); }"
            "QLabel { color: #ccc; font-size: 10pt; padding: 0 4px; }"
            "QSlider::groove:horizontal { height: 6px; background: rgba(255,255,255,60); border-radius: 3px; }"
            "QSlider::sub-page:horizontal { background: #4da3ff; border-radius: 3px; }"
            "QSlider::handle:horizontal { background: #fff; width: 14px; margin: -5px 0; border-radius: 7px; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)
        S = viewer.settings

        # riga del tempo: solo con i video
        self.seek_row = QWidget(self)
        sr = QHBoxLayout(self.seek_row)
        sr.setContentsMargins(4, 2, 4, 0)
        sr.setSpacing(6)
        self.vplay = QToolButton(self.seek_row)
        self.vplay.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vplay.setToolTip(tr("Riproduci / metti in pausa il video"))
        self.vplay.clicked.connect(viewer.toggle_video_pause)
        self.t_pos = QLabel("0:00", self.seek_row)
        self.slider = SeekSlider(self.seek_row)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setRange(0, 0)
        self.slider.setMinimumWidth(200)
        self.slider.setToolTip(tr("Trascina o fai clic per andare a un punto del video"))
        self.slider.sliderMoved.connect(self._seek_drag)
        self.slider.sliderReleased.connect(lambda: self._seek_to(self.slider.value()))
        self.slider.actionTriggered.connect(self._seek_action)
        self.t_dur = QLabel("0:00", self.seek_row)
        sr.addWidget(self.vplay)
        sr.addWidget(self.t_pos)
        sr.addWidget(self.slider, 1)
        sr.addWidget(self.t_dur)
        self.loop_btns = []
        for txt, aid, slot in (("A", "loop_a", viewer.set_loop_a), ("B", "loop_b", viewer.set_loop_b),
                               ("✕ A-B", "loop_clear", viewer.clear_loop)):
            b = QToolButton(self.seek_row)
            b.setText(txt)
            k = shortcuts.native(S, "viewer", aid, True)
            b.setToolTip(shortcuts.label("viewer", aid) + (f" ({k})" if k else ""))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            sr.addWidget(b)
            self.loop_btns.append(b)
        self.loop_clear_btn = self.loop_btns[2]
        outer.addWidget(self.seek_row)

        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        outer.addWidget(row)

        def btn(text, aid, slot, tip=None):
            b = QToolButton(row)
            b.setText(text)
            k = shortcuts.native(S, "viewer", aid, True) if aid else ""
            b.setToolTip((tip or shortcuts.label("viewer", aid)) + (f" ({k})" if k else ""))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(slot)
            lay.addWidget(b)
            return b

        btn("↑ " + tr("Cartella"), "prev_folder", lambda: viewer.go_folder(-1))
        btn("◀", "prev", lambda: viewer.go(-1))
        self.play = btn("", "play", viewer.toggle_play)
        btn("▶", "next", lambda: viewer.go(1))
        btn(tr("Cartella") + " ↓", "next_folder", lambda: viewer.go_folder(1))
        lay.addSpacing(10)
        btn("−", None, lambda: viewer.change_interval(-1), tr("Intervallo più corto"))
        self.interval = QLabel(self)
        lay.addWidget(self.interval)
        btn("+", None, lambda: viewer.change_interval(1), tr("Intervallo più lungo"))
        lay.addSpacing(10)
        btn("⟲", "rotate_left", lambda: viewer.rotate("left"))
        btn("⟳", "rotate_right", lambda: viewer.rotate("right"))
        btn("⤢", "fit_mode", viewer.cycle_fit)
        self.fav = btn("♡", "favorite", viewer.toggle_favorite)
        self.audio = btn("🔊", "video_audio", viewer.toggle_video_audio)
        self.vol = QSlider(Qt.Orientation.Horizontal, row)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(70)
        self.vol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vol.setSingleStep(5)
        self.vol.setPageStep(10)
        self.vol.valueChanged.connect(viewer.set_video_volume)
        lay.addWidget(self.vol)
        lay.addSpacing(10)
        btn(tr("Opzioni"), "options", viewer.open_options)
        btn("✕", "close", viewer.close, tr("Chiudi"))
        self.hide()

    def refresh(self):
        self.play.setText("❚❚ " + tr("Ferma") if self.v.playing else "▶ " + tr("Avvia"))
        self.interval.setText(tr("Intervallo") + " " + self.v._fmt_interval())
        p = self.v.nav.current()
        self.fav.setText("♥" if p and library.is_favorite(p) else "♡")
        vid = getattr(self.v, "video", None)
        self.audio.setVisible(vid is not None)
        self.vol.setVisible(vid is not None)
        self.seek_row.setVisible(vid is not None)
        if vid is not None:
            self.audio.setText("🔇" if vid.muted() else ("🔉" if vid.volume() < 50 else "🔊"))
            self.vol.blockSignals(True)
            self.vol.setValue(vid.volume())
            self.vol.blockSignals(False)
            self.vol.setToolTip(tr("Volume del video") + f": {vid.volume()}%  (" + tr("solo per questo programma") + ")")
            self.vplay.setText("▶" if not vid.is_playing() else "❚❚")
            self.set_time(vid.position(), vid.duration())
            can = self.v._loop_allowed()
            for b in self.loop_btns:
                b.setVisible(can)
            on = vid.loop_a is not None or vid.loop_b is not None
            self.loop_clear_btn.setVisible(can and on)
            for b, v in ((self.loop_btns[0], vid.loop_a), (self.loop_btns[1], vid.loop_b)):
                b.setText(b.text()[0] + (" " + self._fmt(v) if v is not None else ""))
                b.setStyleSheet("color: #ffaa28; font-weight: bold;" if v is not None else "")
            self.slider.set_loop(vid.loop_a, vid.loop_b)
        self.adjustSize()
        self.place()

    @staticmethod
    def _fmt(ms):
        sec = max(0, int(ms) // 1000)
        h, rem = divmod(sec, 3600)
        m, sec = divmod(rem, 60)
        return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

    def set_time(self, pos, dur):
        dur = max(0, int(dur))
        if self.slider.maximum() != dur:
            self.slider.setRange(0, dur)
            self.slider.setPageStep(max(1000, dur // 20))
            self.slider.setSingleStep(5000)
        if not self.slider.isSliderDown():
            self.slider.blockSignals(True)
            self.slider.setValue(int(pos))
            self.slider.blockSignals(False)
            self.t_pos.setText(self._fmt(pos))
        self.t_dur.setText(self._fmt(dur))
        vid = getattr(self.v, "video", None)
        if vid is not None:
            self.vplay.setText("▶" if not vid.is_playing() else "❚❚")

    def _seek_to(self, ms):
        vid = getattr(self.v, "video", None)
        if vid is not None:
            vid.seek(ms)
            self.t_pos.setText(self._fmt(ms))
            self.v.bar_timer.start()

    def _seek_drag(self, ms):
        self.t_pos.setText(self._fmt(ms))
        self._seek_to(ms)               # anteprima mentre si trascina

    def _seek_action(self, action):
        # clic sulla barra (fuori dalla maniglia): salta esattamente lì
        A = QSlider.SliderAction
        if self.slider.isSliderDown() or action not in (A.SliderPageStepAdd, A.SliderPageStepSub):
            return
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QStyle
        x = self.slider.mapFromGlobal(QCursor.pos()).x()
        span = max(1, self.slider.width())
        ms = QStyle.sliderValueFromPosition(self.slider.minimum(), self.slider.maximum(), x, span)
        QTimer.singleShot(0, lambda: (self.slider.setValue(ms), self._seek_to(ms)))

    def place(self):
        p = self.parentWidget()
        if self.width() > p.width() - 8:
            self.resize(max(200, p.width() - 8), self.height())
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 16)


class ViewerWindow(QWidget):
    to_browser = Signal(str)
    closed = Signal(str)
    files_changed = Signal(str)          # cartella modificata
    webtoon_requested = Signal(list, int)

    def __init__(self, nav, loader, settings, slideshow=False, parent=None, screensaver=False):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(QSize(400, 300))
        self.nav = nav
        self.loader = loader
        self.settings = settings
        self.screensaver = screensaver
        self.playing = slideshow
        self.slideshow_mode = slideshow
        self.started_as_slideshow = slideshow
        self.interval = float(settings.value("slideshow/interval", 4.0, type=float))
        if screensaver:
            self.interval = float(settings.value("screensaver/interval", 6.0, type=float))
        self.pair = slideshow and not screensaver and settings.value("slideshow/pair", False, type=bool)
        self.manga = settings.value("slideshow/manga", False, type=bool)
        self._shown2 = None
        self.view_o = orient.IDENTITY          # rotazione / specchio a video
        self._wide = {}
        self.canvas = make_canvas(self)
        self.canvas.rtl = self.manga
        self.canvas.show_info = settings.value("viewer/show_info", False, type=bool) and not screensaver
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.bar = ControlBar(self)
        self.bar_timer = QTimer(self, singleShot=True, interval=2500)
        self.bar_timer.timeout.connect(self._hide_bar)
        self.movie = None
        self.video = None
        self.music = None
        self.music_on = True
        self.pair_movies = {}
        self._pair_slots = [None, None]
        self._movie_keep_view = False
        self._movie_frames = 0
        self._shown_path = None
        self._was_maximized = True
        self._ss_origin = None
        self.timer = None
        self.apply_options()
        self.canvas.set_fit_mode(settings.value("viewer/fit_mode", "fit"))
        self.canvas.background = settings.value("viewer/background", "black")

        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._auto_next)
        self.cursor_timer = QTimer(self, singleShot=True, interval=2000)
        self.cursor_timer.timeout.connect(self._hide_cursor)
        self.setMouseTracking(True)
        self.canvas.installEventFilter(self)

        loader.ready.connect(self._on_ready)
        QTimer.singleShot(0, self._start)

    def _start(self):
        resumed = self._resume_comic()
        self._show_current()
        self._ensure_music()
        if self.playing and not self.screensaver:
            pos = self.nav.folder_position()
            extra = "  ·  " + tr("{n} cartelle", n=pos[1]) if pos else ""
            self.canvas.flash(f"▶ Slideshow  ·  {self._fmt_interval()}{extra}", 2000)
        if resumed:
            self.canvas.flash(resumed, 2600)

    def _st(self, key, default=None):
        return self.canvas.style_.get(key, default)

    # ----------------------------------------------------------- fumetti
    def _resume_comic(self):
        """Archivio aperto dall'inizio: si riparte dall'ultima pagina letta."""
        n = self.nav
        cur = n.current()
        if not cur or not is_virtual(cur) or getattr(n, "explicit_start", False) or n.ii != 0 \
                or n.shuffle or not self._st("comics/resume", True):
            return None
        a, _m = split(cur)
        lp = library.last_page(a)
        if not lp:
            return None
        target = a + "|" + lp[0]
        for i, p in enumerate(n.images):
            if p == target and i > 0:
                n.ii = i
                return tr("Ripreso da pagina {i}/{n}  ·  Home per tornare all'inizio", i=i + 1, n=len(n.images))
        return None

    def _remember_page(self, path):
        if path and is_virtual(path) and self._st("comics/resume", True) and not self.nav.shuffle:
            a, m = split(path)
            i, n = self.nav.position()
            try:
                library.set_last_page(a, m, i, n)
            except Exception:  # noqa: BLE001 - database non scrivibile: pazienza
                pass

    # ------------------------------------------------------------ animazioni
    def _stop_movie(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        if self.video is not None:
            self.video.stop()
            self.video = None
        self._stop_pair_movies()

    def _stop_pair_movies(self):
        for m in self.pair_movies.values():
            m.stop()
            m.deleteLater()
        self.pair_movies = {}

    def _animation_allowed(self):
        """GIF/WebP animate e video, con un'immagine alla volta: sempre nel visualizzatore;
        nello slideshow solo in pausa e se attivato nelle opzioni (predefinito: sì)."""
        if self.pair or self.playing:
            return False
        return not self.slideshow_mode or bool(self._st("viewer/animate_slideshow", True))

    def _pair_animation_allowed(self):
        return self.pair and not self.playing and bool(self._st("viewer/animate_pair"))

    def _sync_pair_animation(self):
        if not self._pair_animation_allowed():
            self._stop_pair_movies()
            return
        for slot, path in enumerate(self._pair_slots):
            if not path or slot in self.pair_movies or not anim.is_animated(path):
                continue
            m = anim.make_movie(path, self)
            if m is None:
                continue
            self.pair_movies[slot] = m
            m.frameChanged.connect(lambda _n, slot=slot, m=m: self._on_pair_frame(slot, m))
            m.error.connect(lambda _e, slot=slot, m=m: self._pair_movie_failed(slot, m))
            m.start()

    def _on_pair_frame(self, slot, m):
        if self.pair_movies.get(slot) is m:
            self.canvas.set_pair_image(slot, gpu.prepare_image(m.currentImage()))

    def _pair_movie_failed(self, slot, m):
        if self.pair_movies.get(slot) is m and m.state() == QMovie.MovieState.NotRunning:
            self.pair_movies.pop(slot).deleteLater()

    def _start_movie(self, path, keep_view=False):
        if not self._animation_allowed() or not anim.is_animated(path):
            return False
        m = anim.make_movie(path, self)
        if m is None:
            return False
        self._movie_keep_view = keep_view
        self._movie_frames = 0
        self.movie = m
        m.frameChanged.connect(self._on_frame)
        m.error.connect(lambda _e, m=m: self._movie_failed(m))
        m.start()
        return True

    def _movie_failed(self, m):
        # Qt segnala un "errore" anche a fine giro, poi riparte: conta solo se si è fermata
        if m is not self.movie or (m.state() != QMovie.MovieState.NotRunning and self._movie_frames):
            return
        self._stop_movie()
        if self._shown_path:
            self.loader.request(self._shown_path)

    def _sync_animation(self):
        path = self._shown_path
        if not path:
            return
        if self.pair:
            self._sync_pair_animation()
            return
        if self.video is not None:
            if self._animation_allowed() and not self.video.user_paused:
                self.video.play()
            else:
                self.video.pause()
            return
        if self._animation_allowed():
            if self.movie is None and self._start_movie(path, keep_view=True):
                self._update_info()
        elif self.movie is not None:
            self._stop_movie()          # resta il fotogramma corrente

    # ------------------------------------------------------------------ video
    def _start_video(self, path):
        from .video import VideoPlayer
        try:
            v = VideoPlayer(path, muted=not self._st("viewer/video_sound", True),
                            volume=int(self._st("viewer/video_volume", 100)), parent=self)
        except Exception as e:  # noqa: BLE001 - QtMultimedia non disponibile
            self._display_error(path, str(e))
            return
        self.video = v
        self._video_frames = 0
        v.frame.connect(lambda img, v=v: self._on_video_frame(v, img))
        v.failed.connect(lambda err, v=v: self._video_failed(v, err))
        v.position_changed.connect(lambda ms, v=v: v is self.video and self.bar.set_time(ms, v.duration()))
        v.duration_changed.connect(lambda ms, v=v: v is self.video and self.bar.set_time(v.position(), ms))
        v.play()        # serve per il primo fotogramma; se non deve animarsi si ferma subito

    def _on_video_frame(self, v, img):
        if v is not self.video:
            return
        first = self._video_frames == 0
        self._video_frames += 1
        self.canvas.set_image(gpu.prepare_image(orient.apply(img, self.view_o)), keep_view=not first)
        if first:
            self._update_info()
            self._after_display()
            if not self._animation_allowed():
                v.pause()

    def _video_failed(self, v, err):
        if v is self.video:
            self.video.stop()
            self.video = None
            self._display_error(self._shown_path, err or tr("Video non riproducibile"))

    # --------------------------------------------------------------- immagini
    def _show_current(self, transition=0):
        """transition: 0 nessuna, +1 / -1 direzione dello scorrimento (avanti / indietro)."""
        self.timer.stop()
        if transition and self.slideshow_mode:
            kind = self._st("slideshow/transition", "fade")
            self.canvas.prepare_transition(kind, int(self._st("slideshow/transition_ms", 600)), transition)
        self._stop_movie()
        self.canvas.kb = None
        path = self.nav.current()
        if path != self._shown_path:
            self.view_o = orient.IDENTITY
        self._shown_path = path
        self._shown2 = self._partner() if path else None
        if not path:
            self.canvas.set_message(tr("Nessuna immagine in questa cartella\n\n"
                                       "↓ / ↑  per cambiare cartella   ·   Esc per uscire"))
            self.setWindowTitle(f"{os.path.basename(self.nav.folder)} - {APP_NAME}")
            self._update_info()
            return
        self.setWindowTitle(f"{os.path.basename(path.split('|')[-1])} - {APP_NAME}")
        if self.pair and not (self._shown2 is None and codecs.is_video(path)):
            self._show_pair()
            return
        if codecs.is_video(path):
            self._start_video(path)
            self._update_info()
            return
        if self._start_movie(path):
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

    # ------------------------------------------------------ 2 affiancate
    def _double_pages(self):
        return bool(self._st("slideshow/double_pages", True))

    def _is_wide(self, path):
        """Immagine orizzontale (pagina doppia) o video: si mostra da sola."""
        if path in self._wide:
            return self._wide[path]
        if codecs.is_video(path):
            w = True
        else:
            s = codecs.read_size(path)
            w = s.isValid() and s.width() > s.height() * 1.15
        self._wide[path] = w
        return w

    def _partner(self):
        if not self.pair:
            return None
        n = self.nav
        if not (0 <= n.ii + 1 < len(n.images)):
            return None
        cur, nxt = n.images[n.ii], n.images[n.ii + 1]
        if codecs.is_video(cur) or codecs.is_video(nxt):
            return None
        if self._double_pages() and (self._is_wide(cur) or self._is_wide(nxt)):
            return None
        return nxt

    def _back_step(self):
        n = self.nav
        if not self._double_pages():
            return 2
        if n.ii - 1 < 0 or self._is_wide(n.images[n.ii - 1]):
            return 1
        if n.ii - 2 >= 0 and not self._is_wide(n.images[n.ii - 2]):
            return 2
        return 1

    def _show_pair(self):
        p1, p2 = self._shown_path, self._shown2
        self.loader.request(p1)
        if p2:
            self.loader.request(p2, keep_wanted=True)
        self._try_pair()

    def _try_pair(self):
        p1, p2 = self._shown_path, self._shown2
        img1, err1 = self.loader.get(p1), self.loader.error(p1)
        img2 = self.loader.get(p2) if p2 else None
        err2 = self.loader.error(p2) if p2 else None
        if img1 is None and not err1:
            self._update_info()
            return
        if p2 and img2 is None and not err2:
            self._update_info()
            return
        if err1 and (not p2 or err2):
            self._display_error(p1, err1)
            return
        if err1:
            img1, img2 = img2, None
        self._stop_pair_movies()
        self._pair_slots = [p2, None] if err1 else [p1, p2 if img2 is not None else None]
        self.canvas.set_pair(img1, img2)
        self._sync_pair_animation()
        self._update_info()
        self._after_display()

    def _pair_step(self, d):
        """Avanza (o torna indietro) di una coppia; le pagine doppie contano da sole."""
        n = self.nav
        n.folder_changed = False
        if not n.images:
            return n.step(d)
        old = n.ii
        if d > 0:
            step = 2 if self._partner() else 1
            if n.ii + step < len(n.images):
                n.ii += step
                return True
            n.ii = len(n.images) - 1
            if n.step(1):
                return True
        else:
            if n.ii > 0:
                n.ii = max(0, n.ii - self._back_step())
                return True
            n.ii = 0
            if n.step(-1):
                if n.folder_changed or n.ii > old:
                    last = len(n.images) - 1
                    if self._double_pages():
                        if last >= 1 and not self._is_wide(n.images[last]) and \
                                not self._is_wide(n.images[last - 1]):
                            n.ii = last - 1
                    else:
                        n.ii -= n.ii % 2
                return True
        n.ii = old
        return False

    def toggle_pair(self):
        self.pair = not self.pair
        self.settings.setValue("slideshow/pair", self.pair)
        self.canvas.flash(tr("Due immagini affiancate") if self.pair else tr("Un'immagine alla volta"))
        self._show_current()

    def toggle_manga(self):
        self.manga = not self.manga
        self.settings.setValue("slideshow/manga", self.manga)
        self.canvas.rtl = self.manga
        if self.pair:
            self.canvas.flash(tr("Modalità manga: da destra a sinistra") if self.manga
                              else tr("Da sinistra a destra"))
        else:
            self.canvas.flash(tr("Modalità manga attivata (vale con 2 affiancate, tasto D)") if self.manga
                              else tr("Modalità manga disattivata"))
        self.canvas.update()

    def _on_frame(self, _n):
        if self.movie is not None:
            keep = self._movie_keep_view
            self._movie_keep_view = True
            self._movie_frames += 1
            self.canvas.set_image(gpu.prepare_image(orient.apply(self.movie.currentImage(), self.view_o)),
                                  keep_view=keep)
            if not keep:
                self._update_info()

    def _on_ready(self, path, img, err):
        if self.pair and path in (self._shown_path, self._shown2):
            self._try_pair()
            return
        if path != self._shown_path or self.movie is not None or self.video is not None:
            return
        if err:
            self._display_error(path, err)
        else:
            self._display(path, img)

    def _display(self, path, img):
        self.canvas.set_image(orient.apply(img, self.view_o))
        self._update_info()
        self._after_display()

    def _display_error(self, path, err):
        name = os.path.basename((path or "").split("|")[-1])
        self.canvas.set_message(tr("Impossibile aprire\n{name}\n\n{err}", name=name, err=err))
        self._update_info()
        self._after_display()

    def _after_display(self):
        self._remember_page(self._shown_path)
        if self.pair:
            for k in (2, 3):
                nxt = self.nav.peek(k)
                if nxt and not codecs.is_video(nxt):
                    self.loader.request(nxt, keep_wanted=True)
        else:
            nxt = self.nav.peek(1)
            if nxt and not codecs.is_video(nxt):
                self.loader.request(nxt, keep_wanted=True)
        if self.playing:
            if self._st("slideshow/transition", "fade") == "kenburns" and not self.pair:
                self.canvas.start_kenburns(self.interval + int(self._st("slideshow/transition_ms", 600)) / 1000,
                                           int(self._st("slideshow/kenburns_zoom", 12)) / 100)
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
            name = os.path.basename(path.split("|")[-1])
            img = self.canvas.image
            if self._shown2 and self.pair:
                lines.append(f"{name}  +  {os.path.basename(self._shown2.split('|')[-1])}"
                             f"   [{i}-{i + 1}/{n}]   {date}")
            else:
                dims = ""
                if img is not None and not img.isNull():
                    dims = f"   {img.width()}×{img.height()}   {self.canvas.current_scale() * 100:.0f}%"
                lines.append(f"{name}   [{i}/{n}]{dims}   {size}   {date}")
            extra = []
            r, lb = library.get(path)
            if r:
                extra.append(stars(r))
            if lb:
                extra.append("● " + library.label_name(lb))
            if library.is_favorite(path):
                extra.append("♥ " + tr("Preferiti"))
            d = orient.describe(self.view_o)
            if d:
                extra.append("⟳ " + d)
            if self.canvas.fit_mode != "fit" and not self.pair:
                extra.append(fit_mode_name(self.canvas.fit_mode))
            if self.video is not None:
                extra.append("🎬 " + (tr("audio attivo") if not self.video.muted() else tr("muto")))
            if extra:
                lines.append("   ".join(extra))
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
            if self.music is not None and self.music.ok() and self.music_on:
                opts.append("♫ " + self.music.title())
            o = f"  ({', '.join(opts)})" if opts else ""
            lines.append(f"Slideshow {state} · {self._fmt_interval()}{o}")
        self.canvas.info_lines = lines
        self.canvas.paused = self.slideshow_mode and not self.playing
        if self.bar.isVisible():
            self.bar.refresh()
        self.canvas.update()

    # ---------------------------------------------------------- navigazione
    def go(self, d):
        if self.pair and self.nav.images:
            moved = self._pair_step(d)
        else:
            moved = self.nav.step(d)
        if moved:
            self._show_current(transition=d)
            if self.nav.folder_changed:
                self._flash_folder()
            return True
        self.canvas.flash(tr("Ultima immagine") if d > 0 else tr("Prima immagine"), 900)
        if self.playing:
            self.timer.start(int(self.interval * 1000))
        return False

    def go_folder(self, d):
        self.setCursor(Qt.CursorShape.WaitCursor)
        try:
            moved = self.nav.jump_folder(d)
        finally:
            self.unsetCursor()
        if moved:
            self._show_current(transition=d)
            self._flash_folder()
        else:
            self.canvas.flash(tr("Nessuna altra cartella con immagini"), 1200)

    def first(self):
        self.nav.first()
        self._show_current(transition=-1)

    def last(self):
        self.nav.last()
        if self.pair and not self._double_pages():
            self.nav.ii -= self.nav.ii % 2
        self._show_current(transition=1)

    def _flash_folder(self):
        name = os.path.basename(self.nav.folder) or self.nav.folder
        pos = self.nav.folder_position()
        p = f"  ({pos[0]}/{pos[1]})" if pos else ""
        self.canvas.flash(tr("Cartella: ") + f"{name}{p}", int(self.canvas.style_["osd/folder_ms"]), "folder")

    def _auto_next(self):
        if not self.playing:
            return
        if (self._pair_step(1) if self.pair and self.nav.images else self.nav.step(1)):
            self._show_current(transition=1)
            if self.nav.folder_changed:
                self._flash_folder()
        else:
            self.playing = False
            self._update_info()
            self.canvas.flash(tr("Fine dello slideshow"), 3000)
            if self.music is not None:
                self.music.pause()

    def toggle_play(self):
        self.set_playing(not self.playing)

    def set_playing(self, on):
        self.slideshow_mode = True
        self.playing = on
        self._ensure_music()
        if on:
            self.canvas.flash("▶ " + tr("Slideshow avviato") + f" · {self._fmt_interval()}")
            self.timer.start(int(self.interval * 1000))
            if self.canvas.kb is not None:
                self.canvas.freeze_kenburns(False)
            if self.music is not None and self.music_on:
                self.music.play()
        else:
            self.timer.stop()
            self.canvas.freeze_kenburns(True)
            self.canvas.flash("❚❚ " + tr("Slideshow fermo"))
            if self.music is not None:
                self.music.pause()
        self._sync_animation()
        self._update_info()

    # -------------------------------------------------------------- musica
    def _ensure_music(self):
        if self.music is not None or not self.slideshow_mode or self.screensaver:
            return
        src = self._st("slideshow/music", "")
        if not src:
            return
        try:
            from .video import SlideshowMusic
            self.music = SlideshowMusic(src, bool(self._st("slideshow/music_shuffle", True)),
                                        int(self._st("slideshow/music_volume", 60)), self)
        except Exception:  # noqa: BLE001 - QtMultimedia assente
            self.music = None
            return
        if self.playing and self.music_on:
            self.music.play()

    def toggle_music(self):
        self._ensure_music()
        if self.music is None or not self.music.ok():
            self.canvas.flash(tr("Nessuna musica: scegli un file o una cartella in Opzioni → Slideshow"), 2500)
            return
        self.music_on = not self.music_on
        if self.music_on and self.playing:
            self.music.play()
        else:
            self.music.pause()
        self.canvas.flash(("♫ " + self.music.title()) if self.music_on else tr("Musica spenta"))
        self._update_info()

    def toggle_video_pause(self):
        v = self.video
        if v is None:
            return
        if v.is_playing():
            v.user_paused = True
            v.pause()
        else:
            v.user_paused = False
            v.play()
        self.bar.refresh()

    def _loop_allowed(self):
        return self.video is not None and not self.slideshow_mode

    def set_loop_a(self):
        v = self.video
        if not self._loop_allowed():
            return
        a = v.position()
        b = v.loop_b if v.loop_b is not None and v.loop_b > a + 100 else None
        v.set_loop(a, b)
        self.canvas.flash(tr("Punto A") + " " + ControlBar._fmt(a)
                          + ("" if b is not None else " – " + tr("ora imposta il punto B")))
        self.bar.refresh()

    def set_loop_b(self):
        v = self.video
        if not self._loop_allowed():
            return
        b = v.position()
        a = v.loop_a if v.loop_a is not None else 0
        if b <= a + 100:
            self.canvas.flash(tr("Il punto B deve venire dopo il punto A"))
            return
        v.set_loop(a, b)
        self.canvas.flash(tr("Ciclo A-B") + f" {ControlBar._fmt(a)} → {ControlBar._fmt(b)}")
        self.bar.refresh()

    def clear_loop(self):
        v = self.video
        if v is None or (v.loop_a is None and v.loop_b is None):
            return
        v.set_loop(None, None)
        self.canvas.flash(tr("Ciclo A-B tolto"))
        self.bar.refresh()

    def set_video_volume(self, v, flash=False):
        vid = self.video
        if vid is None:
            return
        louder = int(v) > vid.volume()
        vid.set_volume(v)
        self.settings.setValue("viewer/video_volume", vid.volume())
        if vid.muted() and louder:                # alzare il volume riaccende l'audio
            vid.set_muted(False)
            self.settings.setValue("viewer/video_sound", True)
        if flash:
            self.canvas.flash(tr("Volume del video") + f": {vid.volume()}%")
        self.bar.refresh()

    def change_video_volume(self, step):
        if self.video is not None:
            self.set_video_volume(self.video.volume() + step, flash=True)

    def toggle_video_audio(self):
        if self.video is None:
            return
        self.video.set_muted(not self.video.muted())
        self.settings.setValue("viewer/video_sound", not self.video.muted())
        self.canvas.style_["viewer/video_sound"] = not self.video.muted()
        self.canvas.flash(tr("Audio del video attivo") if not self.video.muted() else tr("Video muto"))
        self.bar.refresh()
        self._update_info()

    # ------------------------------------------------------------ opzioni
    def apply_options(self):
        from .options import load_style
        self.canvas.style_ = load_style(self.settings)
        self.keymap = shortcuts.keymap(self.settings, "viewer")
        if not self.canvas.style_["viewer/controls"]:
            self.bar.hide()
        self.canvas.loupe_mag = float(self.canvas.style_.get("viewer/loupe_mag", 3))
        if self.timer is not None:   # non durante __init__
            self._sync_animation()
        self.canvas.update()

    def open_options(self, tab=None):
        from .options import OptionsDialog
        was = self.playing
        self.timer.stop()
        self.unsetCursor()
        if OptionsDialog(self.settings, self, tab=tab).run():
            self.apply_options()
            self.bar.deleteLater()
            self.bar = ControlBar(self)
        if was:
            self.timer.start(int(self.interval * 1000))

    def open_shortcuts(self):
        was = self.playing
        self.timer.stop()
        if shortcuts.ShortcutsDialog(self.settings, self).run():
            self.apply_options()
        if was:
            self.timer.start(int(self.interval * 1000))

    def _show_bar(self):
        if not self.canvas.badge_on:
            self.canvas.badge_on = True
            self.canvas.update()
        self.bar_timer.start()
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
            self.canvas.badge_on = False
            self.canvas.update()

    def _fmt_interval(self):
        return f"{num(self.interval)} s"

    def change_interval(self, d):
        cur = self.interval
        if d > 0:
            nxt = next((v for v in INTERVALS if v > cur + 1e-6), INTERVALS[-1])
        else:
            nxt = next((v for v in reversed(INTERVALS) if v < cur - 1e-6), INTERVALS[0])
        self.set_interval(nxt)

    def set_interval(self, secs):
        self.interval = secs
        self.settings.setValue("slideshow/interval", self.interval)
        self.canvas.flash(tr("Intervallo") + f": {self._fmt_interval()}")
        self._update_info()
        if self.playing:
            self.timer.start(int(self.interval * 1000))

    # --------------------------------------------------------- visualizzazione
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

    def set_fit(self, mode):
        self.canvas.set_fit_mode(mode)
        self.settings.setValue("viewer/fit_mode", self.canvas.fit_mode)
        self.canvas.flash(fit_mode_name(self.canvas.fit_mode))
        self._update_info()

    def cycle_fit(self):
        i = FIT_MODES.index(self.canvas.fit_mode) if self.canvas.fit_mode in FIT_MODES else 0
        self.set_fit(FIT_MODES[(i + 1) % len(FIT_MODES)])

    def rotate(self, op):
        """Ruota / specchia a video (Ctrl+S per salvarlo nel file)."""
        if self.pair or not self._shown_path:
            self.canvas.flash(tr("Rotazione disponibile con un'immagine alla volta"))
            return
        self.view_o = orient.compose(self.view_o, op)
        src = self.loader.get(self._shown_path) if self.movie is None and self.video is None else None
        if src is not None:
            self.canvas.set_image(orient.apply(src, self.view_o))
        elif self.movie is not None:
            self.canvas.set_image(orient.apply(self.movie.currentImage(), self.view_o))
        d = orient.describe(self.view_o)
        hint = "   ·   " + tr("Ctrl+S per salvarla nel file") if d and orient.can_save(self._shown_path) else ""
        self.canvas.flash((d or tr("Orientamento originale")) + hint, 2000)
        self._update_info()

    def save_orientation(self):
        path = self._shown_path
        if not path or orient.is_identity(self.view_o):
            self.canvas.flash(tr("Nessuna rotazione da salvare"))
            return
        if not orient.can_save(path):
            self.canvas.flash(tr("Questo file non si può modificare (archivio, video o RAW)"), 2000)
            return
        try:
            how = orient.save_to_file(path, self.view_o)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, tr("Impossibile salvare la rotazione:\n{err}", err=e))
            return
        self.view_o = orient.IDENTITY
        self.loader.forget(path)
        self.files_changed.emit(parent_of(path))
        self._shown_path = None
        self._show_current()
        self.canvas.flash(tr("Rotazione salvata senza perdita di qualità") if how == "lossless"
                          else tr("Rotazione salvata"), 2000)

    def toggle_loupe(self):
        self.canvas.loupe = not self.canvas.loupe
        self.canvas.flash(tr("Lente d'ingrandimento: Maiusc+rotellina per l'ingrandimento")
                          if self.canvas.loupe else tr("Lente spenta"))
        self.canvas.update()

    def set_background(self, bg):
        self.canvas.background = bg if bg in BACKGROUNDS else "black"
        self.settings.setValue("viewer/background", self.canvas.background)
        self.canvas.flash(tr("Sfondo: {name}", name=background_name(self.canvas.background)))
        self.canvas.update()

    def cycle_background(self):
        i = BACKGROUNDS.index(self.canvas.background) if self.canvas.background in BACKGROUNDS else 0
        self.set_background(BACKGROUNDS[(i + 1) % len(BACKGROUNDS)])

    def toggle_hist(self):
        self.canvas.show_hist = not self.canvas.show_hist
        self.canvas.update()

    def toggle_pixel(self):
        self.canvas.show_pixel = not self.canvas.show_pixel
        self.canvas.update()

    def set_transition(self, kind):
        self.settings.setValue("slideshow/transition", kind)
        self.canvas.style_["slideshow/transition"] = kind
        if kind != "kenburns":
            self.canvas.kb = None
        self.canvas.flash(tr("Transizione: {name}", name=transition_name(kind)))

    # --------------------------------------------------------------- file
    def _real_path(self):
        path = self.nav.current()
        if not path:
            return None
        if is_virtual(path):
            self.canvas.flash(tr("Le immagini dentro un archivio non si possono modificare o spostare"), 2000)
            return None
        return path

    def _after_removal(self, path):
        self.loader.forget(path)
        self.nav.remove_current()
        self.files_changed.emit(parent_of(path))
        self._shown_path = None
        self._show_current(transition=1)

    def delete_current(self):
        path = self._real_path()
        if not path:
            return
        was_playing = self.playing
        self.timer.stop()
        if not self._st("viewer/quick_delete", True):
            r = QMessageBox.question(self, tr("Elimina"),
                                     tr("Spostare nel Cestino?") + f"\n\n{os.path.basename(path)}")
            if r != QMessageBox.StandardButton.Yes:
                if was_playing:
                    self.timer.start(int(self.interval * 1000))
                return
        self._stop_movie()
        if undo_manager.delete(path, self.nav.ii):
            self._after_removal(path)
            k = shortcuts.native(self.settings, "viewer", "undo", True)
            self.canvas.flash(tr("Spostata nel Cestino") + (f"  ·  {k} " + tr("per annullare") if k else ""), 2200)
            return
        QMessageBox.warning(self, tr("Elimina"), tr("Impossibile spostare il file nel Cestino."))
        if was_playing:
            self.timer.start(int(self.interval * 1000))

    def undo(self):
        if not undo_manager.can_undo():
            self.canvas.flash(tr("Niente da annullare"))
            return
        try:
            op = undo_manager.undo()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, tr("Impossibile annullare:\n{err}", err=e))
            return
        if op is None:
            return
        if op.kind == "copy":
            self.canvas.flash(tr("Copia annullata: {name}", name=os.path.basename(op.dst)))
            self.files_changed.emit(os.path.dirname(op.dst))
            return
        restored = op.src
        n = self.nav
        if n.custom or samepath(parent_of(restored), n.folder):
            idx = op.index if op.index is not None and 0 <= op.index <= len(n.images) else n.ii
            n.images.insert(idx, restored)
            n.ii = idx
            self._shown_path = None
            self._show_current()
        self.files_changed.emit(parent_of(restored))
        if op.kind == "move":
            self.files_changed.emit(os.path.dirname(op.dst))
        self.canvas.flash(tr("Ripristinata: {name}", name=os.path.basename(restored)), 1800)

    def sort_to(self, i):
        """Tasti 1-9: sposta (o copia) l'immagine nella cartella impostata."""
        path = self.nav.current()
        if not path:
            return
        target = self.settings.value(f"sort/target{i}", "")
        if not target:
            self.canvas.flash(tr("Cartella {i} non impostata: Opzioni → Smistamento", i=i), 2500)
            return
        mode = self.settings.value("sort/mode", "move")
        name = os.path.basename(target.rstrip("\\/")) or target
        try:
            if mode == "copy" or is_virtual(path):
                data = read_bytes(path) if is_virtual(path) else None
                undo_manager.copy(path, target, data)
                self.files_changed.emit(target)
                self.canvas.flash(tr("Copiata in {name}", name=name), 1500)
                if self.slideshow_mode or self._st("sort/advance", True):
                    self.go(1)
                return
            self._stop_movie()
            undo_manager.move(path, target, self.nav.ii)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, tr("Operazione non riuscita: {err}", err=e))
            return
        self.files_changed.emit(target)
        self._after_removal(path)
        k = shortcuts.native(self.settings, "viewer", "undo", True)
        self.canvas.flash(f"→ {name}" + (f"  ·  {k} " + tr("per annullare") if k else ""), 1500)

    def set_rating(self, n):
        path = self.nav.current()
        if not path:
            return
        library.set_rating([path], n)
        self.canvas.flash(stars(n) if n else tr("Valutazione tolta"))
        self.files_changed.emit(parent_of(path))
        self._update_info()

    def set_label(self, n):
        path = self.nav.current()
        if not path:
            return
        library.set_label([path], n)
        self.canvas.flash("● " + library.label_name(n) if n else tr("Etichetta tolta"))
        self.files_changed.emit(parent_of(path))
        self._update_info()

    def toggle_favorite(self):
        path = self.nav.current()
        if not path:
            return
        added = library.toggle_favorite([path])
        self.canvas.flash("♥ " + tr("Aggiunta ai Preferiti") if added else "♡ " + tr("Tolta dai Preferiti"))
        self._update_info()

    def add_to_collection(self, cid=None):
        path = self.nav.current()
        if not path:
            return
        if cid is None:
            name, ok = QInputDialog.getText(self, tr("Nuova raccolta"), tr("Nome della raccolta:"))
            if not ok or not name.strip():
                return
            cid = library.collection_id(name.strip(), create=True)
        library.add_to_collection(cid, [path])
        self.canvas.flash(tr("Aggiunta alla raccolta «{name}»", name=library.display_name(cid)))

    def rename_current(self):
        path = self._real_path()
        if not path:
            return
        was = self.playing
        self.timer.stop()
        from .fileops import rename_single
        new = rename_single(self, path)
        if new:
            self.loader.forget(path)
            if 0 <= self.nav.ii < len(self.nav.images):
                self.nav.images[self.nav.ii] = new
            self.files_changed.emit(parent_of(new))
            self._shown_path = None
            self._show_current()
        elif was:
            self.timer.start(int(self.interval * 1000))

    def edit_current(self):
        path = self._real_path()
        if not path:
            return
        if codecs.is_video(path):
            self.canvas.flash(tr("I video non si possono modificare"))
            return
        was = self.playing
        self.set_playing(False) if was else None
        self.unsetCursor()
        from .edit import EditorDialog
        saved = EditorDialog(path, self.settings, self).run()
        if saved:
            self.loader.forget(path)
            self.files_changed.emit(parent_of(saved))
            if not samepath(saved, path) and samepath(parent_of(saved), self.nav.folder):
                self.nav.images.insert(self.nav.ii + 1, saved)
                self.nav.ii += 1
            self._shown_path = None
            self._show_current()

    def image_info(self):
        path = self.nav.current()
        if not path:
            return
        was = self.playing
        self.timer.stop()
        self.unsetCursor()
        from .imageinfo import show_image_info
        show_image_info(self, path, self.canvas.image)
        if was and self.playing:
            self.timer.start(int(self.interval * 1000))

    def open_webtoon(self):
        if not self.nav.images:
            return
        self.webtoon_requested.emit(list(self.nav.images), self.nav.ii)
        self.close()

    def _toggle_folder_osd(self, on):
        self.settings.setValue("osd/folder", on)
        self.apply_options()

    def back_to_browser(self):
        self.to_browser.emit(self.nav.current() or self.nav.folder)
        self.close()

    # ----------------------------------------------------------- comandi
    def do(self, aid):
        """Esegue un comando del registro dei tasti (shortcuts.VIEWER)."""
        if aid.startswith("rating_"):
            return self.set_rating(int(aid[7:]))
        if aid.startswith("label_"):
            return self.set_label(int(aid[6:]))
        if aid.startswith("sort_"):
            return self.sort_to(int(aid[5:]))
        from . import fileops
        acts = {
            "next": lambda: self.go(1), "prev": lambda: self.go(-1),
            "next_folder": lambda: self.go_folder(1), "prev_folder": lambda: self.go_folder(-1),
            "first": self.first, "last": self.last,
            "play": self.toggle_play, "stop": lambda: self.set_playing(False),
            "plus": lambda: self.change_interval(1) if self.slideshow_mode else self.zoom_step(1.25),
            "minus": lambda: self.change_interval(-1) if self.slideshow_mode else self.zoom_step(0.8),
            "pair": self.toggle_pair, "manga": self.toggle_manga, "fit_mode": self.cycle_fit,
            "zoom_toggle": self.toggle_zoom, "zoom_in": lambda: self.zoom_step(1.25),
            "zoom_out": lambda: self.zoom_step(0.8), "fullscreen": self.toggle_fullscreen,
            "info": self.toggle_info, "rotate_right": lambda: self.rotate("right"),
            "rotate_left": lambda: self.rotate("left"), "flip_h": lambda: self.rotate("flip_h"),
            "flip_v": lambda: self.rotate("flip_v"), "save_orientation": self.save_orientation,
            "loupe": self.toggle_loupe, "background": self.cycle_background,
            "histogram": self.toggle_hist, "pixel": self.toggle_pixel, "webtoon": self.open_webtoon,
            "edit": self.edit_current, "favorite": self.toggle_favorite,
            "delete": self.delete_current, "undo": self.undo, "rename": self.rename_current,
            "copy_image": lambda: fileops.copy_image(self.canvas.image),
            "image_info": self.image_info, "music": self.toggle_music,
            "video_audio": self.toggle_video_audio, "options": self.open_options,
            "volume_up": lambda: self.change_video_volume(5),
            "volume_down": lambda: self.change_video_volume(-5),
            "loop_a": self.set_loop_a, "loop_b": self.set_loop_b, "loop_clear": self.clear_loop,
            "to_browser": lambda: None if self.slideshow_mode else self.back_to_browser(),
            "close": lambda: self.back_to_browser() if self.slideshow_mode else self.close(),
        }
        f = acts.get(aid)
        if f:
            f()

    # -------------------------------------------------------------- input
    def keyPressEvent(self, e):
        if self.screensaver:
            self.close()
            return
        for k in shortcuts.event_keys(e):
            aid = self.keymap.get(k)
            if aid:
                self.do(aid)
                return
        super().keyPressEvent(e)

    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        dx = e.angleDelta().x()
        mods = e.modifiers()
        if not dy and not dx:
            return
        if mods & Qt.KeyboardModifier.ControlModifier:
            self.zoom_step(1.15 if dy > 0 else 1 / 1.15)
            return
        if mods & Qt.KeyboardModifier.ShiftModifier and self.canvas.loupe:
            self.canvas.loupe_mag = max(1.5, min(16.0, self.canvas.loupe_mag * (1.2 if (dy or dx) > 0 else 1 / 1.2)))
            self.settings.setValue("viewer/loupe_mag", self.canvas.loupe_mag)
            self.canvas.update()
            return
        if self.canvas._scrollable():
            step = self.canvas.height() * 0.15
            if mods & Qt.KeyboardModifier.ShiftModifier or (dx and not dy):
                self.canvas.scroll_by(step * (1 if (dx or dy) > 0 else -1), 0)
                return
            d = -1 if dy > 0 else 1
            if not self.canvas.at_edge(d):
                self.canvas.scroll_by(0, -step * d)
                return
            if self.go(d) and d < 0:
                self.canvas.scroll_to_end(bottom=True)
            return
        self.go(-1 if dy > 0 else 1)

    def mouseDoubleClickEvent(self, e):
        self.toggle_fullscreen()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if self.screensaver and t in (ev.Type.MouseButtonPress, ev.Type.MouseMove):
            pos = ev.globalPosition() if hasattr(ev, "globalPosition") else None
            if t == ev.Type.MouseButtonPress:
                self.close()
                return True
            if pos is not None:
                if self._ss_origin is None:
                    self._ss_origin = pos
                elif (pos - self._ss_origin).manhattanLength() > 12:
                    self.close()
                    return True
            return False
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

    # ------------------------------------------------------- menu contestuale
    def _act(self, menu, aid, text=None, slot=None, checkable=False, checked=False, enabled=True):
        k = shortcuts.native(self.settings, "viewer", aid, True) if aid else ""
        a = QAction((text or shortcuts.label("viewer", aid)) + (f"\t{k}" if k else ""), menu)
        a.setCheckable(checkable)
        if checkable:
            a.setChecked(checked)
        a.setEnabled(enabled)
        a.triggered.connect(slot or (lambda _=False, aid=aid: self.do(aid)))
        menu.addAction(a)
        return a

    def _context_menu(self, pos):
        if self.screensaver:
            self.close()
            return
        from . import fileops
        path = self.nav.current()
        real = bool(path) and not is_virtual(path)
        single = not self.pair
        c = self.canvas
        m = QMenu(self)
        self._act(m, "next", tr("Successiva"))
        self._act(m, "prev", tr("Precedente"))
        self._act(m, "next_folder")
        self._act(m, "prev_folder")
        m.addSeparator()

        sm = m.addMenu(tr("Slideshow"))
        self._act(sm, "play", tr("Ferma slideshow") if self.playing else tr("Avvia / riprendi slideshow"))
        self._act(sm, None, tr("Intervallo più lungo"), lambda: self.change_interval(1))
        self._act(sm, None, tr("Intervallo più corto"), lambda: self.change_interval(-1))
        sm.addSeparator()
        self._act(sm, "pair", tr("Due immagini affiancate"), checkable=True, checked=self.pair)
        self._act(sm, "manga", tr("Modalità manga, da destra a sinistra"), checkable=True,
                  checked=self.manga, enabled=self.pair)
        tm = sm.addMenu(tr("Transizione"))
        g = QActionGroup(tm)
        cur_t = self._st("slideshow/transition", "fade")
        for k in TRANSITIONS:
            a = self._act(tm, None, transition_name(k), lambda _=False, k=k: self.set_transition(k),
                          checkable=True, checked=cur_t == k)
            g.addAction(a)
        self._act(sm, "music", tr("Musica di sottofondo"), checkable=True,
                  checked=self.music is not None and self.music_on, enabled=bool(self._st("slideshow/music", "")))

        vm = m.addMenu(tr("Visualizzazione"))
        fm = vm.addMenu(tr("Adatta"))
        g = QActionGroup(fm)
        for k in FIT_MODES:
            a = self._act(fm, None, fit_mode_name(k), lambda _=False, k=k: self.set_fit(k),
                          checkable=True, checked=c.fit_mode == k and c.zoom is None, enabled=single)
            g.addAction(a)
        self._act(vm, "zoom_toggle", tr("Adatta / 100%"), enabled=single)
        self._act(vm, "zoom_in", enabled=single)
        self._act(vm, "zoom_out", enabled=single)
        vm.addSeparator()
        for aid in ("rotate_right", "rotate_left", "flip_h", "flip_v"):
            self._act(vm, aid, enabled=single and bool(path))
        self._act(vm, "save_orientation", enabled=single and real and not orient.is_identity(self.view_o)
                  and orient.can_save(path))
        vm.addSeparator()
        bm = vm.addMenu(tr("Sfondo"))
        g = QActionGroup(bm)
        for k in BACKGROUNDS:
            a = self._act(bm, None, background_name(k), lambda _=False, k=k: self.set_background(k),
                          checkable=True, checked=c.background == k)
            g.addAction(a)
        self._act(vm, "loupe", checkable=True, checked=c.loupe)
        self._act(vm, "histogram", checkable=True, checked=c.show_hist)
        self._act(vm, "pixel", checkable=True, checked=c.show_pixel)
        self._act(vm, "info", tr("Mostra informazioni"), checkable=True, checked=c.show_info)
        self._act(vm, None, tr("Mostra nome cartella al cambio"), self._toggle_folder_osd, checkable=True,
                  checked=c.style_["osd/folder"])
        self._act(vm, "fullscreen", checkable=True, checked=self.isFullScreen())
        self._act(vm, "webtoon", enabled=bool(self.nav.images))
        m.addSeparator()

        r, lb = library.get(path) if path else (0, 0)
        rm = m.addMenu(tr("Valutazione") + (f"  {stars(r)}" if r else ""))
        rm.setEnabled(bool(path))
        g = QActionGroup(rm)
        for i in range(6):
            a = self._act(rm, f"rating_{i}", (stars(i) if i else tr("Nessuna")), checkable=True, checked=r == i)
            g.addAction(a)
        lm = m.addMenu(tr("Etichetta"))
        lm.setEnabled(bool(path))
        g = QActionGroup(lm)
        for i, _name, color in library.LABELS:
            a = self._act(lm, f"label_{i}", library.label_name(i), checkable=True, checked=lb == i)
            a.setIcon(color_icon(color))
            g.addAction(a)
        self._act(m, "favorite", tr("Preferiti"), checkable=True,
                  checked=bool(path) and library.is_favorite(path), enabled=bool(path))
        cm = m.addMenu(tr("Aggiungi a raccolta"))
        cm.setEnabled(bool(path))
        for cid, _name, cnt in library.collections():
            self._act(cm, None, f"{library.display_name(cid)}  ({cnt})",
                      lambda _=False, cid=cid: self.add_to_collection(cid))
        cm.addSeparator()
        self._act(cm, None, tr("Nuova raccolta…"), lambda: self.add_to_collection(None))
        om = m.addMenu(tr("Smista in"))
        om.setEnabled(bool(path))
        mode = self.settings.value("sort/mode", "move")
        for i in range(1, 10):
            t = self.settings.value(f"sort/target{i}", "")
            if t:
                self._act(om, f"sort_{i}", (tr("Sposta in {name}", name=os.path.basename(t.rstrip("\\/")) or t)
                                             if mode == "move" else
                                             tr("Copia in {name}", name=os.path.basename(t.rstrip("\\/")) or t)))
        om.addSeparator()
        self._act(om, None, tr("Imposta le cartelle…"), lambda: self.open_options("sort"))
        m.addSeparator()

        fmn = m.addMenu(tr("File"))
        self._act(fmn, "edit", enabled=real and not codecs.is_video(path or ""))
        self._act(fmn, "rename", enabled=real)
        self._act(fmn, "copy_image", tr("Copia immagine"), enabled=c.image is not None)
        self._act(fmn, None, tr("Copia file"), lambda: fileops.clipboard_set([path]), enabled=real)
        ow = fmn.addMenu(tr("Apri con"))
        ow.setEnabled(real)
        ow.addAction(tr("Programma predefinito"), lambda: fileops.open_default(path))
        ow.addAction(tr("Scegli un programma…"), lambda: fileops.open_with(path))
        ow.addAction(tr("Modifica con Paint"), lambda: fileops.edit_with_paint(path))
        self._act(fmn, None, tr("Imposta come sfondo del desktop"),
                  lambda: fileops.set_wallpaper(self, path), enabled=bool(path))
        self._act(fmn, None, tr("Stampa…"), lambda: fileops.print_images(self, [path]), enabled=bool(path))
        fmn.addSeparator()
        self._act(fmn, None, tr("Mostra in Esplora risorse"),
                  lambda: show_in_explorer(path.split("|", 1)[0]), enabled=bool(path))
        self._act(fmn, None, tr("Copia percorso"),
                  lambda: fileops.copy_as_path([path.replace("|", os.sep)]), enabled=bool(path))
        self._act(fmn, "image_info", tr("Informazioni immagine (EXIF)…"), enabled=bool(path))
        if self.video is not None:
            self._act(m, "video_audio", checkable=True, checked=not self.video.muted())
            if self._loop_allowed():
                self._act(m, "loop_a")
                self._act(m, "loop_b")
                self._act(m, "loop_clear", enabled=self.video.loop_a is not None or self.video.loop_b is not None)
        m.addSeparator()
        kind = undo_manager.last_kind()
        self._act(m, "undo", {"delete": tr("Annulla eliminazione"), "move": tr("Annulla spostamento"),
                              "copy": tr("Annulla copia")}.get(kind, tr("Annulla")), enabled=kind is not None)
        self._act(m, "delete", tr("Elimina"), enabled=real)
        m.addSeparator()
        self._act(m, "options", tr("Opzioni…"))
        self._act(m, None, tr("Tasti di scelta rapida…"), self.open_shortcuts)
        if self.slideshow_mode:
            self._act(m, "close", tr("Esci dallo slideshow"))
            self._act(m, None, tr("Chiudi"), self.close)
        else:
            self._act(m, "to_browser", tr("Torna al browser"))
            self._act(m, "close", tr("Chiudi"))
        m.exec(pos)

    def closeEvent(self, e):
        self.timer.stop()
        self._stop_movie()
        if self.music is not None:
            self.music.stop()
            self.music = None
        self.canvas.release_gpu()
        try:
            self.loader.ready.disconnect(self._on_ready)
        except (RuntimeError, TypeError):
            pass
        self.closed.emit(self.nav.current() or "")
        super().closeEvent(e)
