"""Rotazioni e specchi: a video (visualizzatore) e salvati nel file.

Un orientamento è (k, specchio) = ruota di k×90° in senso orario, poi (se specchio)
specchia in orizzontale: le 8 combinazioni corrispondono agli 8 valori EXIF.

Per i JPEG il salvataggio è SENZA PERDITA: si cambia solo il tag "Orientation" dei
dati EXIF, i pixel restano identici. Se il JPEG non ha il tag (o per gli altri
formati) l'immagine viene ruotata davvero e salvata di nuovo (PNG/TIFF/BMP senza
perdita, JPEG/WebP/HEIC/AVIF/JXL con qualità 95, dati EXIF conservati).
"""
import os
import struct

from PySide6.QtGui import QTransform

# matrici 2×2 (x verso destra, y verso il basso) dei valori EXIF
_EXIF_M = {1: (1, 0, 0, 1), 2: (-1, 0, 0, 1), 3: (-1, 0, 0, -1), 4: (1, 0, 0, -1),
           5: (0, 1, 1, 0), 6: (0, -1, 1, 0), 7: (0, -1, -1, 0), 8: (0, 1, -1, 0)}
_ROT90 = (0, -1, 1, 0)
_MIRROR = (-1, 0, 0, 1)
IDENTITY = (0, False)


def _mul(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3])


def matrix(o):
    k, mirror = o
    m = (1, 0, 0, 1)
    for _ in range(k % 4):
        m = _mul(_ROT90, m)
    if mirror:
        m = _mul(_MIRROR, m)
    return m


def from_matrix(m):
    for k in range(4):
        for mir in (False, True):
            if matrix((k, mir)) == m:
                return (k, mir)
    return IDENTITY


def compose(o, op):
    """Applica op ("right", "left", "180", "flip_h", "flip_v") dopo l'orientamento o."""
    m = matrix(o)
    ops = {"right": _ROT90, "left": _mul(_ROT90, _mul(_ROT90, _ROT90)),
           "180": _mul(_ROT90, _ROT90), "flip_h": _MIRROR, "flip_v": (1, 0, 0, -1)}
    return from_matrix(_mul(ops[op], m))


def is_identity(o):
    return from_matrix(matrix(o)) == IDENTITY


def apply(img, o):
    """QImage trasformata secondo l'orientamento o."""
    if img is None or img.isNull() or is_identity(o):
        return img
    k, mirror = from_matrix(matrix(o))
    if k:
        img = img.transformed(QTransform().rotate(90 * k))
    if mirror:
        img = img.mirrored(True, False)
    return img


def exif_value(o):
    m = matrix(o)
    for v, mm in _EXIF_M.items():
        if mm == m:
            return v
    return 1


def orientation_of_exif(v):
    return from_matrix(_EXIF_M.get(v, _EXIF_M[1]))


def describe(o):
    from .i18n import tr
    k, mirror = from_matrix(matrix(o))
    parts = []
    if k:
        parts.append({1: tr("ruotata 90° a destra"), 2: tr("ruotata 180°"), 3: tr("ruotata 90° a sinistra")}[k])
    if mirror:
        parts.append(tr("specchiata"))
    return ", ".join(parts)


# ------------------------------------------------------------ JPEG senza perdita
def _jpeg_orientation_offset(data):
    """(posizione del valore del tag Orientation, endianness, valore) nel JPEG, o None."""
    if data[:2] != b"\xff\xd8":
        return None
    p = 2
    while p + 4 <= len(data):
        if data[p] != 0xFF:
            return None
        marker = data[p + 1]
        if marker in (0xD9, 0xDA):       # fine o inizio dei dati immagine
            return None
        seglen = struct.unpack(">H", data[p + 2:p + 4])[0]
        if marker == 0xE1 and data[p + 4:p + 10] == b"Exif\x00\x00":
            t = p + 10                      # inizio dell'intestazione TIFF
            e = "<" if data[t:t + 2] == b"II" else ">" if data[t:t + 2] == b"MM" else None
            if e is None:
                return None
            ifd = t + struct.unpack(e + "I", data[t + 4:t + 8])[0]
            n = struct.unpack(e + "H", data[ifd:ifd + 2])[0]
            for i in range(n):
                q = ifd + 2 + i * 12
                tag, typ, cnt = struct.unpack(e + "HHI", data[q:q + 8])
                if tag == 0x0112 and typ == 3 and cnt == 1:
                    return q + 8, e, struct.unpack(e + "H", data[q + 8:q + 10])[0]
            return None
        p += 2 + seglen
    return None


def save_to_file(path, op_orientation):
    """Salva nel file la trasformazione vista a schermo. Ritorna "lossless" o "reencoded".
    Solleva OSError."""
    from . import codecs
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".jpe", ".jfif"):
        with open(path, "rb") as f:
            data = f.read()
        hit = _jpeg_orientation_offset(data)
        if hit:
            pos, e, cur = hit
            new = from_matrix(_mul(matrix(op_orientation), _EXIF_M.get(cur, _EXIF_M[1])))
            val = exif_value(new)
            st = os.stat(path)
            with open(path, "r+b") as f:
                f.seek(pos)
                f.write(struct.pack(e + "H", val))
            try:    # la data resta quella dello scatto, ma la cache delle miniature deve aggiornarsi
                os.utime(path, (st.st_atime, max(st.st_mtime + 1, st.st_mtime)))
            except OSError:
                pass
            return "lossless"
    if not codecs.have_pillow():
        img, err = codecs.read_qimage(path)
        if img.isNull():
            raise OSError(err)
        img = apply(img, op_orientation)
        key = codecs.key_for_ext(ext) or "png"
        codecs.save_qimage(img, path + ".tmp" + ext, key, 95)
        os.replace(path + ".tmp" + ext, path)
        return "reencoded"
    im, exif, icc = codecs.open_pil(path)
    from PIL import Image
    k, mirror = from_matrix(matrix(op_orientation))
    tr_map = {1: Image.Transpose.ROTATE_270, 2: Image.Transpose.ROTATE_180, 3: Image.Transpose.ROTATE_90}
    if k:
        im = im.transpose(tr_map[k])
    if mirror:
        im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    key = codecs.key_for_ext(ext) or "png"
    tmp = path + ".isvtmp" + ext
    codecs.save_pil(im, tmp, key, 95, False, exif, icc)
    os.replace(tmp, path)
    return "reencoded"


def can_save(path):
    from . import codecs
    from .archive import is_virtual
    if is_virtual(path) or codecs.is_video(path) or codecs.is_raw(path):
        return False
    return codecs.key_for_ext(os.path.splitext(path)[1]) is not None
