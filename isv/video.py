"""Video brevi (MP4, WebM, MOV…) e musica dello slideshow, con QtMultimedia.

  * VideoPlayer: riproduce un video nel canvas del visualizzatore, fotogramma per
    fotogramma (passa da QVideoSink, quindi funziona sia con il disegno CPU sia GPU).
  * VideoThumbnailer: estrae un fotogramma per le miniature del browser (uno alla volta).
  * SlideshowMusic: musica di sottofondo da un file o da una cartella.
"""
import os
import random

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from .archive import is_virtual

MUSIC_EXTS = {".mp3", ".ogg", ".oga", ".flac", ".wav", ".m4a", ".aac", ".opus", ".wma"}


def _mm():
    from PySide6 import QtMultimedia
    return QtMultimedia


def _perceived(v):
    """Volume 0–100 su scala percepita (logaritmica) → valore lineare per QAudioOutput."""
    x = max(0, min(100, v)) / 100
    try:
        A = _mm().QtAudio
        return A.convertVolume(x, A.VolumeScale.LogarithmicVolumeScale, A.VolumeScale.LinearVolumeScale)
    except AttributeError:          # Qt più vecchio
        return x * x


class VideoPlayer(QObject):
    """Riproduce path; frame(QImage) a ogni fotogramma."""
    frame = Signal(object)
    failed = Signal(str)
    position_changed = Signal(int)      # ms
    duration_changed = Signal(int)      # ms

    def __init__(self, path, muted=True, volume=100, parent=None):
        super().__init__(parent)
        mm = _mm()
        self.path = path
        self._volume = max(0, min(100, int(volume)))
        self.player = mm.QMediaPlayer(self)
        self.audio = None           # l'uscita audio si crea solo se serve (video muto = nessuna)
        if not muted:
            self.set_muted(False)
        self.sink = mm.QVideoSink(self)
        self.player.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._on_frame)
        self.player.errorOccurred.connect(lambda _e, s: self.failed.emit(s or "video"))
        self.player.setLoops(mm.QMediaPlayer.Loops.Infinite)
        self.player.positionChanged.connect(self._on_position)
        self.loop_a = None              # ciclo A-B in ms (None = non impostato)
        self.loop_b = None
        self.player.durationChanged.connect(lambda ms: self.duration_changed.emit(int(ms)))
        self.user_paused = False
        self._buf = None
        if is_virtual(path):
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            from .archive import read_bytes
            self._data = QByteArray(read_bytes(path))
            self._buf = QBuffer(self)
            self._buf.setData(self._data)
            self._buf.open(QIODevice.OpenModeFlag.ReadOnly)
            self.player.setSourceDevice(self._buf, QUrl(path.rsplit("/", 1)[-1]))
        else:
            self.player.setSource(QUrl.fromLocalFile(path))

    def _on_frame(self, f):
        if f.isValid():
            img = f.toImage()
            if not img.isNull():
                self.frame.emit(img)

    def play(self):
        self.player.play()

    def pause(self):
        self.player.pause()

    def is_playing(self):
        return self.player.playbackState() == _mm().QMediaPlayer.PlaybackState.PlayingState

    def set_muted(self, m):
        if self.audio is None:
            if m:
                return
            self.audio = _mm().QAudioOutput(self)
            self.audio.setVolume(_perceived(self._volume))
            playing = self.is_playing()
            pos = self.player.position()
            self.player.setAudioOutput(self.audio)
            if playing:                     # alcuni backend agganciano l'audio solo dal riavvio
                self.player.setPosition(pos)
                self.player.play()
        self.audio.setMuted(m)

    def muted(self):
        return self.audio is None or self.audio.isMuted()

    def volume(self):
        return self._volume

    def set_volume(self, v):
        """0–100: volume di questa applicazione (non tocca quello del sistema)."""
        self._volume = max(0, min(100, int(v)))
        if self.audio is not None:
            self.audio.setVolume(_perceived(self._volume))

    def _on_position(self, ms):
        ms = int(ms)
        a, b = self.loop_a, self.loop_b
        if a is not None and b is not None and (ms >= b or ms < a - 250):
            self.player.setPosition(a)
            ms = a
        self.position_changed.emit(ms)

    def set_loop(self, a, b):
        self.loop_a, self.loop_b = a, b
        if a is not None and b is not None:
            pos = self.position()
            if pos < a or pos >= b:
                self.player.setPosition(a)

    def position(self):
        return int(self.player.position())

    def duration(self):
        return int(self.player.duration())

    def seekable(self):
        return self.player.isSeekable()

    def seek(self, ms):
        self.player.setPosition(max(0, min(int(ms), max(0, self.duration()))))

    def stop(self):
        try:
            self.sink.videoFrameChanged.disconnect(self._on_frame)
        except (RuntimeError, TypeError):
            pass
        self.player.stop()
        self.player.setSource(QUrl())
        self.deleteLater()


class VideoThumbnailer(QObject):
    """Fotogramma rappresentativo (a ~10% della durata, max 2 s) dei video in coda."""
    done = Signal(str, object)          # percorso, QImage (nulla se non riuscito)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = []
        self.cur = None
        self.player = None
        self.timeout = QTimer(self, singleShot=True, interval=6000)
        self.timeout.timeout.connect(lambda: self._finish(None))

    def request(self, path):
        if path != self.cur and path not in self.queue:
            self.queue.append(path)
        if self.cur is None:
            QTimer.singleShot(0, self._next)

    def clear(self):
        self.queue.clear()

    def _ensure(self):
        if self.player is None:
            mm = _mm()
            self.player = mm.QMediaPlayer(self)    # senza uscita audio: muto
            self.sink = mm.QVideoSink(self)
            self.player.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self._on_frame)
            self.player.mediaStatusChanged.connect(self._on_status)
            self.player.errorOccurred.connect(lambda *_: self._finish(None))

    def _next(self):
        if self.cur is not None or not self.queue:
            return
        self.cur = self.queue.pop(0)
        if is_virtual(self.cur):
            self._finish(None)
            return
        self._ensure()
        self._target = None
        self.timeout.start()
        self.player.setSource(QUrl.fromLocalFile(self.cur))

    def _on_status(self, st):
        S = _mm().QMediaPlayer.MediaStatus
        if self.cur is None:
            return
        if st == S.LoadedMedia and self._target is None:
            dur = self.player.duration()
            self._target = min(2000, dur // 10) if dur > 0 else 0
            if self._target:
                self.player.setPosition(self._target)
            self.player.play()
        elif st in (S.InvalidMedia,):
            self._finish(None)

    def _on_frame(self, f):
        if self.cur is None or self._target is None or not f.isValid():
            return
        if self._target and f.startTime() >= 0 and f.startTime() // 1000 < self._target - 400:
            return      # fotogramma prima del salto
        img = f.toImage()
        if not img.isNull():
            self._finish(img)

    def _finish(self, img):
        path, self.cur = self.cur, None
        self.timeout.stop()
        if self.player is not None:
            self.player.pause()
            self.player.setSource(QUrl())
        if path:
            from PySide6.QtGui import QImage
            self.done.emit(path, img if img is not None else QImage())
        QTimer.singleShot(0, self._next)


class SlideshowMusic(QObject):
    """Musica di sottofondo dello slideshow: un file oppure tutti i brani di una cartella."""

    def __init__(self, source, shuffle=True, volume=60, parent=None):
        super().__init__(parent)
        self.tracks = []
        if source and os.path.isdir(source):
            for root, _d, files in os.walk(source):
                self.tracks += [os.path.join(root, f) for f in sorted(files)
                                if os.path.splitext(f)[1].lower() in MUSIC_EXTS]
            if shuffle:
                random.shuffle(self.tracks)
        elif source and os.path.isfile(source):
            self.tracks = [source]
        self.i = 0
        self.player = None
        if not self.tracks:
            return
        mm = _mm()
        self.player = mm.QMediaPlayer(self)
        self.audio = mm.QAudioOutput(self)
        self.audio.setVolume(max(0, min(100, volume)) / 100)
        self.player.setAudioOutput(self.audio)
        self.player.mediaStatusChanged.connect(self._status)
        self.player.errorOccurred.connect(lambda *_: QTimer.singleShot(300, self.next))
        if len(self.tracks) == 1:
            self.player.setLoops(mm.QMediaPlayer.Loops.Infinite)
        self.player.setSource(QUrl.fromLocalFile(self.tracks[0]))

    def ok(self):
        return self.player is not None

    def _status(self, st):
        if st == _mm().QMediaPlayer.MediaStatus.EndOfMedia and len(self.tracks) > 1:
            self.next()

    def next(self):
        if not self.ok():
            return
        self.i = (self.i + 1) % len(self.tracks)
        self.player.setSource(QUrl.fromLocalFile(self.tracks[self.i]))
        self.player.play()

    def title(self):
        return os.path.splitext(os.path.basename(self.tracks[self.i]))[0] if self.ok() else ""

    def play(self):
        if self.ok():
            self.player.play()

    def pause(self):
        if self.ok():
            self.player.pause()

    def stop(self):
        if self.ok():
            self.player.stop()
        self.deleteLater()
