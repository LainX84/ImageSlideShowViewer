"""Formati di file: lettura e scrittura oltre a quelli di Qt.

  * Qt (sempre): JPEG, PNG, GIF, BMP, WebP, TIFF, ICO, TGA…
  * Pillow + plugin (facoltativi, consigliati):
        HEIC / HEIF   pillow-heif
        AVIF          Pillow 11.3+ (oppure pillow-heif)
        JPEG XL       pillow-jxl-plugin
  * RAW delle fotocamere: si mostra l'anteprima JPEG incorporata nel file
    (con rawpy se installato, altrimenti cercandola direttamente nel file).
  * Video brevi (MP4, WebM, MOV, MKV…) se c'è QtMultimedia: vedi video.py.

Tutte le funzioni di lettura accettano anche i percorsi "virtuali" degli archivi.
"""
import io
import os
import threading

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QImageWriter

from .archive import image_reader, is_virtual, read_bytes

RAW_EXTS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".orf",
            ".rw2", ".raf", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mrw", ".rwl",
            ".iiq", ".mef", ".mos"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv", ".mpg", ".mpeg", ".3gp"}
_QT_WANTED = ["jpg", "jpeg", "jpe", "jfif", "png", "gif", "bmp", "webp", "tif", "tiff",
              "tga", "ico", "heic", "heif", "avif", "jxl"]

_lock = threading.Lock()
_qt_exts = None
_pil_exts = None        # estensione -> formato Pillow
_pil_write = None       # nome formato Pillow -> True
_video_ok = None


# ------------------------------------------------------------------- formati
def qt_exts():
    global _qt_exts
    if _qt_exts is None:
        sup = {bytes(f).decode("ascii", "ignore").lower() for f in QImageReader.supportedImageFormats()}
        ex = {e for e in _QT_WANTED if e in sup}
        if "jpg" in sup or "jpeg" in sup:
            ex |= {"jpg", "jpeg", "jpe", "jfif"}
        if "tif" in sup or "tiff" in sup:
            ex |= {"tif", "tiff"}
        if "heif" in sup or "heic" in sup:
            ex |= {"heic", "heif"}
        _qt_exts = {"." + e for e in ex}
    return _qt_exts


def _init_pillow():
    """Registra i plugin di Pillow disponibili (una volta sola)."""
    global _pil_exts, _pil_write
    with _lock:
        if _pil_exts is not None:
            return
        exts, write = {}, {}
        try:
            from PIL import Image
        except ImportError:
            _pil_exts, _pil_write = exts, write
            return
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            exts.update({".heic": "HEIF", ".heif": "HEIF", ".hif": "HEIF"})
            write["HEIF"] = True
        except Exception:  # noqa: BLE001
            pass
        try:
            from PIL import features
            if features.check("avif"):
                exts[".avif"] = "AVIF"
                write["AVIF"] = True
        except Exception:  # noqa: BLE001
            pass
        if ".avif" not in exts:
            try:
                import pillow_heif
                if hasattr(pillow_heif, "register_avif_opener"):
                    pillow_heif.register_avif_opener()
                    exts[".avif"] = "AVIF"
                    write["AVIF"] = True
            except Exception:  # noqa: BLE001
                pass
        try:
            import pillow_jxl  # noqa: F401 - registra il formato JXL
            exts[".jxl"] = "JXL"
            write["JXL"] = True
        except Exception:  # noqa: BLE001
            pass
        Image.init()
        _pil_exts, _pil_write = exts, write


def pillow_exts():
    """Estensioni lette tramite Pillow (quelle che Qt non sa leggere)."""
    _init_pillow()
    return {e for e in _pil_exts if e not in qt_exts()}


def video_supported():
    global _video_ok
    if _video_ok is None:
        try:
            from PySide6 import QtMultimedia  # noqa: F401
            _video_ok = True
        except Exception:  # noqa: BLE001
            _video_ok = False
    return _video_ok


_img_exts = None


def image_exts():
    """Tutte le estensioni di immagine apribili (senza i video)."""
    global _img_exts
    if _img_exts is None:
        _img_exts = frozenset(qt_exts() | pillow_exts() | RAW_EXTS)
    return _img_exts


def media_exts(videos=True):
    ex = image_exts()
    if videos and video_supported():
        ex = ex | VIDEO_EXTS
    return ex


def ext_of(path):
    return os.path.splitext(path.split("|")[-1])[1].lower()


def is_video(path):
    return ext_of(path) in VIDEO_EXTS and video_supported()


def is_raw(path):
    return ext_of(path) in RAW_EXTS


def needs_pillow(path):
    e = ext_of(path)
    return e not in qt_exts() and e in pillow_exts()


def format_label(path):
    e = ext_of(path)
    return {".jpg": "JPEG", ".jpeg": "JPEG", ".jpe": "JPEG", ".jfif": "JPEG", ".tif": "TIFF",
            ".heic": "HEIC", ".heif": "HEIF", ".jxl": "JPEG XL"}.get(e, e.lstrip(".").upper())


# ------------------------------------------------------- conversioni QImage
def pil_to_qimage(im):
    from PIL import Image
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if ("A" in im.getbands() or im.mode == "P" and "transparency" in im.info)
                        else "RGB")
    if im.mode == "RGB":
        data = im.tobytes("raw", "RGB")
        q = QImage(data, im.width, im.height, im.width * 3, QImage.Format.Format_RGB888)
    else:
        data = im.tobytes("raw", "RGBA")
        q = QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888)
    del Image
    return q.copy()


def qimage_to_pil(img):
    from PIL import Image
    alpha = img.hasAlphaChannel()
    q = img.convertToFormat(QImage.Format.Format_RGBA8888 if alpha else QImage.Format.Format_RGB888)
    w, h, bpl = q.width(), q.height(), q.bytesPerLine()
    buf = bytes(q.constBits())[:bpl * h]
    mode = "RGBA" if alpha else "RGB"
    return Image.frombuffer(mode, (w, h), buf, "raw", mode, bpl, 1).copy()


def _source(path):
    return io.BytesIO(read_bytes(path)) if is_virtual(path) else path


# ------------------------------------------------------------------ lettura
def read_qimage(path, max_side=0):
    """(QImage, errore). Con max_side l'immagine viene letta già ridotta (miniature)."""
    from .i18n import tr
    e = ext_of(path)
    try:
        if e in RAW_EXTS:
            img = _read_raw(path)
        elif e in qt_exts():
            r, keep = image_reader(path)
            r.setAutoTransform(True)
            if max_side:
                sz = r.size()
                if sz.isValid() and (sz.width() > max_side or sz.height() > max_side):
                    r.setScaledSize(sz.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio))
            img = r.read()
            if img.isNull():
                return img, r.errorString() or tr("Formato non leggibile")
            del keep
        elif e in pillow_exts():
            img = _read_pillow(path, max_side)
        else:
            return QImage(), tr("Formato non supportato")
    except Exception as ex:  # noqa: BLE001
        return QImage(), str(ex) or tr("Impossibile leggere il file")
    if img is None or img.isNull():
        return QImage(), tr("Formato non leggibile")
    if max_side and (img.width() > max_side or img.height() > max_side):
        img = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img, ""


def _read_pillow(path, max_side=0):
    _init_pillow()
    from PIL import Image, ImageOps
    with Image.open(_source(path)) as im:
        if max_side:
            try:
                im.draft("RGB", (max_side, max_side))
            except Exception:  # noqa: BLE001
                pass
        im.load()
        im = ImageOps.exif_transpose(im)
        if max_side and (im.width > max_side or im.height > max_side):
            im.thumbnail((max_side, max_side))
        return pil_to_qimage(im)


def read_size(path):
    """Dimensioni come verranno mostrate (EXIF applicato); QSize() se non si sa."""
    e = ext_of(path)
    try:
        if e in qt_exts():
            r, keep = image_reader(path)
            s = r.size()
            if s.isValid():
                t = r.transformation()
                if t & QImageIOHandlerRotate90():
                    s = QSize(s.height(), s.width())
            return s
        if e in pillow_exts():
            _init_pillow()
            from PIL import Image
            with Image.open(_source(path)) as im:
                w, h = im.size
                try:
                    if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):
                        w, h = h, w
                except Exception:  # noqa: BLE001
                    pass
                return QSize(w, h)
        if e in RAW_EXTS:
            img = _read_raw(path)
            return img.size() if img is not None else QSize()
    except Exception:  # noqa: BLE001
        pass
    return QSize()


def QImageIOHandlerRotate90():  # noqa: N802 - piccolo alias leggibile
    from PySide6.QtGui import QImageIOHandler
    return QImageIOHandler.Transformation.TransformationRotate90


# ---------------------------------------------------------------------- RAW
def _read_raw(path):
    """Anteprima JPEG incorporata nel RAW (ruotata come la foto)."""
    data = None
    if not is_virtual(path):
        try:
            import rawpy
            with rawpy.imread(path) as raw:
                flip = getattr(raw.sizes, "flip", 0)
                th = raw.extract_thumb()
                if th.format == rawpy.ThumbFormat.JPEG:
                    img = _decode_bytes(bytes(th.data))
                else:   # bitmap RGB (numpy)
                    arr = th.data
                    h, w = arr.shape[:2]
                    img = QImage(arr.tobytes(), w, h, w * 3, QImage.Format.Format_RGB888).copy()
                return _flip(img, flip)
        except Exception:  # noqa: BLE001 - rawpy assente o RAW senza anteprima
            pass
        with open(path, "rb") as f:
            data = f.read()
    else:
        data = read_bytes(path)
    img = _largest_jpeg(data)
    if img is None:
        return QImage()
    return _apply_orientation(img, _tiff_orientation(data))


def _decode_bytes(data):
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    r = QImageReader(buf, b"jpeg")
    return r.read()


def _largest_jpeg(data, max_candidates=40):
    """Cerca nel file le immagini JPEG incorporate e decodifica la più grande."""
    best, best_area, pos, n = None, 0, 0, 0
    while n < max_candidates:
        pos = data.find(b"\xff\xd8\xff", pos)
        if pos < 0:
            break
        n += 1
        buf = QBuffer()
        buf.setData(QByteArray(data[pos:pos + 64 * 1024 * 1024]))
        buf.open(QIODevice.OpenModeFlag.ReadOnly)
        r = QImageReader(buf, b"jpeg")
        s = r.size()
        if s.isValid() and s.width() * s.height() > best_area:
            best_area, best = s.width() * s.height(), pos
        pos += 3
    if best is None:
        return None
    img = _decode_bytes(data[best:])
    return img if not img.isNull() else None


def _tiff_orientation(data):
    """Orientamento EXIF dell'IFD0 per i RAW basati su TIFF (quasi tutti)."""
    import struct
    if data[:2] == b"II":
        e = "<"
    elif data[:2] == b"MM":
        e = ">"
    else:
        return 1
    try:
        off = struct.unpack(e + "I", data[4:8])[0]
        n = struct.unpack(e + "H", data[off:off + 2])[0]
        for i in range(min(n, 400)):
            p = off + 2 + i * 12
            tag, typ = struct.unpack(e + "HH", data[p:p + 4])
            if tag == 0x0112:
                return struct.unpack(e + "H", data[p + 8:p + 10])[0]
    except Exception:  # noqa: BLE001
        pass
    return 1


def _flip(img, flip):
    # rawpy/LibRaw: 3 = 180°, 5 = 90° antiorario, 6 = 90° orario
    return _apply_orientation(img, {3: 3, 5: 8, 6: 6}.get(flip, 1))


def _apply_orientation(img, o):
    from PySide6.QtGui import QTransform
    if img is None or img.isNull() or o in (0, 1):
        return img
    t = QTransform()
    if o in (2, 4, 5, 7):
        img = img.mirrored(o in (2, 5, 7), o == 4)
    if o in (3,):
        t.rotate(180)
    elif o in (6, 7):
        t.rotate(90)
    elif o in (8, 5):
        t.rotate(270)
    return img.transformed(t) if not t.isIdentity() else img


# ------------------------------------------------------------------ scrittura
# (nome mostrato, chiave, estensione, scritto da: "qt" o "pil")
_ALL_WRITE = [("JPEG", "jpeg", ".jpg"), ("PNG", "png", ".png"), ("WebP", "webp", ".webp"),
              ("AVIF", "avif", ".avif"), ("HEIC", "heif", ".heic"), ("JPEG XL", "jxl", ".jxl"),
              ("TIFF", "tiff", ".tif"), ("BMP", "bmp", ".bmp"), ("GIF", "gif", ".gif")]
_PIL_NAME = {"jpeg": "JPEG", "png": "PNG", "webp": "WEBP", "avif": "AVIF", "heif": "HEIF",
             "jxl": "JXL", "tiff": "TIFF", "bmp": "BMP", "gif": "GIF"}
LOSSY = {"jpeg", "webp", "avif", "heif", "jxl"}
LOSSLESS_OPTION = {"webp", "avif", "jxl", "heif"}


def have_pillow():
    try:
        import PIL  # noqa: F401
        return True
    except ImportError:
        return False


def write_formats():
    """Formati disponibili per salvare / convertire: [(nome, chiave, estensione)]."""
    _init_pillow()
    qt = {bytes(f).decode().lower() for f in QImageWriter.supportedImageFormats()}
    out = []
    for name, key, ext in _ALL_WRITE:
        if key in ("avif", "heif", "jxl"):
            if _pil_write.get(_PIL_NAME[key]):
                out.append((name, key, ext))
        elif have_pillow() or key in qt:
            out.append((name, key, ext))
    return out


def key_for_ext(ext):
    ext = ext.lower()
    for name, key, e in _ALL_WRITE:
        if e == ext or (key == "jpeg" and ext in (".jpeg", ".jpe", ".jfif")) or \
                (key == "tiff" and ext == ".tiff") or (key == "heif" and ext in (".heif", ".hif")):
            return key
    return None


def save_pil(im, dst, key, quality=90, lossless=False, exif=None, icc=None):
    """Salva un'immagine Pillow nel formato key. Solleva OSError."""
    _init_pillow()
    fmt = _PIL_NAME[key]
    if key in ("jpeg", "bmp") and im.mode not in ("RGB", "L"):
        from PIL import Image
        if "A" in im.getbands():
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        else:
            im = im.convert("RGB")
    elif key == "gif" and im.mode not in ("P", "L"):
        im = im.convert("RGBA").quantize(256) if "A" in im.getbands() else im.convert("RGB").quantize(256)
    elif im.mode not in ("RGB", "RGBA", "L", "LA", "I;16", "I"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    kw = {}
    if key in LOSSY:
        kw["quality"] = int(quality)
    if lossless and key in LOSSLESS_OPTION:
        kw["lossless"] = True
        if key == "heif":
            kw["quality"] = -1
    if key == "jpeg":
        kw["optimize"] = True
        kw["subsampling"] = 0 if quality >= 90 else 2
    if exif and key in ("jpeg", "webp", "avif", "heif", "jxl", "tiff", "png"):
        kw["exif"] = exif
    if icc and key in ("jpeg", "webp", "avif", "heif", "png", "tiff", "jxl"):
        kw["icc_profile"] = icc
    try:
        im.save(dst, fmt, **kw)
    except TypeError:
        kw.pop("exif", None)
        kw.pop("icc_profile", None)
        im.save(dst, fmt, **kw)
    except (ValueError, KeyError) as e:
        raise OSError(str(e)) from e


def open_pil(path):
    """Immagine Pillow raddrizzata secondo l'EXIF, più (exif con orientamento = 1, icc)."""
    _init_pillow()
    from PIL import Image, ImageOps
    if ext_of(path) in RAW_EXTS:
        return qimage_to_pil(_read_raw(path)), None, None
    im = Image.open(_source(path))
    im.load()
    exif = None
    try:
        ex = im.getexif()
        if ex:
            ex[0x0112] = 1
            exif = ex.tobytes()
    except Exception:  # noqa: BLE001
        exif = None
    icc = im.info.get("icc_profile")
    im = ImageOps.exif_transpose(im)
    return im, exif, icc


def save_qimage(img, dst, key, quality=90, lossless=False, exif=None, icc=None):
    """Salva un QImage (con Pillow se possibile, così si possono tenere EXIF e profilo)."""
    if have_pillow():
        save_pil(qimage_to_pil(img), dst, key, quality, lossless, exif, icc)
        return
    w = QImageWriter(dst, key.encode())
    if key in LOSSY:
        w.setQuality(int(quality))
    if not w.write(img):
        raise OSError(w.errorString())


def status_lines():
    """Righe per la finestra Informazioni / opzioni: cosa è disponibile."""
    _init_pillow()
    out = []
    try:
        import PIL
        out.append(f"Pillow {PIL.__version__}")
    except ImportError:
        out.append("Pillow: —")
    for label, ext in (("HEIC/HEIF", ".heic"), ("AVIF", ".avif"), ("JPEG XL", ".jxl")):
        out.append(f"{label}: {'✓' if ext in _pil_exts or ext in qt_exts() else '—'}")
    try:
        import rawpy  # noqa: F401
        out.append("RAW: rawpy ✓")
    except Exception:  # noqa: BLE001
        out.append("RAW: " + "✓ (anteprima incorporata)")
    out.append(f"Video: {'✓' if video_supported() else '—'}")
    return out
