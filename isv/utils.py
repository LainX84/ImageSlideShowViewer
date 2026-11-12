"""Funzioni di supporto: elenco immagini, cartelle, ordinamento naturale."""
import os
import re
import subprocess
import sys
from collections import namedtuple

from . import archive

FileItem = namedtuple("FileItem", "path name size mtime is_dir", defaults=(False,))

_WANTED = ["jpg", "jpeg", "jpe", "jfif", "png", "gif", "bmp", "webp", "tif",
           "tiff", "heic", "heif", "avif", "jxl", "tga", "ico"]   # per il menu di Esplora risorse

# I video compaiono nel browser e nello slideshow solo se attivato (opzione) e se c'è QtMultimedia
SHOW_VIDEOS = True


def image_exts():
    """Estensioni immagine apribili (Qt, Pillow con i plugin, RAW)."""
    from .codecs import image_exts as _ie
    return _ie()


def is_image(name):
    from .codecs import ext_of
    return ext_of(name) in image_exts()


def is_video(name):
    from .codecs import is_video as _iv
    return SHOW_VIDEOS and _iv(name)


def is_media(name):
    """Immagine oppure video (se i video sono attivi)."""
    return is_image(name) or is_video(name)


def natural_key(s):
    """Ordina 'foto2' prima di 'foto10'."""
    return [int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", s)]


def samepath(a, b):
    if a is None or b is None:
        return False
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


_SKIP = {"$recycle.bin", "system volume information", "$windows.~bt",
         "$windows.~ws", "recycler", "$sysreset", "windowsapps"}


def _hidden(entry):
    name = entry.name
    if name.startswith(".") or name.lower() in _SKIP:
        return True
    if sys.platform == "win32":
        try:
            attrs = entry.stat(follow_symlinks=False).st_file_attributes
            return bool(attrs & (0x2 | 0x4))  # HIDDEN | SYSTEM
        except (OSError, AttributeError):
            return False
    return False


def list_subdirs(folder):
    out = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if getattr(e, "is_junction", lambda: False)():
                        continue
                    if not e.is_dir(follow_symlinks=False):
                        # gli archivi ZIP/CBZ si comportano come sottocartelle
                        if not (archive.is_archive(e.name) and e.is_file()):
                            continue
                except OSError:
                    continue
                if _hidden(e):
                    continue
                out.append(e.path)
    except OSError:
        return []
    out.sort(key=lambda p: natural_key(os.path.basename(p)))
    return out


def list_image_items(folder, sort="name", reverse=False):
    if archive.is_archive(folder):
        return archive.list_items(folder, sort, reverse)
    items = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if not e.is_file() or not is_media(e.name):
                        continue
                    st = e.stat()
                except OSError:
                    continue
                items.append(FileItem(e.path, e.name, st.st_size, st.st_mtime))
    except OSError:
        return []
    if sort == "date":
        items.sort(key=lambda i: (i.mtime, natural_key(i.name)))
    elif sort == "size":
        items.sort(key=lambda i: (i.size, natural_key(i.name)))
    else:
        items.sort(key=lambda i: natural_key(i.name))
    if reverse:
        items.reverse()
    return items


_UNC_SERVER = re.compile(r"^[\\/]{2}([^\\/]+)[\\/]?$")


def unc_server(path):
    """'\\\\192.168.0.2' -> '192.168.0.2'; None se path non è un server di rete nudo."""
    m = _UNC_SERVER.match(path.strip()) if path else None
    return m.group(1) if m else None


def unc_parent(path):
    """Per '\\\\host\\condivisione' restituisce '\\\\host' (la lista delle condivisioni)."""
    p = os.path.normpath(path)
    if p.startswith("\\\\") or p.startswith("//"):
        parts = [x for x in re.split(r"[\\/]+", p) if x]
        if len(parts) == 2:
            return "\\\\" + parts[0]
    return None


def list_unc_shares(host):
    """Cartelle condivise di un computer in rete (solo Windows). Solleva OSError."""
    if sys.platform != "win32":
        from .i18n import tr
        raise OSError(tr("Elenco delle condivisioni disponibile solo su Windows"))
    import ctypes
    from ctypes import wintypes

    class SHARE_INFO_1(ctypes.Structure):
        _fields_ = [("netname", wintypes.LPWSTR), ("type", wintypes.DWORD),
                    ("remark", wintypes.LPWSTR)]

    netapi = ctypes.WinDLL("Netapi32.dll")
    netapi.NetShareEnum.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                                    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    netapi.NetApiBufferFree.argtypes = [ctypes.c_void_p]
    names = []
    resume = wintypes.DWORD(0)
    while True:
        buf = ctypes.c_void_p()
        read, total = wintypes.DWORD(0), wintypes.DWORD(0)
        res = netapi.NetShareEnum("\\\\" + host, 1, ctypes.byref(buf), 0xFFFFFFFF,
                                  ctypes.byref(read), ctypes.byref(total), ctypes.byref(resume))
        if res not in (0, 234):  # 234 = ERROR_MORE_DATA
            from .i18n import tr
            msg = {5: tr("accesso negato"), 53: tr("computer non raggiungibile"),
                   1326: tr("nome utente o password non validi"),
                   2114: tr("servizio Server non attivo")}.get(res, tr("errore {n}", n=res))
            raise OSError(msg)
        try:
            arr = ctypes.cast(buf, ctypes.POINTER(SHARE_INFO_1))
            for i in range(read.value):
                t = arr[i].type
                if (t & 0xFF) == 0 and not (t & 0x80000000):  # solo dischi, niente C$ / ADMIN$
                    names.append(arr[i].netname)
        finally:
            if buf:
                netapi.NetApiBufferFree(buf)
        if res != 234:
            break
    names.sort(key=natural_key)
    return [f"\\\\{host}\\{n}" for n in names]


def list_folder_items(folder, sort="name", reverse=False):
    """Sottocartelle (prima) e immagini della cartella, come nel browser di ACDSee.
    Per un server di rete (\\\\host) elenca le cartelle condivise."""
    host = unc_server(folder)
    if host:
        return [FileItem(p, p.rsplit("\\", 1)[-1], 0, 0, True) for p in list_unc_shares(host)]
    dirs = []
    for p in list_subdirs(folder):
        try:
            mt = os.stat(p).st_mtime
        except OSError:
            mt = 0
        dirs.append(FileItem(p, os.path.basename(p), 0, mt, True))
    if sort == "date":
        dirs.sort(key=lambda i: (i.mtime, natural_key(i.name)))
    if reverse:
        dirs.reverse()
    return dirs + list_image_items(folder, sort, reverse)


def find_cover(folder, max_folders=30):
    """Prima immagine della cartella o, se vuota, delle sue sottocartelle."""
    stack, seen = [folder], 0
    while stack and seen < max_folders:
        f = stack.pop()
        seen += 1
        imgs = [p for p in list_images(f) if not is_video(p)]
        if imgs:
            return imgs[0]
        stack.extend(reversed(list_subdirs(f)))
    return None


def list_images(folder, sort="name", reverse=False):
    return [i.path for i in list_image_items(folder, sort, reverse)]


def has_images(folder):
    if archive.is_archive(folder):
        return archive.has_images(folder)
    try:
        with os.scandir(folder) as it:
            for e in it:
                try:
                    if is_media(e.name) and e.is_file():
                        return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


def collect_image_folders(root):
    """Tutte le cartelle con immagini sotto root (root inclusa), in ordine ad albero."""
    out, stack = [], [root]
    while stack:
        f = stack.pop()
        if has_images(f):
            out.append(f)
        stack.extend(reversed(list_subdirs(f)))
    return out


def _index_in(path, lst):
    for i, p in enumerate(lst):
        if samepath(p, path):
            return i
    return None


def dfs_next_folder(path, boundary=None):
    """Cartella successiva nell'albero: prima le sottocartelle, poi le sorelle."""
    subs = list_subdirs(path)
    if subs:
        return subs[0]
    cur = path
    while True:
        if boundary and samepath(cur, boundary):
            return None
        parent = os.path.dirname(cur)
        if not parent or samepath(parent, cur):
            return None
        sibs = list_subdirs(parent)
        idx = _index_in(cur, sibs)
        if idx is not None and idx + 1 < len(sibs):
            return sibs[idx + 1]
        cur = parent


def dfs_prev_folder(path, boundary=None):
    """Cartella precedente nell'albero (inverso di dfs_next_folder)."""
    if boundary and samepath(path, boundary):
        return None
    parent = os.path.dirname(path)
    if not parent or samepath(parent, path):
        return None
    sibs = list_subdirs(parent)
    idx = _index_in(path, sibs)
    if idx:
        node = sibs[idx - 1]
        while True:
            subs = list_subdirs(node)
            if not subs:
                return node
            node = subs[-1]
    return parent


def is_inside(path, root):
    try:
        return os.path.commonpath([os.path.normcase(os.path.abspath(path)),
                                   os.path.normcase(os.path.abspath(root))]) == \
            os.path.normcase(os.path.abspath(root))
    except ValueError:  # dischi diversi
        return False


def browse_boundary(folder):
    """Limite per il salto cartella: la cartella Immagini se ci siamo dentro,
    altrimenti la cartella di primo livello del disco (es. D:\\Foto)."""
    from PySide6.QtCore import QStandardPaths
    pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
    if pics and is_inside(folder, pics):
        return pics
    folder = os.path.abspath(folder)
    chain = [folder]
    while True:
        parent = os.path.dirname(chain[-1])
        if not parent or samepath(parent, chain[-1]):
            break
        chain.append(parent)
    # chain[-1] = radice del disco, chain[-2] = cartella di primo livello
    return chain[-2] if len(chain) >= 2 else chain[-1]


def find_folder_with_images(start, forward=True, boundary=None, max_steps=3000):
    cur = start
    for _ in range(max_steps):
        cur = (dfs_next_folder if forward else dfs_prev_folder)(cur, boundary)
        if cur is None:
            return None
        if has_images(cur):
            return cur
    return None


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            from .i18n import num
            return f"{n:.0f} {unit}" if unit == "B" else f"{num(n, '.1f')} {unit}"
        n /= 1024
    return str(n)


def unique_path(path):
    """Se path esiste, restituisce 'nome (2).ext', 'nome (3).ext', ..."""
    if not os.path.exists(path):
        return path
    if os.path.isdir(path):
        n = 2
        while os.path.exists(f"{path} ({n})"):
            n += 1
        return f"{path} ({n})"
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def show_in_explorer(path):
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        pass
