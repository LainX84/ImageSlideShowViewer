"""Archivi di fumetti trattati come cartelle: ZIP/CBZ, RAR/CBR, 7Z/CB7.

Un'immagine dentro un archivio ha un percorso "virtuale":
    C:\\Manga\\Volume 1.cbz|capitolo 1/001.jpg
Il carattere '|' non è ammesso nei nomi di file di Windows, quindi non crea ambiguità.

  * ZIP / CBZ  con zipfile (incluso in Python): lettura diretta e veloce.
  * 7Z / CB7   con py7zr; in mancanza, con il programma 7-Zip.
  * RAR / CBR  con il programma 7-Zip (legge anche RAR5) oppure UnRAR, tramite rarfile.
Per RAR e 7Z l'archivio viene estratto una volta in una cartella temporanea (cancellata
all'uscita): leggere una pagina alla volta dagli archivi "solidi" sarebbe lentissimo.
Per la massima compatibilità si possono convertire in CBZ (to_cbz).
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from collections import OrderedDict, namedtuple

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImageReader

SEP = "|"
ZIP_EXTS = {".zip", ".cbz"}
RAR_EXTS = {".rar", ".cbr"}
SEVEN_EXTS = {".7z", ".cb7"}
ARCHIVE_EXTS = ZIP_EXTS | RAR_EXTS | SEVEN_EXTS

Member = namedtuple("Member", "filename file_size date_time")

_lock = threading.Lock()
_zips = OrderedDict()      # percorso -> (mtime, ZipFile, lock)
_members = OrderedDict()   # (percorso, mtime, size) -> [Member immagini ordinate]
_extracted = OrderedDict() # (percorso, mtime) -> cartella temporanea
_extract_locks = {}
MAX_OPEN = 8
MAX_LISTS = 256
MAX_EXTRACTED = 3
_tmp_root = None


def is_archive(path):
    return os.path.splitext(path)[1].lower() in ARCHIVE_EXTS


def kind(path):
    e = os.path.splitext(path)[1].lower()
    return "zip" if e in ZIP_EXTS else "rar" if e in RAR_EXTS else "7z" if e in SEVEN_EXTS else None


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


# ----------------------------------------------------------- strumenti esterni
def _find_7zip():
    """Percorso di 7-Zip (7z.exe / 7zz / 7z) se installato."""
    names = ["7z", "7zz", "7za"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramW6432", r"C:\Program Files")):
            p = os.path.join(base or "", "7-Zip", "7z.exe")
            if os.path.isfile(p):
                return p
    elif sys.platform == "darwin":
        for p in ("/opt/homebrew/bin/7zz", "/opt/homebrew/bin/7z", "/usr/local/bin/7zz",
                  "/usr/local/bin/7z"):
            if os.path.isfile(p):
                return p
    return None


def _find_unrar():
    for n in ("unrar", "UnRAR"):
        p = shutil.which(n)
        if p:
            return p
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            p = os.path.join(base or "", "WinRAR", "UnRAR.exe")
            if os.path.isfile(p):
                return p
    return None


def tools_status():
    """Per le opzioni / Informazioni: cosa c'è per leggere RAR e 7Z."""
    out = {"7zip": _find_7zip(), "unrar": _find_unrar()}
    try:
        import py7zr  # noqa: F401
        out["py7zr"] = True
    except ImportError:
        out["py7zr"] = False
    try:
        import rarfile  # noqa: F401
        out["rarfile"] = True
    except ImportError:
        out["rarfile"] = False
    return out


def _run(cmd):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(cmd, capture_output=True, creationflags=flags)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout or b"").decode("utf-8", "replace").strip()[-400:]
                      or f"exit {r.returncode}")
    return r.stdout


def _missing_tool_error():
    from .i18n import tr
    return OSError(tr("Per aprire i file RAR/CBR serve 7-Zip (consigliato, legge anche RAR5) "
                      "oppure UnRAR. Installa 7-Zip da https://www.7-zip.org"))


# --------------------------------------------------------------------- ZIP
def _open_zip(path):
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


# ------------------------------------------------------------- elenco membri
def _list_raw(path):
    """[Member] di tutti i file dell'archivio (cartelle escluse)."""
    k = kind(path)
    if k == "zip":
        z, zl = _open_zip(path)
        with zl:
            return [Member(zi.filename, zi.file_size, zi.date_time) for zi in z.infolist()
                    if not zi.is_dir()]
    if k == "7z":
        try:
            import py7zr
            with py7zr.SevenZipFile(path, "r") as z:
                out = []
                for fi in z.list():
                    if fi.is_directory:
                        continue
                    dt = fi.creationtime.timetuple()[:6] if getattr(fi, "creationtime", None) else (1980, 1, 1, 0, 0, 0)
                    out.append(Member(fi.filename, fi.uncompressed or 0, dt))
                return out
        except ImportError:
            pass
        return _list_7zip(path)
    if k == "rar":
        seven = _find_7zip()
        if seven:
            return _list_7zip(path)
        try:
            import rarfile
        except ImportError as e:
            raise _missing_tool_error() from e
        unrar = _find_unrar()
        if not unrar:
            raise _missing_tool_error()
        rarfile.UNRAR_TOOL = unrar
        with rarfile.RarFile(path) as rf:
            return [Member(ri.filename, ri.file_size, ri.date_time) for ri in rf.infolist()
                    if not ri.is_dir()]
    return []


def _list_7zip(path):
    exe = _find_7zip()
    if not exe:
        if kind(path) == "7z":
            from .i18n import tr
            raise OSError(tr("Per aprire i file 7Z/CB7 serve il pacchetto py7zr oppure 7-Zip."))
        raise _missing_tool_error()
    out = _run([exe, "l", "-slt", "-ba", "-sccUTF-8", path]).decode("utf-8", "replace")
    members, cur = [], {}
    for line in out.splitlines() + [""]:
        line = line.strip()
        if not line:
            if cur.get("Path") and "D" not in cur.get("Attributes", "") and cur.get("Folder") != "+":
                dt = (1980, 1, 1, 0, 0, 0)
                m = cur.get("Modified", "")
                try:
                    d, t = m.split(" ")[:2]
                    y, mo, da = (int(x) for x in d.split("-"))
                    hh, mm, ss = (int(float(x)) for x in t.split(":"))
                    dt = (y, mo, da, hh, mm, ss)
                except (ValueError, IndexError):
                    pass
                try:
                    size = int(cur.get("Size", "0") or 0)
                except ValueError:
                    size = 0
                members.append(Member(cur["Path"].replace("\\", "/"), size, dt))
            cur = {}
            continue
        if " = " in line:
            k, v = line.split(" = ", 1)
            cur[k] = v
    return members


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
        infos = _list_raw(path)
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError, Exception):  # noqa: BLE001
        infos = []
    imgs = [zi for zi in infos
            if is_image(zi.filename)
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
    import time
    try:
        mt = os.stat(path).st_mtime
    except OSError:
        return []
    items = []
    for zi in image_members(path):
        try:
            zmt = time.mktime(tuple(zi.date_time) + (0, 0, -1))
        except (OverflowError, ValueError, TypeError):
            zmt = mt
        items.append(FileItem(path + SEP + zi.filename, os.path.basename(zi.filename),
                              zi.file_size, zmt))
    if sort == "date":
        items.sort(key=lambda i: i.mtime)
    elif sort == "size":
        items.sort(key=lambda i: i.size)
    if reverse:
        items.reverse()
    return items


# ------------------------------------------------------------------ lettura
def _tmp():
    global _tmp_root
    if _tmp_root is None:
        _tmp_root = tempfile.mkdtemp(prefix="isv-archives-")
        atexit.register(lambda: shutil.rmtree(_tmp_root, ignore_errors=True))
    return _tmp_root


def _extract_all(path):
    """Cartella temporanea con il contenuto di un RAR / 7Z (estratto una volta)."""
    st = os.stat(path)
    key = (path, st.st_mtime)
    with _lock:
        d = _extracted.get(key)
        if d and os.path.isdir(d):
            _extracted.move_to_end(key)
            return d
        el = _extract_locks.setdefault(key, threading.Lock())
    with el:     # un solo thread estrae, gli altri aspettano
        with _lock:
            d = _extracted.get(key)
            if d and os.path.isdir(d):
                return d
        d = tempfile.mkdtemp(dir=_tmp())
        k = kind(path)
        try:
            if k == "7z":
                try:
                    import py7zr
                    with py7zr.SevenZipFile(path, "r") as z:
                        z.extractall(path=d)
                except ImportError:
                    _run([_find_7zip() or "7z", "x", "-y", "-o" + d, path])
            elif k == "rar":
                seven = _find_7zip()
                if seven:
                    _run([seven, "x", "-y", "-o" + d, path])
                else:
                    import rarfile
                    unrar = _find_unrar()
                    if not unrar:
                        raise _missing_tool_error()
                    rarfile.UNRAR_TOOL = unrar
                    with rarfile.RarFile(path) as rf:
                        rf.extractall(d)
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        with _lock:
            _extracted[key] = d
            while len(_extracted) > MAX_EXTRACTED:
                _k, old = _extracted.popitem(last=False)
                shutil.rmtree(old, ignore_errors=True)
        return d


def read_bytes(vpath):
    a, m = split(vpath)
    if kind(a) == "zip":
        z, zl = _open_zip(a)
        with zl:
            return z.read(m)
    d = _extract_all(a)
    with open(os.path.join(d, *m.split("/")), "rb") as f:
        return f.read()


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


# ------------------------------------------------------------ conversione
def to_cbz(path, dst=None, progress=None):
    """Converte un CBR/RAR/CB7/7Z (o rifà un CBZ) in CBZ con tutte le immagini, nello
    stesso ordine. Le immagini sono già compresse: si salvano senza ricomprimere.
    Ritorna il percorso scritto. progress(i, n) -> True per annullare."""
    from .utils import unique_path
    imgs = image_members(path)
    if not imgs:
        from .i18n import tr
        raise OSError(tr("L'archivio non contiene immagini leggibili."))
    if dst is None:
        dst = unique_path(os.path.splitext(path)[0] + ".cbz")
    tmp = dst + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
            for i, m in enumerate(imgs):
                if progress and progress(i, len(imgs)):
                    raise InterruptedError
                zi = zipfile.ZipInfo(m.filename, date_time=tuple(m.date_time)[:6])
                z.writestr(zi, read_bytes(path + SEP + m.filename))
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return dst
