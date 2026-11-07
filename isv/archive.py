"""Archivi ZIP/CBZ trattati come cartelle.

Un'immagine dentro un archivio ha un percorso "virtuale":
    C:\\Manga\\Volume 1.cbz|capitolo 1/001.jpg
Il carattere '|' non è ammesso nei nomi di file di Windows, quindi non crea ambiguità.
"""
import os
import threading
import zipfile
from collections import OrderedDict

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImageReader

SEP = "|"
ARCHIVE_EXTS = {".zip", ".cbz"}

_lock = threading.Lock()
_zips = OrderedDict()      # percorso -> (mtime, ZipFile, lock)
_members = OrderedDict()   # (percorso, mtime, size) -> [ZipInfo immagini ordinate]
MAX_OPEN = 8
MAX_LISTS = 256


def is_archive(path):
    return os.path.splitext(path)[1].lower() in ARCHIVE_EXTS


def is_virtual(path):
    return bool(path) and SEP in path


def split(vpath):
    archive, member = vpath.split(SEP, 1)
    return archive, member


def parent_of(path):
    """Cartella (o archivio) che contiene path."""
    if is_virtual(path):
        return split(path)[0]
    return os.path.dirname(path)


def stat_any(path):
    """(mtime, size) per file reali e immagini dentro archivi."""
    if is_virtual(path):
        a, m = split(path)
        st = os.stat(a)
        for zi in image_members(a):
            if zi.filename == m:
                return st.st_mtime, zi.file_size
        return st.st_mtime, 0
    st = os.stat(path)
    return st.st_mtime, st.st_size


def _open(path):
    st = os.stat(path)
    with _lock:
        hit = _zips.get(path)
        if hit and hit[0] == st.st_mtime:
            _zips.move_to_end(path)
            return hit[1], hit[2]
        if hit:
            try:
                hit[1].close()
            except Exception:  # noqa: BLE001
                pass
        z = zipfile.ZipFile(path)
        entry = (st.st_mtime, z, threading.Lock())
        _zips[path] = entry
        while len(_zips) > MAX_OPEN:
            _p, (_m, old, _l) = _zips.popitem(last=False)
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        return z, entry[2]


def image_members(path):
    """Immagini contenute nell'archivio, in ordine naturale (sottocartelle comprese)."""
    from .utils import is_image, natural_key
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (path, st.st_mtime, st.st_size)
    with _lock:
        hit = _members.get(key)
        if hit is not None:
            _members.move_to_end(key)
            return hit
    try:
        z, zl = _open(path)
        with zl:
            infos = z.infolist()
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
        infos = []
    imgs = [zi for zi in infos
            if not zi.is_dir() and is_image(zi.filename)
            and not os.path.basename(zi.filename).startswith(".")
            and "__MACOSX" not in zi.filename]
    imgs.sort(key=lambda zi: natural_key(zi.filename))
    with _lock:
        _members[key] = imgs
        while len(_members) > MAX_LISTS:
            _members.popitem(last=False)
    return imgs


def has_images(path):
    return bool(image_members(path))


def list_items(path, sort="name", reverse=False):
    from .utils import FileItem
    try:
        mt = os.stat(path).st_mtime
    except OSError:
        return []
    items = []
    for zi in image_members(path):
        try:
            import time
            zmt = time.mktime(zi.date_time + (0, 0, -1))
        except (OverflowError, ValueError):
            zmt = mt
        items.append(FileItem(path + SEP + zi.filename, os.path.basename(zi.filename),
                              zi.file_size, zmt))
    if sort == "date":
        items.sort(key=lambda i: i.mtime)
    elif sort == "size":
        items.sort(key=lambda i: i.size)
    # "name": già in ordine naturale per percorso interno
    if reverse:
        items.reverse()
    return items


def read_bytes(vpath):
    a, m = split(vpath)
    z, zl = _open(a)
    with zl:
        return z.read(m)


def image_reader(path):
    """QImageReader per un file normale o per un'immagine in un archivio.
    Restituisce (reader, keepalive): tenere keepalive finché si legge."""
    if not is_virtual(path):
        return QImageReader(path), None
    data = QByteArray(read_bytes(path))
    buf = QBuffer()
    buf.setData(data)
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    fmt = os.path.splitext(path)[1].lower().lstrip(".")
    fmt = {"jpg": "jpeg", "jpe": "jpeg", "jfif": "jpeg", "tif": "tiff"}.get(fmt, fmt)
    r = QImageReader(buf, fmt.encode())
    r.setDecideFormatFromContent(True)
    return r, (buf, data)
