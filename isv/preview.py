"""Pannello anteprima del browser: l'immagine selezionata in grande, con i dati
principali. Anima GIF / WebP e riproduce (muti) i video."""
import os
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from . import anim, codecs, library
from .archive import stat_any
from .canvas import Canvas
from .i18n import tr
from .loader import ImageLoader
from .utils import human_size


class PreviewPanel(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.canvas = Canvas(self)
        self.canvas.style_["osd/messages"] = False
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info.setContentsMargins(6, 4, 6, 6)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.info)
        self.loader = ImageLoader(cache_size=4, parent=self)
        self.loader.ready.connect(self._ready)
        self.path = None
        self.movie = None
        self.video = None
        self.setMinimumWidth(200)
        self.setMinimumHeight(160)
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self._load)
        self._next = None

    def show_path(self, path):
        self._next = path
        self._timer.start()

    def _stop(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        if self.video is not None:
            self.video.stop()
            self.video = None

    def _load(self):
        path = self._next
        if path == self.path:
            return
        self._stop()
        self.path = path
        if not path:
            self.canvas.set_message("")
            self.info.setText("")
            return
        self._info()
        animate = self.settings.value("browser/animate_thumbs", True, type=bool)
        if codecs.is_video(path):
            try:
                from .video import VideoPlayer
                self.video = VideoPlayer(path, muted=True, parent=self)
                self.video.frame.connect(lambda img, v=self.video: self._vframe(v, img))
                self.video.play()
            except Exception:  # noqa: BLE001
                self.canvas.set_message(tr("Video non riproducibile"))
            return
        if animate and anim.maybe_animated(path) and anim.is_animated(path):
            m = anim.make_movie(path, self)
            if m is not None:
                self.movie = m
                self._first = True
                m.frameChanged.connect(self._mframe)
                m.start()
                return
        img = self.loader.get(path)
        if img is not None:
            self.canvas.set_image(img)
        else:
            self.canvas.set_message("…")
            self.loader.request(path)

    def _mframe(self, _n):
        if self.movie is not None:
            self.canvas.set_image(self.movie.currentImage(), keep_view=not self._first)
            self._first = False

    def _vframe(self, v, img):
        if v is self.video:
            self.canvas.set_image(img, keep_view=True)

    def _ready(self, path, img, err):
        if path != self.path or self.movie is not None or self.video is not None:
            return
        if err:
            self.canvas.set_message(err)
        else:
            self.canvas.set_image(img)
            self._info(img)

    def _info(self, img=None):
        p = self.path
        try:
            mt, sz = stat_any(p)
            parts = [human_size(sz), time.strftime(tr("%d/%m/%Y %H:%M"), time.localtime(mt))]
        except OSError:
            parts = []
        if img is not None and not img.isNull():
            parts.insert(0, f"{img.width()} × {img.height()}")
        r, lb = library.get(p)
        extra = ("★" * r if r else "") + (("  ● " + library.label_name(lb)) if lb else "")
        if library.is_favorite(p):
            extra += "  ♥"
        self.info.setText(f"<b>{os.path.basename(p.split('|')[-1])}</b><br>{'  ·  '.join(parts)}"
                          + (f"<br>{extra}" if extra else ""))

    def refresh(self):
        if self.path:
            self._info(self.canvas.image)

    def hideEvent(self, e):
        self._stop()
        self.path = None
        super().hideEvent(e)
