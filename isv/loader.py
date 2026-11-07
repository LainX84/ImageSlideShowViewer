"""Caricamento immagini in background con piccola cache (precaricamento slideshow)."""
from collections import OrderedDict

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .archive import image_reader
from .worker import BgWorker


_SKIPPED = "__skipped__"


def _read(path, wanted):
    if path not in wanted:  # l'utente è già andato oltre: non perdere tempo a decodificare
        return path, QImage(), _SKIPPED
    try:
        r, _keep = image_reader(path)
    except Exception as e:  # noqa: BLE001 - archivio danneggiato, file sparito...
        return path, QImage(), str(e) or "Impossibile leggere il file"
    r.setAutoTransform(True)  # rispetta l'orientamento EXIF
    img = r.read()
    err = "" if not img.isNull() else (r.errorString() or "Formato non leggibile")
    return path, img, err


class ImageLoader(QObject):
    ready = Signal(str, QImage, str)  # path, immagine, errore

    def __init__(self, cache_size=6, parent=None):
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
