"""Lettura veloce di pochi dati EXIF (data di scatto, fotocamera, GPS) con Pillow.

Si legge solo l'intestazione del file, senza decodificare l'immagine.
"""
import io
import time

from .archive import is_virtual, read_bytes


def _open(path):
    try:
        from .codecs import _init_pillow
        _init_pillow()
        from PIL import Image
    except ImportError:
        return None
    try:
        return Image.open(io.BytesIO(read_bytes(path)) if is_virtual(path) else path)
    except Exception:  # noqa: BLE001
        return None


def _ratio(v):
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        try:
            a, b = v
            return a / b if b else 0.0
        except (TypeError, ValueError):
            return 0.0


def read(path):
    """{"date": timestamp o None, "camera": str, "gps": (lat, lon) o None, "size": (w, h)}"""
    out = {"date": None, "camera": "", "gps": None, "size": None}
    im = _open(path)
    if im is None:
        return out
    try:
        with im:
            out["size"] = im.size
            ex = im.getexif()
            if not ex:
                return out
            sub = {}
            try:
                sub = ex.get_ifd(0x8769)
            except Exception:  # noqa: BLE001
                pass
            d = sub.get(0x9003) or sub.get(0x9004) or ex.get(0x0132)
            if d:
                try:
                    s = d.decode() if isinstance(d, bytes) else str(d)
                    out["date"] = time.mktime(time.strptime(s.strip()[:19], "%Y:%m:%d %H:%M:%S"))
                except (ValueError, OverflowError):
                    pass
            make = str(ex.get(0x010F, "") or "").strip().strip("\0")
            model = str(ex.get(0x0110, "") or "").strip().strip("\0")
            out["camera"] = model if make and model.lower().startswith(make.split()[0].lower()) else \
                f"{make} {model}".strip()
            try:
                g = ex.get_ifd(0x8825)
            except Exception:  # noqa: BLE001
                g = {}
            if g and 2 in g and 4 in g:
                lat = sum(_ratio(x) / 60 ** i for i, x in enumerate(g[2]))
                lon = sum(_ratio(x) / 60 ** i for i, x in enumerate(g[4]))
                if str(g.get(1, "N")).upper().startswith("S"):
                    lat = -lat
                if str(g.get(3, "E")).upper().startswith("W"):
                    lon = -lon
                if abs(lat) > 1e-6 or abs(lon) > 1e-6:
                    out["gps"] = (lat, lon)
    except Exception:  # noqa: BLE001
        pass
    return out


def taken(path, fallback_mtime=None):
    """Data dello scatto (EXIF) o, in mancanza, la data del file."""
    d = read(path)["date"]
    if d:
        return d
    if fallback_mtime is not None:
        return fallback_mtime
    from .archive import stat_any
    try:
        return stat_any(path)[0]
    except OSError:
        return 0
