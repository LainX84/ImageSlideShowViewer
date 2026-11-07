"""Image SlideShow Viewer – image viewer and slideshow in the style of ACDSee.

Double-click this file to start it (.pyw does not open a console window).
On first run, if PySide6 is missing, it offers to install it. Errors are shown in a
message box and saved to image-slideshow-viewer-error.log.

Command line:
    image_slideshow_viewer.pyw [folder | image | archive.cbz]
    image_slideshow_viewer.pyw --slideshow <folder|archive|images...>
    image_slideshow_viewer.pyw --rename <files...>
    image_slideshow_viewer.pyw --convert <images...>
"""
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TITLE = "Image SlideShow Viewer"


def _italian():
    if sys.platform == "win32":
        try:
            import ctypes
            return ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x10
        except Exception:  # noqa: BLE001
            return False
    return os.environ.get("LANG", "").lower().startswith("it")


IT = _italian()


def T(it, en):
    return it if IT else en


def message(text, ask=False):
    """Message box that does not need Qt (which might be missing)."""
    if sys.platform == "win32":
        import ctypes
        flags = (0x04 | 0x20) if ask else 0x10  # Yes/No + question, or error
        return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags) == 6
    print(f"{TITLE}: {text}", file=sys.stderr)
    return False


def ensure_pyside():
    try:
        import PySide6  # noqa: F401
        return True
    except ImportError:
        pass
    if not message(T("Per funzionare Image SlideShow Viewer ha bisogno della libreria PySide6 "
                     "(circa 100 MB).\n\nInstallarla adesso?",
                     "Image SlideShow Viewer needs the PySide6 library (about 100 MB).\n\n"
                     "Install it now?"), ask=True):
        return False
    # python.exe next to pythonw.exe, so pip does not open extra windows
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        exe = exe[:-len("pythonw.exe")] + "python.exe"
    r = subprocess.run([exe, "-m", "pip", "install", "PySide6>=6.5"],
                       capture_output=True, text=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        message(T("Installazione di PySide6 non riuscita:", "PySide6 installation failed:")
                + "\n\n" + (r.stderr or r.stdout)[-1500:])
        return False
    return True


def run():
    if not ensure_pyside():
        return 1
    try:
        from isv.app import main
        return main()
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else HERE
        log = os.path.join(base, "image-slideshow-viewer-error.log")
        try:
            with open(log, "w", encoding="utf-8") as f:
                f.write(tb)
        except OSError:
            log = T("(impossibile scrivere il log)", "(could not write the log)")
        message(T("Il programma si è chiuso per un errore:", "The program closed because of an error:")
                + f"\n\n{tb[-1200:]}\n\n" + T("Dettagli in: ", "Details in: ") + log)
        return 1


if __name__ == "__main__":
    sys.exit(run())
