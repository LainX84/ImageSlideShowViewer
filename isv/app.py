"""Avvio dell'applicazione e coordinamento tra browser e visualizzatori."""
import os
import sys

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtGui import QColor, QIcon, QImageReader, QPalette
from PySide6.QtWidgets import QApplication

from . import APP_ID, APP_NAME, ORG_NAME, __version__, i18n
from .archive import is_archive, is_virtual, parent_of
from .utils import collect_image_folders, has_images, is_image

VERSION = __version__


def dark_palette():
    p = QPalette()
    C = QPalette.ColorRole
    base, win, text = QColor(30, 30, 32), QColor(42, 42, 45), QColor(225, 225, 225)
    p.setColor(C.Window, win)
    p.setColor(C.WindowText, text)
    p.setColor(C.Base, base)
    p.setColor(C.AlternateBase, win)
    p.setColor(C.ToolTipBase, QColor(55, 55, 58))
    p.setColor(C.ToolTipText, text)
    p.setColor(C.Text, text)
    p.setColor(C.Button, win)
    p.setColor(C.ButtonText, text)
    p.setColor(C.BrightText, QColor(255, 80, 80))
    p.setColor(C.Highlight, QColor(52, 120, 200))
    p.setColor(C.HighlightedText, QColor(255, 255, 255))
    p.setColor(C.Link, QColor(90, 160, 240))
    p.setColor(QPalette.ColorGroup.Disabled, C.Text, QColor(120, 120, 120))
    p.setColor(QPalette.ColorGroup.Disabled, C.ButtonText, QColor(120, 120, 120))
    p.setColor(QPalette.ColorGroup.Disabled, C.WindowText, QColor(120, 120, 120))
    return p


def open_settings():
    """Impostazioni dell'utente; al primo avvio importa quelle della vecchia versione (FotoVista)."""
    s = QSettings(ORG_NAME, APP_ID)
    if not s.allKeys():
        old = QSettings("FotoVista", "FotoVista")
        for k in old.allKeys():
            s.setValue(k, old.value(k))
    return s


def expand_folders(folders, include_sub):
    """Cartelle con immagini da mostrare per ogni cartella scelta.
    Se una cartella non ha immagini proprie si entra comunque nelle sottocartelle."""
    out = []
    for f in folders:
        if include_sub or not has_images(f):
            out.extend(collect_image_folders(f))
        else:
            out.append(f)
    return out


class App:
    def __init__(self, qapp, settings):
        from .loader import ImageLoader
        self.qapp = qapp
        self.settings = settings
        self.loader = ImageLoader()
        self.browser = None
        self.viewers = []

    def show_browser(self, path=None):
        from .browser import BrowserWindow
        if self.browser is None:
            self.browser = BrowserWindow(self, self.settings)
            start = path
            if not start:
                last = self.settings.value("browser/last_folder", "")
                pics = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
                start = next((p for p in (last, pics, os.path.expanduser("~")) if p and os.path.isdir(p)))
            self.browser.show()
            if os.path.isfile(start) and not is_archive(start) or is_virtual(start):
                self.browser.set_folder(parent_of(start), select=start)
            else:
                self.browser.set_folder(start)
        else:
            if self.browser.isMinimized():
                self.browser.showNormal()
            self.browser.show()
            self.browser.raise_()
            self.browser.activateWindow()
            if path:
                self.browser.reveal(path)
        return self.browser

    def open_viewer(self, nav, slideshow=False):
        from .viewer import ViewerWindow
        v = ViewerWindow(nav, self.loader, self.settings, slideshow=slideshow)
        v.to_browser.connect(self.show_browser)
        v.closed.connect(lambda p, v=v: self._viewer_closed(v, p))
        v.files_changed.connect(self._files_changed)
        self.viewers.append(v)
        if slideshow or self.settings.value("viewer/fullscreen", False, type=bool):
            v.showFullScreen()
            v.cursor_timer.start()
        else:
            v.showMaximized()
        v.activateWindow()
        return v

    def open_dual(self, left="", right="", parent=None):
        from .dual import DualDialog, DualViewerWindow
        dlg = DualDialog(self.settings, left, right, parent)
        if dlg.exec() != DualDialog.DialogCode.Accepted:
            return None
        sides, interval, paused, shuffle = dlg.values()
        v = DualViewerWindow(sides, self.loader, self.settings, interval, paused, shuffle)
        v.closed.connect(lambda _p, v=v: self.viewers.remove(v) if v in self.viewers else None)
        self.viewers.append(v)
        v.showFullScreen()
        v.cursor_timer.start()
        v.activateWindow()
        return v

    def slideshow_from_paths(self, paths):
        """Slideshow avviato da Esplora risorse su una o più cartelle / archivi / immagini."""
        from .navigator import Navigator
        s = self.settings
        opts = dict(shuffle=s.value("slideshow/random", False, type=bool),
                    loop=s.value("slideshow/loop", True, type=bool),
                    sort=s.value("browser/sort", "name"),
                    reverse=s.value("browser/sort_reverse", False, type=bool))
        sub = s.value("slideshow/subfolders", False, type=bool)
        from .utils import natural_key
        # da Esplora risorse i percorsi arrivano in ordine sparso
        paths = sorted((os.path.abspath(p) for p in paths if os.path.exists(p)),
                       key=lambda p: natural_key(p))
        folders = [p for p in paths if os.path.isdir(p) or is_archive(p)]
        images = [p for p in paths if os.path.isfile(p) and is_image(p)]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if folders:
                nav = Navigator(parent_of(folders[0]), folders=expand_folders(folders, sub), **opts)
            elif len(images) >= 2:
                nav = Navigator(os.path.dirname(images[0]), images=images, **opts)
            elif images:
                nav = Navigator(os.path.dirname(images[0]), start=images[0], include_sub=sub, **opts)
            else:
                nav = None
        finally:
            QApplication.restoreOverrideCursor()
        if nav is None or nav.current() is None:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(None, APP_NAME, i18n.tr("Nessuna immagine trovata."))
            return False
        self.open_viewer(nav, slideshow=True)
        return True

    def _viewer_closed(self, v, path):
        if v in self.viewers:
            self.viewers.remove(v)
        # Dopo uno slideshow il browser resta dov'era (con la selezione);
        # dopo il visualizzatore si posiziona sull'ultima immagine vista.
        if self.browser is not None and self.browser.isVisible() and path \
                and not v.started_as_slideshow:
            self.browser.reveal(path)
            self.browser.activateWindow()

    def _files_changed(self, folder):
        if self.browser is not None and self.browser.folder:
            from .utils import samepath
            if samepath(folder, self.browser.folder):
                self.browser.reload()


def run_shell_action(app, action, paths):
    """Comandi del menu contestuale di Esplora risorse (--slideshow / --rename / --convert)."""
    from PySide6.QtWidgets import QMessageBox
    from . import batch
    if action == "slideshow":
        if app.slideshow_from_paths(paths):
            return app.qapp.exec()
        return 0
    files = sorted({os.path.abspath(p) for p in paths if os.path.isfile(p)},
                   key=lambda p: [os.path.dirname(p).lower()] + batch.natural_key(os.path.basename(p)))
    if action == "convert":
        files = [p for p in files if is_image(p)]
    if not files:
        QMessageBox.information(None, APP_NAME, i18n.tr("Nessun file adatto tra quelli selezionati."))
        return 0
    dlg = batch.RenameDialog if action == "rename" else batch.ConvertDialog
    dlg(files, app.settings, None).run()
    return 0


def main(argv=None):
    argv = sys.argv if argv is None else argv
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = QApplication(argv)
    qapp.setApplicationName(APP_ID)
    qapp.setApplicationDisplayName(APP_NAME)
    qapp.setOrganizationName(ORG_NAME)
    qapp.setApplicationVersion(VERSION)
    qapp.setStyle("Fusion")
    qapp.setPalette(dark_palette())
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.exists(icon):
        qapp.setWindowIcon(QIcon(icon))
    QImageReader.setAllocationLimit(2048)  # MB: consente foto molto grandi

    settings = open_settings()
    i18n.init(settings)  # prima di creare qualsiasi finestra

    args = argv[1:]
    action = None
    for flag in ("--slideshow", "--rename", "--convert"):
        if flag in args:
            action = flag[2:]
            args = [a for a in args if a != flag]
    paths = [a for a in args if not a.startswith("-")]

    if action:
        # Esplora risorse avvia un processo per ogni file selezionato: il primo raccoglie
        # i percorsi di tutti gli altri e apre una sola finestra.
        from .single import collect_paths
        paths = collect_paths(action, paths)
        if paths is None:   # inviati a un'altra istanza già in raccolta
            return 0
        app = App(qapp, settings)
        qapp._isv = app
        return run_shell_action(app, action, paths)

    app = App(qapp, settings)
    target = paths[0] if paths else None
    if target and os.path.isfile(target) and is_image(target):
        # Doppio clic su un file da Esplora risorse: apre subito il visualizzatore.
        from .navigator import Navigator
        target = os.path.abspath(target)
        app.open_viewer(Navigator(os.path.dirname(target), start=target))
    elif target and os.path.isfile(target) and is_archive(target):
        # Doppio clic su un .cbz/.zip: lo apre come un fumetto.
        from .navigator import Navigator
        app.open_viewer(Navigator(os.path.abspath(target)))
    else:
        app.show_browser(os.path.abspath(target) if target and os.path.isdir(target) else None)
    qapp._isv = app
    return qapp.exec()
