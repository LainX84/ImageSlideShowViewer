"""Caricamento immagini in background con piccola cache (precaricamento slideshow)."""
from collections import OrderedDict

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from . import codecs, gpu, gpudecode
from .archive import is_virtual, read_bytes, stat_any
from .worker import BgWorker


_SKIPPED = "__skipped__"
VIDEO = "__video__"      # i video non passano dal caricatore: li riproduce video.py


def _read(path, wanted):
    if path not in wanted:  # l'utente è già andato oltre: non perdere tempo a decodificare
        return path, QImage(), _SKIPPED
    if codecs.is_video(path):
        return path, QImage(), VIDEO
    img = _read_gpu(path)
    if img is not None:
        return path, gpu.prepare_image(img), ""
    img, err = codecs.read_qimage(path)   # Qt, Pillow (HEIC/AVIF/JXL) o anteprima RAW
    return path, gpu.prepare_image(img), err


def _read_gpu(path):
    """JPEG grandi decodificati dalla GPU NVIDIA (se attivato e disponibile)."""
    try:
        if not gpudecode.wants(path, stat_any(path)[1]):
            return None
        data = read_bytes(path) if is_virtual(path) else path
    except Exception:  # noqa: BLE001
        return None
    return gpudecode.decode(data)


class ImageLoader(QObject):
    ready = Signal(str, QImage, str)  # path, immagine, errore

    def __init__(self, cache_size=10, parent=None):
        super().__init__(parent)
        self.worker = BgWorker(2, self)
        self.cache = OrderedDict()
        self.errors = {}
        self.pending = set()
        self.cache_size = cache_size
        self.max_bytes = 350 * 1024 * 1024
        self.wanted = set()

    def get(self, path):
        img = self.cache.get(path)
        if img is not None:
            self.cache.move_to_end(path)
        return img

    def error(self, path):
        return self.errors.get(path)

    def request(self, path, keep_wanted=False):
        """Chiede l'immagine; con keep_wanted=False le richieste precedenti
        ancora in coda vengono scartate (scorrimento veloce)."""
        if not path:
            return
        if not keep_wanted:
            self.wanted.clear()  # stesso oggetto: i lavori in coda vedono la modifica
        self.wanted.add(path)
        if path in self.cache or path in self.pending:
            return
        self.pending.add(path)
        self.worker.submit(_read, self._on_loaded, path, self.wanted)

    def forget(self, path):
        self.cache.pop(path, None)
        self.errors.pop(path, None)

    def _on_loaded(self, res):
        if isinstance(res, Exception):
            return
        path, img, err = res
        self.pending.discard(path)
        if err == _SKIPPED:
            return
        if err:
            self.errors[path] = err
        else:
            self.cache[path] = img
            # limite sia per numero sia per memoria (foto grandi = ~50 MB l'una)
            while len(self.cache) > 2 and (
                    len(self.cache) > self.cache_size or
                    sum(i.sizeInBytes() for i in self.cache.values()) > self.max_bytes):
                self.cache.popitem(last=False)
        self.ready.emit(path, img, err)
