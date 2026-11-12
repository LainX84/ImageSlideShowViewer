"""Avvio dell'applicazione e coordinamento tra browser e visualizzatori."""
import os
import sys

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtGui import QIcon, QImageReader
from PySide6.QtWidgets import QApplication

from . import APP_ID, APP_NAME, ORG_NAME, __version__, i18n
from .archive import is_archive, is_virtual, parent_of
from .utils import collect_image_folders, has_images, is_image

VERSION = __version__


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

    def _slideshow_screen(self):
        """Schermo scelto nelle opzioni per lo slideshow (None = quello della finestra)."""
        from PySide6.QtGui import QGuiApplication
        choice = self.settings.value("slideshow/screen", "window")
        screens = QGuiApplication.screens()
        if choice == "primary":
            return QGuiApplication.primaryScreen()
        if choice == "secondary":
            prim = QGuiApplication.primaryScreen()
            others = [s for s in screens if s is not prim]
            return others[0] if others else None
        for s in screens:
            if s.name() == choice:
                return s
        if self.browser is not None and self.browser.isVisible():
            return self.browser.screen()
        return None

    def _place(self, w, fullscreen):
        sc = self._slideshow_screen() if fullscreen else None
        if sc is not None:
            w.setScreen(sc)
            w.move(sc.geometry().topLeft())
            w.resize(sc.geometry().size() * 0.8)

    def open_viewer(self, nav, slideshow=False, screensaver=False):
        from .viewer import ViewerWindow
        v = ViewerWindow(nav, self.loader, self.settings, slideshow=slideshow, screensaver=screensaver)
        v.to_browser.connect(self.show_browser)
        v.closed.connect(lambda p, v=v: self._viewer_closed(v, p))
        v.files_changed.connect(self._files_changed)
        v.webtoon_requested.connect(self.open_webtoon)
        self.viewers.append(v)
        if slideshow or self.settings.value("viewer/fullscreen", False, type=bool):
            self._place(v, True)
            v.showFullScreen()
            v.cursor_timer.start()
        else:
            v.showMaximized()
        v.activateWindow()
        return v

    def open_webtoon(self, paths, start=0):
        from .webtoon import WebtoonView
        w = WebtoonView(paths, start, self.settings)
        w.closed.connect(lambda p, w=w: self._webtoon_closed(w, p))
        self.viewers.append(w)
        self._place(w, True)
        w.showMaximized()
        w.activateWindow()
        return w

    def _webtoon_closed(self, w, path):
        if w in self.viewers:
            self.viewers.remove(w)
        if self.browser is not None and self.browser.isVisible() and path:
            self.browser.reveal(path)

    def open_compare(self, a, b):
        from .compare import CompareWindow
        w = CompareWindow(a, b)
        if not w.ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.browser, APP_NAME, i18n.tr("Impossibile aprire le immagini da confrontare."))
            w.deleteLater()
            return None
        w.show()
        return w

    def offer_nvidia(self):
        """Con una scheda NVIDIA propone (all'avvio) di scaricare il supporto per la GPU."""
        from . import gpudecode, nvsupport
        s = self.settings
        if s.value("nvidia/offer", "ask") == "never" or not nvsupport.supported():
            return
        if nvsupport.installed() or not nvsupport.driver_present() or gpudecode.available():
            return
        from PySide6.QtWidgets import QMessageBox
        parent = self.browser if self.browser is not None and self.browser.isVisible() else None
        name = nvsupport.gpu_name()
        box = QMessageBox(parent)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(i18n.tr("Hai una scheda NVIDIA{name}.", name=f" ({name})" if name else ""))
        box.setInformativeText(i18n.tr(
            "Vuoi scaricare il supporto per decodificare i JPEG grandi con la scheda video?\n"
            "Sono le librerie ufficiali NVIDIA (nvImageCodec e nvJPEG, circa 25 MB), prese da PyPI.\n\n"
            "Si può fare anche dopo, o togliere, da Opzioni → Animazioni e GPU."))
        b_yes = box.addButton(i18n.tr("Scarica e installa"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(i18n.tr("Più tardi"), QMessageBox.ButtonRole.RejectRole)
        b_never = box.addButton(i18n.tr("Non chiedere più"), QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(b_yes)
        box.exec()
        if box.clickedButton() is b_never:
            s.setValue("nvidia/offer", "never")
        elif box.clickedButton() is b_yes:
            from .options import install_nvidia
            install_nvidia(parent, s)

    def start_screensaver(self):
        """Slideshow casuale a schermo intero (salvaschermo)."""
        if any(getattr(v, "screensaver", False) for v in self.viewers):
            return
        s = self.settings
        folder = s.value("screensaver/folder", "") or s.value("browser/last_folder", "")
        if not folder or not os.path.isdir(folder):
            return
        from .navigator import Navigator
        try:
            nav = Navigator(folder, include_sub=s.value("screensaver/subfolders", True, type=bool),
                            shuffle=True, loop=True)
        except Exception:  # noqa: BLE001
            return
        if nav.current() is None:
            return
        self.open_viewer(nav, slideshow=True, screensaver=True)

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
        if self.browser is not None and self.browser.virtual is not None:
            self.browser.reload()
            return
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
    from . import gpu, gpudecode
    gpu.configure(open_settings())   # OpenGL hardware / software / CPU: prima di QApplication
    qapp = QApplication(argv)
    qapp.setApplicationName(APP_ID)
    qapp.setApplicationDisplayName(APP_NAME)
    qapp.setOrganizationName(ORG_NAME)
    qapp.setApplicationVersion(VERSION)
    qapp.setStyle("Fusion")
    icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
    if os.path.exists(icon):
        qapp.setWindowIcon(QIcon(icon))
    QImageReader.setAllocationLimit(2048)  # MB: consente foto molto grandi

    settings = open_settings()
    gpudecode.set_enabled(settings.value("gpu/nvjpeg", False, type=bool))
    from . import utils as _utils
    _utils.SHOW_VIDEOS = settings.value("slideshow/videos", True, type=bool)
    i18n.init(settings)  # prima di creare qualsiasi finestra
    from . import theme
    theme.init(qapp, settings)  # chiaro / scuro / automatico

    args = argv[1:]
    action = None
    args = [a for a in args if a != "--screensaver"]
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
    from .screensaver import IdleMonitor
    from .undo import manager as undo_manager
    qapp.aboutToQuit.connect(undo_manager.flush)     # eliminati in sospeso -> Cestino
    app.idle = IdleMonitor(qapp, settings, app.start_screensaver)
    if "--screensaver" in argv:
        f = paths[0] if paths and os.path.isdir(paths[0]) else None
        if f:
            settings.setValue("screensaver/folder", os.path.abspath(f))
        app.start_screensaver()
        qapp._isv = app
        return qapp.exec()
    target = paths[0] if paths else None
    from .utils import is_media
    if target and os.path.isfile(target) and is_media(target):
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
    from PySide6.QtCore import QTimer
    QTimer.singleShot(2500, app.offer_nvidia)
    qapp._isv = app
    return qapp.exec()
