"""Prestazioni: decodifica multithread e precaricamento delle immagini vicine.

  * Decodifica multithread: AVIF (libavif/dav1d), HEIC (libheif) e JPEG XL (libjxl)
    usano tutti i core per una singola immagine; in più il caricatore decodifica
    più immagini in parallelo (quella mostrata + quelle precaricate) e la
    conversione in blocco lavora su più file contemporaneamente.
    JPEG, PNG e WebP (decoder di Qt) restano a un thread per immagine, ma
    beneficiano del parallelismo tra immagini diverse.
  * Precaricamento: dopo aver mostrato un'immagine si decodificano in background
    le successive (e alcune precedenti), così il cambio è istantaneo.
"""
import os
import weakref

CPU = os.cpu_count() or 4

DEFAULT_AHEAD = 2
DEFAULT_BEHIND = 1
MAX_AHEAD = 6
MAX_BEHIND = 3

_multithread = True
_prefetch = True
_ahead = DEFAULT_AHEAD
_behind = DEFAULT_BEHIND
_loaders = weakref.WeakSet()


def register(loader):
    """I caricatori registrati si riconfigurano quando cambiano le opzioni."""
    _loaders.add(loader)


def apply(settings):
    """Legge le opzioni e le rende attive (all'avvio e dopo le Opzioni)."""
    global _multithread, _prefetch, _ahead, _behind
    _multithread = settings.value("perf/multithread", True, type=bool)
    _prefetch = settings.value("perf/prefetch", True, type=bool)
    _ahead = max(1, min(MAX_AHEAD, settings.value("perf/prefetch_ahead", DEFAULT_AHEAD, type=int)))
    _behind = max(0, min(MAX_BEHIND, settings.value("perf/prefetch_behind", DEFAULT_BEHIND, type=int)))
    from . import codecs
    codecs.set_decode_threads(0 if _multithread else 1)
    for ld in list(_loaders):
        try:
            ld.configure()
        except RuntimeError:     # oggetto Qt già distrutto
            pass


def multithread():
    return _multithread


def loader_threads():
    """Immagini decodificate in parallelo dal visualizzatore."""
    if not _multithread:
        return 1
    return max(2, min(4, CPU // 2))


def batch_threads():
    """File elaborati in parallelo dalla conversione in blocco."""
    if not _multithread:
        return 1
    return max(1, min(16, CPU - 1))


def prefetch_offsets(step=1):
    """Spostamenti da precaricare rispetto all'immagine attuale, dal più vicino.
    step=2 con 2 immagini affiancate (si avanza di una coppia alla volta)."""
    if not _prefetch:
        return []
    out = []
    for k in range(1, _ahead + 1):
        out.extend(step * (k - 1) + step + i for i in range(step))
        if k <= _behind:
            out.extend(-(step * (k - 1) + 1 + i) for i in range(step))
    return out


def cache_size():
    """Quante immagini decodificate tenere in memoria."""
    return max(10, 2 * (_ahead + _behind) + 4)
