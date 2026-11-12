"""Immagini animate (GIF e WebP), anche dentro gli archivi ZIP/CBZ.

probe() dice se un file è animato (risultato in cache: per le GIF Qt deve scorrere
tutto il file per contare i fotogrammi); make_movie() crea il QMovie che lo riproduce.
"""
import os
import threading
from collections import OrderedDict

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QMovie

from .archive import image_reader, is_virtual, read_bytes, stat_any

ANIM_EXTS = {".gif", ".webp"}

_lock = threading.Lock()
_cache = OrderedDict()      # (percorso, mtime, dimensione) -> QSize oppure None
_MAX = 2000


def maybe_animated(path):
    """Controllo veloce, solo sull'estensione."""
    return bool(path) and os.path.splitext(path)[1].lower() in ANIM_EXTS


def probe(path):
    """Dimensioni dell'immagine se è animata (più di un fotogramma), altrimenti None.
    Si può chiamare da un thread in background."""
    if not maybe_animated(path):
        return None
    try:
        mt, size = stat_any(path)
    except OSError:
        return None
    key = (path, mt, size)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    res = None
    try:
        r, _keep = image_reader(path)
        if r.supportsAnimation() and r.imageCount() != 1:
            # imageCount() = 0 vuol dire "non si sa": si controlla se esiste un 2° fotogramma
            n = r.imageCount()
            if n > 1 or (n == 0 and r.jumpToImage(1)):
                s = r.size()
                res = QSize(s) if s.isValid() else QSize()
    except Exception:  # noqa: BLE001 - file danneggiato, archivio sparito...
        res = None
    with _lock:
        _cache[key] = res
        while len(_cache) > _MAX:
            _cache.popitem(last=False)
    return res


def is_animated(path):
    return probe(path) is not None


def make_movie(path, parent=None):
    """QMovie per un file normale o per un'immagine dentro un archivio (None se non va)."""
    if not is_virtual(path):
        m = QMovie(path, parent=parent)
    else:
        try:
            data = QByteArray(read_bytes(path))
        except Exception:  # noqa: BLE001
            return None
        m = QMovie(parent=parent)
        buf = QBuffer(m)            # il buffer vive quanto il filmato
        buf.setData(data)
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        m._keep = (buf, data)       # noqa: SLF001 - riferimento Python ai dati
        m.setFormat(os.path.splitext(path)[1].lower().lstrip(".").encode())
        m.setDevice(buf)
    if not m.isValid():
        m.deleteLater()
        return None
    return m


def fit_size(size, box):
    """size ridotta (mai ingrandita) per stare dentro un quadrato box×box."""
    if not size.isValid() or (size.width() <= box and size.height() <= box):
        return QSize()
    return size.scaled(box, box, Qt.AspectRatioMode.KeepAspectRatio)
