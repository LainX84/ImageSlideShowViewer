"""Supporto GPU NVIDIA scaricato su richiesta (decodifica JPEG con nvImageCodec / nvJPEG).

Le librerie NVIDIA pesano qualche decina di MB e servono solo a chi ha una scheda
NVIDIA, quindi non sono incluse nel programma: se all'avvio viene trovato il driver
NVIDIA, il programma propone di scaricarle (una volta sola). Si possono installare,
reinstallare o togliere anche da Opzioni → Animazioni e GPU.

Il download viene dai pacchetti ufficiali su PyPI (nvidia-nvimgcodec-cu12 e
nvidia-nvjpeg-cu12), controllati con l'impronta SHA-256 pubblicata da PyPI, ed estratti
nella cartella dei dati del programma: non serve pip, quindi funziona anche con il
programma compilato (.exe). Si tiene solo il necessario (decoder JPEG, la versione per
questo Python), circa 15 MB su disco.

Disponibile su Windows x64 e Linux x64 (NVIDIA non pubblica questi pacchetti per macOS).
"""
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import zipfile

PACKAGES = ["nvidia-nvimgcodec-cu12", "nvidia-nvjpeg-cu12"]
PYPI = "https://pypi.org/pypi/{name}/json"

_activated = None       # cartella attivata in questo processo
_dll_handles = []
_preloaded = []


# ----------------------------------------------------------------- dove / cosa
def supported():
    """Piattaforma per cui NVIDIA pubblica i pacchetti."""
    m = platform.machine().lower()
    return (sys.platform == "win32" and m in ("amd64", "x86_64")) or \
        (sys.platform.startswith("linux") and m in ("x86_64", "amd64"))


def root_dir():
    from PySide6.QtCore import QStandardPaths
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    base = base or os.path.expanduser("~/.local/share/ImageSlideShowViewer")
    d = os.path.join(base, "nvidia-gpu")
    os.makedirs(d, exist_ok=True)
    return d


def _py_tag():
    return f"{sys.version_info.major}{sys.version_info.minor}"


def info():
    """Dati dell'installazione attuale (dict) oppure None."""
    try:
        with open(os.path.join(root_dir(), "current.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    folder = os.path.join(root_dir(), data.get("folder", ""))
    if not data.get("folder") or not os.path.isdir(folder):
        return None
    data["path"] = folder
    return data


def installed():
    i = info()
    return bool(i) and i.get("python") == _py_tag()


# -------------------------------------------------------------- scheda NVIDIA
def driver_present():
    """True se è installato il driver NVIDIA (con CUDA)."""
    try:
        if sys.platform == "win32":
            sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
            return os.path.exists(os.path.join(sysdir, "nvcuda.dll"))
        if sys.platform.startswith("linux"):
            if os.path.exists("/proc/driver/nvidia/version"):
                return True
            import ctypes.util
            return ctypes.util.find_library("cuda") is not None
    except Exception:  # noqa: BLE001
        pass
    return False


def gpu_name():
    """Nome della scheda NVIDIA, se si riesce a saperlo (per i messaggi)."""
    try:
        from . import gpu
        i = gpu.probe() if gpu.mode() != "cpu" else None
        if i and "nvidia" in (i.get("vendor", "") + i.get("renderer", "")).lower():
            return i["renderer"].split("/")[0].strip()
    except Exception:  # noqa: BLE001
        pass
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            import subprocess
            r = subprocess.run([exe, "--query-gpu=name", "--format=csv,noheader"], capture_output=True,
                               text=True, timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip().splitlines()[0]
        except Exception:  # noqa: BLE001
            pass
    return ""


# ------------------------------------------------------------------ attivazione
def activate():
    """Rende importabili le librerie installate (da chiamare prima di usarle)."""
    global _activated
    if _activated:
        return True
    i = info()
    if not i or i.get("python") != _py_tag():
        return False
    folder = i["path"]
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import ctypes
    libs = []
    for sub in ("nvidia/nvjpeg/bin", "nvidia/nvjpeg/lib", "nvidia/nvimgcodec"):
        d = os.path.join(folder, *sub.split("/"))
        if not os.path.isdir(d):
            continue
        if sys.platform == "win32":
            try:
                _dll_handles.append(os.add_dll_directory(d))
            except OSError:
                pass
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        libs += [os.path.join(d, n) for n in sorted(os.listdir(d))
                 if n.lower().endswith(".dll") or ".so" in n]
    # caricate subito per percorso completo: quando nvImageCodec le cerca per nome le
    # trova già in memoria (nvJPEG per primo, perché le altre ne dipendono)
    libs.sort(key=lambda p: 0 if "nvjpeg" in os.path.basename(p).lower() else 1)
    for p in libs:
        try:
            _preloaded.append(ctypes.WinDLL(p) if sys.platform == "win32"
                              else ctypes.CDLL(p, mode=getattr(ctypes, "RTLD_GLOBAL", 0)))
        except OSError:
            pass
    _activated = folder
    _cleanup_old(i["folder"])
    return True


def activated_folder():
    return _activated


def _cleanup_old(keep):
    """Toglie le installazioni precedenti (non più in uso)."""
    r = root_dir()
    for n in os.listdir(r):
        p = os.path.join(r, n)
        if n != keep and os.path.isdir(p) and n.startswith("nv-"):
            shutil.rmtree(p, ignore_errors=True)


# ------------------------------------------------------------- scaricamento
def _ssl_context():
    import ssl
    custom = os.environ.get("SSL_CERT_FILE")      # proxy aziendali con un loro certificato
    if custom and os.path.exists(custom):
        return ssl.create_default_context(cafile=custom)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _open(url, timeout=30):
    import urllib.request
    from . import __version__
    req = urllib.request.Request(url, headers={"User-Agent": f"ImageSlideShowViewer/{__version__}"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def _platform_ok(filename):
    f = filename.lower()
    if sys.platform == "win32":
        return f.endswith("win_amd64.whl")
    return "x86_64" in f and ("manylinux" in f or "linux" in f)


def _pick_wheel(name):
    """(versione, url, sha256, dimensione) del pacchetto per questa piattaforma."""
    with _open(PYPI.format(name=name)) as r:
        data = json.load(r)
    version = data["info"]["version"]
    for f in data.get("urls", []):
        if f.get("packagetype") == "bdist_wheel" and _platform_ok(f["filename"]):
            return version, f["url"], f["digests"]["sha256"], f.get("size", 0)
    raise OSError(f"{name} {version}: nessun pacchetto per questo sistema")


def _download(url, sha, size, dst, progress, done, total):
    h = hashlib.sha256()
    with _open(url, timeout=60) as r, open(dst, "wb") as out:
        got = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress(done + got, total, None):
                raise InterruptedError
    if h.hexdigest() != sha:
        raise OSError("SHA-256 non corrispondente: download danneggiato")
    return got


def _wanted(member, tag):
    """Solo quello che serve per decodificare i JPEG con questo Python."""
    n = member.replace("\\", "/")
    low = n.lower()
    if low.endswith("/") or ".dist-info/" in low and not low.endswith(("license.txt", "license")):
        return False
    if "/include/" in low or low.endswith((".h", ".hpp", ".lib", ".a")):
        return False
    base = os.path.basename(low)
    if "nvimgcodec_impl" in base:     # modulo Python: solo quello di questa versione
        return f".cp{tag}-" in base or f"cpython-{tag}-" in base
    if "/extensions/" in low:         # dei decoder aggiuntivi serve solo nvJPEG
        return "nvjpeg_ext" in base
    return True


def install(progress):
    """Scarica e installa. progress(i, n, testo) -> True per annullare.
    Ritorna il dict con le versioni installate. Solleva OSError."""
    from .i18n import tr
    if not supported():
        raise OSError(tr("Il supporto NVIDIA non è disponibile per questo sistema."))
    progress(0, 0, tr("Ricerca dei pacchetti NVIDIA…"))
    picks = [(n,) + _pick_wheel(n) for n in PACKAGES]
    total = sum(p[4] for p in picks) or 1
    tmp = tempfile.mkdtemp(prefix="isv-nvidia-")
    folder_name = f"nv-{int(time.time())}"
    target = os.path.join(root_dir(), folder_name)
    tag = _py_tag()
    versions = {}
    try:
        done = 0
        files = []
        for name, version, url, sha, size in picks:
            label = tr("Scaricamento di {name} {v}…", name=name, v=version)

            def prog(i, n, _t, label=label):
                return progress(i, n, label)
            dst = os.path.join(tmp, os.path.basename(url.split("?")[0]))
            done += _download(url, sha, size, dst, prog, done, total)
            files.append(dst)
            versions[name] = version
        progress(total, total, tr("Installazione…"))
        os.makedirs(target, exist_ok=True)
        for w in files:
            with zipfile.ZipFile(w) as z:
                for m in z.infolist():
                    if not _wanted(m.filename, tag):
                        continue
                    out = os.path.normpath(os.path.join(target, m.filename))
                    if not out.startswith(os.path.normpath(target) + os.sep):
                        continue        # percorso fuori dalla cartella: ignorato
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with z.open(m) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if sys.platform != "win32":
                        os.chmod(out, 0o755)
        data = {"folder": folder_name, "python": tag, "versions": versions, "date": time.time()}
        tmpjson = os.path.join(root_dir(), "current.json.tmp")
        with open(tmpjson, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmpjson, os.path.join(root_dir(), "current.json"))
        if not _activated:
            _cleanup_old(folder_name)
        return data
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def uninstall():
    """Toglie le librerie scaricate (quelle in uso si cancellano al prossimo avvio)."""
    try:
        os.remove(os.path.join(root_dir(), "current.json"))
    except OSError:
        pass
    r = root_dir()
    for n in os.listdir(r):
        p = os.path.join(r, n)
        if os.path.isdir(p) and (not _activated or os.path.normpath(p) != os.path.normpath(_activated)):
            shutil.rmtree(p, ignore_errors=True)


def size_on_disk():
    i = info()
    if not i:
        return 0
    tot = 0
    for root, _d, files in os.walk(i["path"]):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return tot


def describe():
    """Riga di stato per le opzioni."""
    from .i18n import tr
    from .utils import human_size
    if not supported():
        return tr("Supporto NVIDIA non disponibile su questo sistema.")
    card = gpu_name() if driver_present() else ""
    head = (tr("Scheda NVIDIA: {name}", name=card) if card else
            tr("Driver NVIDIA trovato") if driver_present() else tr("Nessuna scheda NVIDIA trovata"))
    i = info()
    if i and i.get("python") == _py_tag():
        v = ", ".join(f"{k.replace('nvidia-', '').replace('-cu12', '')} {ver}" for k, ver in i["versions"].items())
        return head + "  ·  " + tr("Librerie installate: {v} ({size})", v=v, size=human_size(size_on_disk()))
    if i:
        return head + "  ·  " + tr("Librerie da reinstallare (installate per un'altra versione di Python)")
    return head + "  ·  " + tr("Librerie non installate")
