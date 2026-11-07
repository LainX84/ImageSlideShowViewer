"""Menu contestuale di Esplora risorse (tasto destro su cartelle, archivi e immagini).

Le voci vengono scritte solo per l'utente corrente (HKEY_CURRENT_USER\\Software\\Classes),
quindi non servono permessi di amministratore e si tolgono senza lasciare tracce.
Su Windows 11 compaiono sotto "Mostra altre opzioni" (o Maiusc+F10).
"""
import os
import sys

from . import APP_ID, APP_NAME
from .i18n import tr

KEY = APP_ID                        # nome della voce nel registro
ROOT = r"Software\Classes"
ARCHIVES = (".cbz", ".zip")


def supported():
    return sys.platform == "win32"


def _image_exts():
    from .utils import _WANTED
    return ["." + e for e in _WANTED]


def _launcher():
    """(eseguibile, argomenti iniziali) per avviare il programma da Esplora risorse."""
    if getattr(sys, "frozen", False):
        return sys.executable, []
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        w = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(w):
            exe = w
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "image_slideshow_viewer.pyw")
    return exe, [script]


def _command(action, arg="%1"):
    exe, pre = _launcher()
    parts = [exe] + pre + [f"--{action}", arg]
    return " ".join(f'"{p}"' for p in parts)


def _icon():
    exe, pre = _launcher()
    if not pre:
        return f'"{exe}",0'
    ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    return f'"{ico}"' if os.path.exists(ico) else f'"{exe}",0'


def _targets():
    """[(chiave della classe, [(azione, etichetta)], argomento)]"""
    show = ("slideshow", tr("Avvia slideshow"))
    ren = ("rename", tr("Rinomina in blocco…"))
    conv = ("convert", tr("Converti formato…"))
    out = [(r"Directory", [show], "%1"),
           (r"Directory\Background", [show], "%V"),
           (r"Drive", [show], "%1")]
    for ext in ARCHIVES:
        out.append((rf"SystemFileAssociations\{ext}", [show, ren], "%1"))
    for ext in _image_exts():
        out.append((rf"SystemFileAssociations\{ext}", [show, ren, conv], "%1"))
    return out


def _all_class_keys():
    keys = {k for k, _, _ in _targets()}
    return sorted(keys)


def _delete_tree(winreg, root, path):
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as k:
            subs, i = [], 0
            while True:
                try:
                    subs.append(winreg.EnumKey(k, i))
                    i += 1
                except OSError:
                    break
        for sub in subs:
            _delete_tree(winreg, root, path + "\\" + sub)
        winreg.DeleteKey(root, path)
    except OSError:
        pass


def _notify():
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:  # noqa: BLE001
        pass


def is_installed():
    if not supported():
        return False
    import winreg
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{ROOT}\Directory\shell\{KEY}").Close()
        return True
    except OSError:
        return False


def install():
    """Crea (o aggiorna) il sottomenu "Image SlideShow Viewer". Solleva OSError."""
    if not supported():
        raise OSError(tr("Disponibile solo su Windows."))
    import winreg
    HK = winreg.HKEY_CURRENT_USER
    uninstall(notify=False)
    icon = _icon()
    for cls, actions, arg in _targets():
        base = rf"{ROOT}\{cls}\shell\{KEY}"
        with winreg.CreateKey(HK, base) as k:
            winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "SubCommands", 0, winreg.REG_SZ, "")
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon)
            # più di 15 file selezionati: senza questo Windows nasconde la voce
            winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
        for i, (action, label) in enumerate(actions, 1):
            sub = rf"{base}\shell\{i:02d}{action}"
            with winreg.CreateKey(HK, sub) as k:
                winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, label)
                winreg.SetValueEx(k, "MultiSelectModel", 0, winreg.REG_SZ, "Player")
            with winreg.CreateKey(HK, sub + r"\command") as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, _command(action, arg))
    _notify()


def uninstall(notify=True):
    if not supported():
        return
    import winreg
    for cls in _all_class_keys():
        _delete_tree(winreg, winreg.HKEY_CURRENT_USER, rf"{ROOT}\{cls}\shell\{KEY}")
    if notify:
        _notify()


def refresh_if_moved():
    """Se il programma è stato spostato (o si passa dal .pyw al .exe), riscrive le voci."""
    if not is_installed():
        return
    import winreg
    path = rf"{ROOT}\Directory\shell\{KEY}\shell\01slideshow\command"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            cur, _ = winreg.QueryValueEx(k, "")
    except OSError:
        cur = ""
    if cur != _command("slideshow", "%1"):
        try:
            install()
        except OSError:
            pass
