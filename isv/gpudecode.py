"""Decodifica JPEG sulla GPU NVIDIA con nvImageCodec (nvJPEG, CUDA) – facoltativa.

Serve solo con schede NVIDIA. Le librerie si scaricano dal programma (proposta
all'avvio, oppure Opzioni → Animazioni e GPU: vedi nvsupport.py) o con
    pip install "nvidia-nvimgcodec-cu12[nvjpeg]" numpy
Se mancano, o se un file non si decodifica, si usa come sempre il decoder di Qt.
Conviene soprattutto con foto JPEG molto grandi (20+ megapixel); per le miniature
non serve, perché Qt le decodifica già a risoluzione ridotta.
"""
import os
import threading

from PySide6.QtGui import QImage

JPEG_EXTS = {".jpg", ".jpeg", ".jpe", ".jfif"}
MIN_BYTES = 512 * 1024      # sotto questa dimensione la CPU è già più veloce

_lock = threading.Lock()
_init_lock = threading.Lock()
_decoder = None
_params = None
_state = None               # None = non ancora provato, True = pronto, str = errore
_enabled = False


def set_enabled(on):
    global _enabled
    _enabled = bool(on)


def is_enabled():
    return _enabled and available()


def _init():
    """Carica nvImageCodec (una volta sola). Ritorna True oppure il motivo del fallimento."""
    if _state is not None:
        return _state
    with _init_lock:
        if _state is None:
            _load()
    return _state


def reset():
    """Dopo un'installazione: si riprova a caricare le librerie."""
    global _decoder, _params, _state
    with _init_lock:
        _decoder, _params, _state = None, None, None


def _load():
    global _decoder, _params, _state
    try:
        from . import nvsupport
        nvsupport.activate()        # librerie scaricate dal programma, se ci sono
    except Exception:  # noqa: BLE001
        pass
    try:
        import numpy  # noqa: F401
        from nvidia import nvimgcodec
    except Exception:  # noqa: BLE001
        _state = "missing"
        return
    try:
        B = nvimgcodec.BackendKind
        try:
            _decoder = nvimgcodec.Decoder(backends=[
                nvimgcodec.Backend(B.GPU_ONLY), nvimgcodec.Backend(B.HYBRID_CPU_GPU)])
        except Exception:  # noqa: BLE001 - versioni con firma diversa
            _decoder = nvimgcodec.Decoder()
        try:
            _params = nvimgcodec.DecodeParams(apply_exif_orientation=True)
        except Exception:  # noqa: BLE001
            _params = None
        _state = True
    except Exception as e:  # noqa: BLE001 - niente GPU NVIDIA / driver troppo vecchio
        _decoder = None
        _state = str(e) or e.__class__.__name__


def available():
    return _init() is True


def status():
    """Testo per le opzioni."""
    from .i18n import tr
    st = _init()
    if st is True:
        return tr("nvImageCodec pronto (decodifica JPEG su GPU NVIDIA)")
    if st == "missing":
        from . import nvsupport
        if nvsupport.supported():
            return tr("Non installato: usa «Installa» qui sopra")
        return tr("Non disponibile su questo sistema")
    return tr("Non disponibile: {why}", why=st)


def wants(path, size=None):
    if not _enabled or os.path.splitext(path)[1].lower() not in JPEG_EXTS:
        return False
    if size is not None and size < MIN_BYTES:
        return False
    return available()


def decode(data_or_path):
    """bytes (o percorso) -> QImage RGB888, oppure None se non riesce."""
    if not available():
        return None
    try:
        import numpy as np
        with _lock:   # un solo decodificatore condiviso dai thread di caricamento
            if isinstance(data_or_path, (bytes, bytearray)):
                img = (_decoder.decode(bytes(data_or_path), params=_params) if _params is not None
                       else _decoder.decode(bytes(data_or_path)))
            else:
                img = (_decoder.read(data_or_path, params=_params) if _params is not None
                       else _decoder.read(data_or_path))
            if img is None:
                return None
            host = img.cpu() if hasattr(img, "cpu") else img
            arr = np.ascontiguousarray(np.asarray(host), dtype=np.uint8)
    except Exception:  # noqa: BLE001 - JPEG particolare (CMYK, danneggiato...): ci pensa Qt
        return None
    if arr.ndim == 2:
        h, w = arr.shape
        q = QImage(arr.data, w, h, w, QImage.Format.Format_Grayscale8)
    elif arr.ndim == 3 and arr.shape[2] in (3, 4):
        h, w, c = arr.shape
        fmt = QImage.Format.Format_RGB888 if c == 3 else QImage.Format.Format_RGBA8888
        q = QImage(arr.data, w, h, w * c, fmt)
    else:
        return None
    return q.copy()   # copia nella memoria di Qt: arr può essere liberato
