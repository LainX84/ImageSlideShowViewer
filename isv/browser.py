"""Finestra principale: albero cartelle + griglia miniature (come la modalità Gestione di ACDSee)."""
import os

from PySide6.QtCore import QDir, QFileSystemWatcher, QItemSelection, QItemSelectionModel, QSize, Qt, QTimer, QStandardPaths, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFileDialog, QFileSystemModel, QLabel,
                               QLineEdit, QListView, QMainWindow, QMenu, QMessageBox,
                               QSlider, QSplitter, QStyle, QToolBar, QTreeView)

from . import batch, fileops
from .archive import is_archive, parent_of
from .navigator import Navigator
from .thumbs import ThumbDelegate, ThumbModel
from . import APP_NAME, shell
from .app import expand_folders
from .i18n import LANGUAGES, tr
from .utils import (has_images, human_size, list_folder_items,
                    list_unc_shares, samepath, show_in_explorer, unc_parent, unc_server)

SORT_KEYS = ["name", "date", "size"]


def sort_names():
    return [tr("Nome"), tr("Data"), tr("Dimensione")]


def help_html():
    rows_b = [
        (tr("<b>Invio</b> / doppio clic"), tr("apri la cartella o l'immagine")),
        ("<b>F5</b>", tr("slideshow: cartelle selezionate, immagini selezionate o cartella corrente")),
        (tr("<b>Maiusc+F5</b>"), tr("slideshow di 2 cartelle affiancate")),
        ("<b>F2</b>", tr("rinomina (più file selezionati: rinomina in blocco)")),
        ("<b>Ctrl+F2</b>", tr("rinomina in blocco")),
        ("<b>Ctrl+X / C / V</b>", tr("taglia / copia / incolla (anche con Esplora risorse)")),
        (tr("<b>Ctrl+Maiusc+N</b>"), tr("nuova cartella")),
        ("<b>Ctrl+P</b>", tr("stampa")),
        (tr("<b>Alt+Invio</b>"), tr("informazioni immagine ed EXIF (sulle cartelle: proprietà)")),
        (tr("<b>Ctrl+Maiusc+C</b>"), tr("converti formato")),
        (tr("<b>Canc</b>"), tr("sposta nel Cestino")),
        ("<b>Backspace</b> / Alt+↑", tr("cartella superiore")),
        ("<b>Ctrl+R</b>", tr("aggiorna")),
        (tr("tasto destro"), tr("menu con tutti i comandi sui file selezionati")),
    ]
    rows_v = [
        (tr("<b>→ ←</b>, PagGiù/PagSu, rotellina"), tr("immagine successiva / precedente")),
        ("<b>↓ ↑</b>, Ctrl+→/←", tr("cartella successiva / precedente")),
        (tr("<b>Spazio</b> / P"), tr("avvia / ferma lo slideshow")),
        ("<b>S</b>", tr("ferma lo slideshow")),
        ("<b>D</b>", tr("due immagini affiancate sì/no")),
        ("<b>O</b>", tr("opzioni: nome cartella sì/no, colori, barra comandi")),
        (tr("muovi il mouse"), tr("barra dei comandi (avvia/ferma, cartelle, intervallo)")),
        ("<b>+ −</b>", tr("intervallo più lungo / più corto (in slideshow)")),
        (tr("<b>Home / Fine</b>"), tr("prima / ultima immagine della cartella")),
        (tr("<b>F</b> / F11 / doppio clic"), tr("schermo intero")),
        ("<b>Z</b> / *", tr("adatta alla finestra ↔ 100%")),
        (tr("<b>Ctrl+rotellina</b>"), tr("zoom (trascina per spostarti)")),
        ("<b>I</b>", tr("mostra / nascondi informazioni")),
        (tr("<b>Canc</b>"), tr("sposta nel Cestino")),
        ("<b>F2</b>", tr("rinomina l'immagine")),
        ("<b>Ctrl+C</b>", tr("copia l'immagine negli appunti")),
        (tr("<b>Invio</b>"), tr("torna al browser su questa immagine")),
        ("<b>Esc</b>", tr("chiudi")),
    ]

    def table(rows):
        return "<table cellspacing=4>" + "".join(
            f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows) + "</table>"

    return (f"<h3>Browser</h3>{table(rows_b)}"
            f"<h3>{tr('Visualizzatore e slideshow')}</h3>{table(rows_v)}")


class BrowserWindow(QMainWindow):
    def __init__(self, app, settings):
        super().__init__()
        self.app, self.settings = app, settings
        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.folder = None
        self.history = []

        # --- albero cartelle
        self.fs = QFileSystemModel(self)
        self.fs.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Drives)
        self.fs.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fs)
        for c in range(1, 4):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(False)
        self.tree.setMinimumWidth(180)
        self.tree.selectionModel().currentChanged.connect(self._tree_changed)

        # --- miniature
        self.model = ThumbModel(self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(ThumbDelegate(self.view))
        self.view.setViewMode(QListView.ViewMode.IconMode)
        self.view.setResizeMode(QListView.ResizeMode.Adjust)
        self.view.setMovement(QListView.Movement.Static)
        self.view.setUniformItemSizes(True)
        self.view.setSpacing(2)
        self.view.setMouseTracking(True)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setLayoutMode(QListView.LayoutMode.Batched)
        self.view.setBatchSize(300)
        self.view.doubleClicked.connect(lambda idx: self.activate(idx.row()))
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.selectionModel().selectionChanged.connect(self._update_status)

        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 1000])
        self.split = split
        self.setCentralWidget(split)

        self._build_actions()
        self._build_toolbars()
        self._build_menus()
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._reload_timer.start())
        self._reload_timer = QTimer(self, singleShot=True, interval=600)
        self._reload_timer.timeout.connect(self.reload)

        g = settings.value("browser/geometry")
        if g is not None:
            self.restoreGeometry(g)
        s = settings.value("browser/splitter")
        if s is not None:
            self.split.restoreState(s)
        QTimer.singleShot(1500, shell.refresh_if_moved)

    # ------------------------------------------------------------ interfaccia
    def _act(self, text, slot, shortcut=None, icon=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if icon is not None:
            a.setIcon(self.style().standardIcon(icon))
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_actions(self):
        SP = QStyle.StandardPixmap
        self.a_back = self._act(tr("Indietro"), self.go_back, "Alt+Left", SP.SP_ArrowBack)
        self.a_up = self._act(tr("Su"), self.go_up, "Alt+Up", SP.SP_ArrowUp)
        self.a_pics = self._act(tr("Immagini"), self.go_pictures, None, SP.SP_DirHomeIcon)
        self.a_refresh = self._act(tr("Aggiorna"), self.reload, "Ctrl+R", SP.SP_BrowserReload)
        self.a_open_dir = self._act(tr("Apri cartella…"), self.choose_folder, "Ctrl+O")
        self.a_view = self._act(tr("Visualizza"), lambda: self.open_viewer(), None)
        self.a_show = self._act(tr("▶  Slideshow"), self.start_slideshow, "F5")
        self.a_show.setShortcuts([QKeySequence("F5"), QKeySequence("Ctrl+S")])
        self.a_dual = self._act(tr("Slideshow di 2 cartelle affiancate…"), self.dual_slideshow, "Shift+F5")
        self.a_rename = self._act(tr("Rinomina in blocco…"), self.batch_rename, "Ctrl+F2")
        self.a_rename1 = self._act(tr("Rinomina"), self.rename_item, "F2")
        self.a_cut = self._act(tr("Taglia"), lambda: self.to_clipboard(True), "Ctrl+X")
        self.a_copyclip = self._act(tr("Copia"), lambda: self.to_clipboard(False), "Ctrl+C")
        self.a_paste = self._act(tr("Incolla"), self.paste, "Ctrl+V")
        self.a_newdir = self._act(tr("Nuova cartella…"), self.make_folder, "Ctrl+Shift+N")
        self.a_open_def = self._act(tr("Programma predefinito"), lambda: self._each_file(fileops.open_default))
        self.a_open_with = self._act(tr("Scegli un programma…"), lambda: self._each_file(fileops.open_with, 1))
        self.a_paint = self._act(tr("Modifica con Paint"), lambda: self._each_file(fileops.edit_with_paint))
        self.a_wall = self._act(tr("Imposta come sfondo del desktop"), self.set_wallpaper)
        self.a_print = self._act(tr("Stampa…"), self.print_selected, "Ctrl+P")
        self.a_copypath = self._act(tr("Copia percorso"), self.copy_paths)
        self.a_props = self._act(tr("Proprietà"), self.properties)
        self.a_info = self._act(tr("Informazioni immagine (EXIF)…"), self.image_info, "Alt+Return")
        self.a_convert = self._act(tr("Converti formato…"), self.batch_convert, "Ctrl+Shift+C")
        self.a_copy = self._act(tr("Copia in…"), lambda: self.batch_copy(False), "Ctrl+Shift+K")
        self.a_move = self._act(tr("Sposta in…"), lambda: self.batch_copy(True), "Ctrl+Shift+M")
        self.a_delete = self._act(tr("Elimina (Cestino)"), self.batch_delete, "Del")
        self.a_selall = self._act(tr("Seleziona tutto"), self.view.selectAll, "Ctrl+A")
        self.a_explorer = self._act(tr("Mostra in Esplora risorse"), self.reveal_in_explorer)
        self.a_options = self._act(tr("Opzioni visualizzatore e slideshow…"), self.show_options)
        self.a_shell = self._act(tr("Menu contestuale di Esplora risorse"), self.toggle_shell_menu)
        self.a_shell.setCheckable(True)
        self.a_shell.setEnabled(shell.supported())
        self.a_help = self._act(tr("Scorciatoie da tastiera"), self.show_help, "F1")
        self.a_about = self._act(tr("Informazioni su {app}…", app=APP_NAME), self.show_about)
        self.a_quit = self._act(tr("Esci"), self.close, "Ctrl+Q")
        for a in (self.a_delete, self.a_selall, self.a_cut, self.a_copyclip, self.a_paste,
                  self.a_rename1, self.a_info):
            a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            self.view.addAction(a)
        bk = self._act("", self.go_up, "Backspace")
        bk.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.view.addAction(bk)
        ent = QAction(self.view)
        ent.setShortcuts([QKeySequence("Return"), QKeySequence("Enter")])
        ent.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        ent.triggered.connect(lambda: self.activate())
        self.view.addAction(ent)

    def _build_toolbars(self):
        tb = QToolBar(tr("Navigazione"))
        tb.setObjectName("nav")
        tb.setMovable(False)
        tb.addAction(self.a_back)
        tb.addAction(self.a_up)
        tb.addAction(self.a_pics)
        tb.addAction(self.a_refresh)
        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(lambda: self.set_folder(self.path_edit.text().strip()))
        tb.addWidget(self.path_edit)
        self.addToolBar(tb)
        self.addToolBarBreak()

        st = QToolBar("Slideshow")
        st.setObjectName("slideshow")
        st.setMovable(False)
        st.addAction(self.a_show)
        s = self.settings
        st.addWidget(QLabel("  " + tr("Intervallo") + " "))
        self.sp_interval = QDoubleSpinBox(minimum=0.5, maximum=600, singleStep=0.5, decimals=1)
        self.sp_interval.setSuffix(" s")
        self.sp_interval.setValue(s.value("slideshow/interval", 4.0, type=float))
        self.sp_interval.valueChanged.connect(lambda v: s.setValue("slideshow/interval", v))
        st.addWidget(self.sp_interval)
        self.ck_random = QCheckBox(tr("Casuale"))
        self.ck_loop = QCheckBox(tr("Ripeti"))
        self.ck_sub = QCheckBox(tr("Includi sottocartelle"))
        self.ck_pair = QCheckBox(tr("2 affiancate"))
        self.ck_pair.setToolTip(tr("Mostra due immagini alla volta, una accanto all'altra: "
                                   "1-2, poi 3-4, 5-6… (nello slideshow anche con il tasto D)"))
        self.ck_manga = QCheckBox(tr("Manga"))
        self.ck_manga.setToolTip(tr("Con 2 affiancate: lettura da destra a sinistra, la 1 a destra e la 2 "
                                    "a sinistra, poi 3 a destra e 4 a sinistra… "
                                    "(nello slideshow anche con il tasto M)"))
        for ck, key, default in ((self.ck_random, "random", False), (self.ck_loop, "loop", True),
                                 (self.ck_sub, "subfolders", False), (self.ck_pair, "pair", False),
                                 (self.ck_manga, "manga", False)):
            ck.setChecked(s.value(f"slideshow/{key}", default, type=bool))
            ck.toggled.connect(lambda v, k=key: s.setValue(f"slideshow/{k}", v))
            st.addWidget(QLabel(" "))
            st.addWidget(ck)
        self.ck_manga.setEnabled(self.ck_pair.isChecked())
        self.ck_pair.toggled.connect(self.ck_manga.setEnabled)
        st.addSeparator()
        st.addWidget(QLabel(" " + tr("Ordina per") + " "))
        self.cb_sort = QComboBox()
        self.cb_sort.addItems(sort_names())
        keys = SORT_KEYS
        cur = s.value("browser/sort", "name")
        self.cb_sort.setCurrentIndex(keys.index(cur) if cur in keys else 0)
        self.cb_sort.currentIndexChanged.connect(self._sort_changed)
        st.addWidget(self.cb_sort)
        self.ck_rev = QCheckBox(tr("Decrescente"))
        self.ck_rev.setChecked(s.value("browser/sort_reverse", False, type=bool))
        self.ck_rev.toggled.connect(self._sort_changed)
        st.addWidget(QLabel(" "))
        st.addWidget(self.ck_rev)
        st.addSeparator()
        st.addWidget(QLabel(" " + tr("Miniature") + " "))
        self.sl_size = QSlider(Qt.Orientation.Horizontal)
        self.sl_size.setRange(64, 240)
        self.sl_size.setFixedWidth(140)
        self.sl_size.setValue(s.value("browser/thumb_size", 150, type=int))
        self.sl_size.valueChanged.connect(self._thumb_size)
        st.addWidget(self.sl_size)
        self.addToolBar(st)
        self._thumb_size(self.sl_size.value())

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        m.addAction(self.a_open_dir)
        m.addAction(self.a_newdir)
        m.addAction(self.a_explorer)
        m.addSeparator()
        m.addAction(self.a_print)
        m.addAction(self.a_props)
        m.addSeparator()
        m.addAction(self.a_quit)
        m = mb.addMenu(tr("&Modifica"))
        for a in (self.a_cut, self.a_copyclip, self.a_paste):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_selall)
        m.addSeparator()
        for a in (self.a_rename1, self.a_rename, self.a_convert, self.a_copy, self.a_move,
                  self.a_delete):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_copypath)
        m.addAction(self.a_wall)
        m = mb.addMenu(tr("&Visualizza"))
        m.addAction(self.a_view)
        m.addAction(self.a_show)
        m.addAction(self.a_dual)
        m.addSeparator()
        m.addAction(self.a_info)
        m.addSeparator()
        m.addAction(self.a_refresh)
        m = mb.addMenu(tr("&Strumenti"))
        m.addAction(self.a_options)
        m.addAction(self.a_shell)
        m.aboutToShow.connect(lambda: self.a_shell.setChecked(shell.is_installed()))
        lm = m.addMenu("Lingua / Language")
        cur = self.settings.value("app/language", "auto")
        choices = [("auto", tr("Automatica (come Windows)"))] + [(k, v[0]) for k, v in LANGUAGES.items()]
        for code, name in choices:
            a = lm.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == cur)
            a.triggered.connect(lambda _=False, c=code: self.set_language(c))
        tm = m.addMenu(tr("Tema"))
        cur = self.settings.value("app/theme", "auto")
        self._theme_actions = {}
        for code, name in (("auto", tr("Automatico (come Windows)")),
                           ("light", tr("Chiaro")), ("dark", tr("Scuro"))):
            a = tm.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == cur)
            a.triggered.connect(lambda _=False, c=code: self.set_theme(c))
            self._theme_actions[code] = a
        m = mb.addMenu(tr("&Aiuto"))
        m.addAction(self.a_help)
        m.addSeparator()
        m.addAction(self.a_about)

    def _add(self, menu, action, enabled=True):
        """Aggiunge un'azione al menu abilitandola solo se ha senso qui; dopo la chiusura
        del menu torna abilitata, così le scorciatoie da tastiera continuano a funzionare."""
        if not enabled:
            action.setEnabled(False)
            self._touched.append(action)
        menu.addAction(action)

    def _exec_menu(self, m, pos):
        try:
            m.exec(self.view.viewport().mapToGlobal(pos))
        finally:
            for a in self._touched:
                a.setEnabled(True)
            self._touched = []

    def _context_menu(self, pos):
        on_item = self.view.indexAt(pos).isValid()
        if not on_item:
            self.view.clearSelection()
        inside = bool(self.folder and is_archive(self.folder))   # dentro un CBZ/ZIP
        rows = self.selected_rows()
        files = self.selected_paths()
        dirs = self.selected_folders()
        can_paste = not inside and bool(self.folder) and not unc_server(self.folder) \
            and fileops.clipboard_has_files()
        m = QMenu(self)
        self._touched = []

        if not rows:
            # clic sullo spazio vuoto: comandi sulla cartella corrente
            self._add(m, self.a_paste, can_paste)
            self._add(m, self.a_newdir, not inside and bool(self.folder))
            m.addSeparator()
            m.addAction(self.a_show)
            m.addAction(self.a_selall)
            sm = m.addMenu(tr("Ordina per"))
            for i, name in enumerate(sort_names()):
                a = sm.addAction(name)
                a.setCheckable(True)
                a.setChecked(self.cb_sort.currentIndex() == i)
                a.triggered.connect(lambda _=False, i=i: self.cb_sort.setCurrentIndex(i))
            sm.addSeparator()
            a = sm.addAction(tr("Decrescente"))
            a.setCheckable(True)
            a.setChecked(self.ck_rev.isChecked())
            a.toggled.connect(self.ck_rev.setChecked)
            m.addAction(self.a_refresh)
            m.addSeparator()
            m.addAction(self.a_explorer)
            self._add(m, self.a_props, bool(self.folder) and not inside)
            self._exec_menu(m, pos)
            return

        one = len(rows) == 1
        m.addAction(self.a_view)
        m.addAction(self.a_show)
        if len(dirs) == 2 and len(rows) == 2:
            m.addAction(self.a_dual)
        m.addSeparator()

        om = m.addMenu(tr("Apri con"))
        om.setEnabled(bool(files) and not inside)
        om.addAction(self.a_open_def)
        om.addAction(self.a_open_with)
        om.addAction(self.a_paint)
        bm = m.addMenu(tr("Elaborazione in blocco"))
        self._add(bm, self.a_rename, not inside and bool(files or self._renamable_archives()))
        self._add(bm, self.a_convert, not inside and bool(files))
        self._add(m, self.a_wall, one and bool(files))
        m.addSeparator()

        self._add(m, self.a_cut, not inside)
        self._add(m, self.a_copyclip, not inside)
        if one and dirs and not inside and not is_archive(dirs[0]):
            self.a_paste.setText(tr("Incolla nella cartella"))
        else:
            self.a_paste.setText(tr("Incolla"))
        self._add(m, self.a_paste, can_paste)
        self._add(m, self.a_delete, not inside)
        self._add(m, self.a_rename1, not inside)
        m.addSeparator()
        self._add(m, self.a_copy, not inside)
        self._add(m, self.a_move, not inside)
        m.addSeparator()
        self._add(m, self.a_print, bool(files))
        m.addSeparator()
        m.addAction(self.a_explorer)
        m.addAction(self.a_copypath)
        m.addSeparator()
        if one and files:
            m.addAction(self.a_info)        # immagine: EXIF e informazioni al posto delle proprietà
        else:
            self._add(m, self.a_props, one)
        self._exec_menu(m, pos)
        self.a_paste.setText(tr("Incolla"))

    def _renamable_archives(self):
        return [p for p in self.selected_folders() if is_archive(p) and os.path.isfile(p)]

    def _thumb_size(self, v):
        self.view.setIconSize(QSize(v, v))
        self.settings.setValue("browser/thumb_size", v)

    def _sort_key(self):
        return SORT_KEYS[self.cb_sort.currentIndex()], self.ck_rev.isChecked()

    def _sort_changed(self, *_):
        k, r = self._sort_key()
        self.settings.setValue("browser/sort", k)
        self.settings.setValue("browser/sort_reverse", r)
        self.reload()

    # ------------------------------------------------------------ cartelle
    def _tree_changed(self, cur, _prev):
        if cur.isValid():
            path = self.fs.filePath(cur)
            if path and not samepath(path, self.folder):
                self.set_folder(path, sync_tree=False)

    def set_folder(self, path, sync_tree=True, select=None, add_history=True):
        path = (path or "").strip().strip('"')
        host = unc_server(path)
        if host:
            # Server di rete senza condivisione (\\host): mostra le cartelle condivise.
            path = "\\\\" + host
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                list_unc_shares(host)
            except OSError as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(
                    self, APP_NAME,
                    tr("Impossibile elencare le cartelle condivise di {path}: {err}.\n\n"
                       "Se il computer chiede nome utente e password, apri prima {path} in "
                       "Esplora risorse e accedi; oppure scrivi direttamente il percorso completo, "
                       "per esempio {path}\\Foto.", path=path, err=e))
                return
            QApplication.restoreOverrideCursor()
        elif is_archive(path) and os.path.isfile(path):
            path = os.path.normpath(path)
        elif not path or not os.path.isdir(path):
            QMessageBox.warning(self, APP_NAME, tr("Cartella non trovata o non accessibile:\n{path}", path=path))
            return
        else:
            path = os.path.normpath(path)
        if add_history and self.folder and not samepath(self.folder, path):
            self.history.append(self.folder)
            self.history = self.history[-50:]
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.folder = path
        if not host:
            self.watcher.addPath(path)
        self.settings.setValue("browser/last_folder", path)
        self.path_edit.setText(path)
        self.setWindowTitle(f"{os.path.basename(path) or path} - {APP_NAME}")
        self._load(select=[select] if select else None, scroll_top=True)
        if sync_tree:
            idx = self.fs.index(path)
            if idx.isValid():
                self.tree.blockSignals(True)
                self.tree.selectionModel().blockSignals(True)
                self.tree.setCurrentIndex(idx)
                self.tree.selectionModel().blockSignals(False)
                self.tree.blockSignals(False)
                self.tree.expand(idx)
                QTimer.singleShot(150, lambda: self.tree.scrollTo(self.fs.index(path)))

    def _load(self, select=None, scroll_top=False):
        k, r = self._sort_key()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            items = list_folder_items(self.folder, k, r)
        except OSError:
            items = []
        finally:
            QApplication.restoreOverrideCursor()
        self.model.set_items(items)
        if select:
            self.select_paths(select)
        elif scroll_top:
            self.view.scrollToTop()
            if items:
                self.view.selectionModel().setCurrentIndex(
                    self.model.index(0), QItemSelectionModel.SelectionFlag.NoUpdate)
        self._update_status()

    def reload(self):
        if not self.folder:
            return
        if not unc_server(self.folder) and not os.path.isdir(self.folder) \
                and not (is_archive(self.folder) and os.path.isfile(self.folder)):
            parent = os.path.dirname(self.folder)
            self.folder = None
            self.set_folder(parent, add_history=False)
            return
        sel = self.selected_all()
        cur = self.view.currentIndex()
        cur_path = self.model.path(cur.row()) if cur.isValid() else None
        bar = self.view.verticalScrollBar().value()
        self._load(select=sel or ([cur_path] if cur_path else None))
        QTimer.singleShot(0, lambda: self.view.verticalScrollBar().setValue(bar))

    def select_paths(self, paths):
        sm = self.view.selectionModel()
        rows = {os.path.normcase(it.path): i for i, it in enumerate(self.model.items)}
        sel = QItemSelection()
        first = None
        for p in paths:
            row = rows.get(os.path.normcase(p))
            if row is None:
                continue
            idx = self.model.index(row)
            sel.select(idx, idx)
            if first is None:
                first = idx
        sm.select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if first is not None:
            sm.setCurrentIndex(first, QItemSelectionModel.SelectionFlag.NoUpdate)
            self.view.scrollTo(first, QAbstractItemView.ScrollHint.PositionAtCenter)

    def reveal(self, path):
        """Mostra il browser posizionato su path (file o cartella)."""
        if not path:
            return
        if os.path.isdir(path):
            if not samepath(path, self.folder):
                self.set_folder(path)
            return
        d = parent_of(path)
        if not samepath(d, self.folder):
            self.set_folder(d, select=path)
        else:
            self.reload()
            self.select_paths([path])

    def go_back(self):
        while self.history:
            p = self.history.pop()
            if os.path.isdir(p):
                self.set_folder(p, add_history=False)
                return

    def go_up(self):
        if self.folder:
            if unc_server(self.folder):
                return
            parent = unc_parent(self.folder) or os.path.dirname(self.folder)
            if parent and not samepath(parent, self.folder):
                came_from = self.folder
                self.set_folder(parent, select=came_from)

    def go_pictures(self):
        p = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)
        self.set_folder(p if p and os.path.isdir(p) else os.path.expanduser("~"))

    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Apri cartella"), self.folder or "")
        if d:
            self.set_folder(d)

    # ------------------------------------------------------------ selezione
    def selected_rows(self):
        return sorted(i.row() for i in self.view.selectionModel().selectedIndexes())

    def selected_all(self):
        return [self.model.path(r) for r in self.selected_rows()]

    def selected_paths(self):
        """Solo le immagini selezionate."""
        return [self.model.path(r) for r in self.selected_rows() if not self.model.is_dir(r)]

    def selected_folders(self):
        return [self.model.path(r) for r in self.selected_rows() if self.model.is_dir(r)]

    def _update_status(self, *_):
        nd, ni = self.model.counts()
        na = sum(1 for it in self.model.items if it.is_dir and is_archive(it.name))
        parts = []
        if nd - na:
            parts.append(tr("{n} cartelle", n=nd - na))
        if na:
            parts.append(tr("{n} archivi", n=na))
        parts.append(tr("{n} immagini", n=ni) + f"  ·  {human_size(self.model.total_size())}")
        txt = "   ·   ".join(parts)
        sd, si = len(self.selected_folders()), self.selected_paths()
        if sd or si:
            sel = []
            if sd:
                sel.append(tr("{n} cartelle", n=sd))
            if si:
                size = human_size(sum(os.path.getsize(p) for p in si if os.path.exists(p)))
                sel.append(tr("{n} immagini", n=len(si)) + f" ({size})")
            txt += "   |   " + tr("Selezionate:") + " " + ", ".join(sel)
        self.status.setText(txt)

    def _targets(self, folders_ok=False):
        if self.folder and is_archive(self.folder):
            QMessageBox.information(self, APP_NAME,
                                    tr("Le operazioni in blocco non sono disponibili dentro un archivio "
                                       "ZIP/CBZ.\nTorna alla cartella che lo contiene (Backspace) per "
                                       "copiare, spostare o eliminare l'archivio intero."))
            return []
        if folders_ok == "archives":
            paths = self.selected_paths() + self._renamable_archives()
        else:
            paths = self.selected_all() if folders_ok else self.selected_paths()
        if not paths:
            QMessageBox.information(self, APP_NAME,
                                    tr("Seleziona prima una o più immagini o cartelle.") if folders_ok is True
                                    else tr("Seleziona prima una o più immagini."))
        return paths

    # ------------------------------------------------- visualizza / slideshow
    def activate(self, row=None):
        """Invio / doppio clic: entra nella cartella oppure apre l'immagine."""
        if row is None:
            cur = self.view.currentIndex()
            row = cur.row() if cur.isValid() else (self.selected_rows() or [None])[0]
        if row is None or row >= len(self.model.items):
            return
        if self.model.is_dir(row):
            self.set_folder(self.model.path(row))
        else:
            self.open_viewer(row)

    def open_viewer(self, row=None):
        if row is None:
            cur = self.view.currentIndex()
            row = cur.row() if cur.isValid() else (self.selected_rows() or [None])[0]
        if row is None or row >= len(self.model.items):
            return
        if self.model.is_dir(row):
            self.set_folder(self.model.path(row))
            return
        k, r = self._sort_key()
        nav = Navigator(self.folder, start=self.model.path(row), sort=k, reverse=r,
                        loop=False)
        self.app.open_viewer(nav, slideshow=False)

    def start_slideshow(self):
        if not self.folder:
            return
        k, r = self._sort_key()
        sel = self.selected_paths()
        sel_dirs = self.selected_folders()
        sub = self.ck_sub.isChecked()
        opts = dict(shuffle=self.ck_random.isChecked(), loop=self.ck_loop.isChecked(),
                    sort=k, reverse=r)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if len(sel_dirs) == 1:
                # Una cartella selezionata = punto di partenza: si percorrono tutte le
                # cartelle della vista, iniziando da quella.
                all_dirs = [it.path for it in self.model.items if it.is_dir]
                nav = Navigator(self.folder, folders=self._expand(all_dirs, sub),
                                start_folder=sel_dirs[0], **opts)
            elif sel_dirs:
                # Più cartelle selezionate: solo quelle, una dopo l'altra.
                nav = Navigator(self.folder, folders=self._expand(sel_dirs, sub), **opts)
            elif len(sel) >= 2:
                nav = Navigator(self.folder, images=sel, **opts)
            elif unc_server(self.folder) or (not sub and not has_images(self.folder)):
                # Cartella che contiene solo sottocartelle (o elenco condivisioni di rete):
                # si percorrono tutte le cartelle della vista.
                all_dirs = [it.path for it in self.model.items if it.is_dir]
                nav = Navigator(self.folder, folders=self._expand(all_dirs, sub), **opts)
            else:
                nav = Navigator(self.folder, start=sel[0] if sel else None,
                                include_sub=sub, **opts)
        finally:
            QApplication.restoreOverrideCursor()
        if nav.current() is None:
            QMessageBox.information(self, tr("Slideshow"), tr("Nessuna immagine trovata."))
            return
        self.app.open_viewer(nav, slideshow=True)

    def dual_slideshow(self):
        """Due cartelle (o archivi) affiancate: preselezionate se ne hai scelte due."""
        dirs = self.selected_folders()
        left = dirs[0] if dirs else (self.folder if self.folder and has_images(self.folder) else "")
        right = dirs[1] if len(dirs) > 1 else ""
        self.app.open_dual(left, right, self)

    _expand = staticmethod(expand_folders)

    # ------------------------------------------------------------ in blocco
    def batch_rename(self):
        paths = self._targets(folders_ok="archives")
        if paths and batch.RenameDialog(paths, self.settings, self).run():
            self.reload()

    def batch_convert(self):
        paths = self._targets()
        if paths and batch.ConvertDialog(paths, self.settings, self).run():
            self.reload()

    def batch_copy(self, move):
        paths = self._targets(folders_ok=True)
        if paths and batch.copy_move_dialog(self, paths, self.settings, move):
            self.reload()

    def batch_delete(self):
        paths = self._targets(folders_ok=True)
        if paths and batch.delete_dialog(self, paths):
            self.reload()

    # ------------------------------------------------- comandi del menu contestuale
    def _real_selection(self):
        """Elementi selezionati utilizzabili per operazioni sui file (non dentro un archivio)."""
        if self.folder and is_archive(self.folder):
            return []
        return self.selected_all()

    def rename_item(self):
        sel = self._real_selection()
        if len(sel) > 1:
            self.batch_rename()
            return
        if not sel:
            return
        new = fileops.rename_single(self, sel[0])
        if new:
            self.reload()
            self.select_paths([new])

    def to_clipboard(self, cut):
        sel = self._real_selection()
        if sel:
            fileops.clipboard_set(sel, cut)
            self.statusBar().showMessage(
                (tr("Tagliati: {n}", n=len(sel)) if cut else tr("Copiati negli appunti: {n}", n=len(sel))), 3000)

    def paste(self):
        if not self.folder or is_archive(self.folder) or unc_server(self.folder):
            return
        paths, cut = fileops.clipboard_get()
        if not paths:
            return
        dest = self.folder
        dirs = self.selected_folders()
        if self.a_paste.text() == tr("Incolla nella cartella") and len(dirs) == 1:
            dest = dirs[0]
        if batch.transfer(self, paths, dest, move=cut):
            if cut:
                QApplication.clipboard().clear()
            self.reload()
            if samepath(dest, self.folder):
                self.select_paths([os.path.join(dest, os.path.basename(p)) for p in paths])

    def make_folder(self):
        if not self.folder or is_archive(self.folder) or unc_server(self.folder):
            return
        new = fileops.new_folder(self, self.folder)
        if new:
            self.reload()
            self.select_paths([new])

    def _each_file(self, fn, limit=20):
        files = [p for p in self.selected_paths() if not is_archive(self.folder or "")]
        for p in files[:limit]:
            fn(p)

    def set_wallpaper(self):
        files = self.selected_paths()
        if files:
            fileops.set_wallpaper(self, files[0])

    def print_selected(self):
        files = self.selected_paths()
        if files:
            fileops.print_images(self, files)

    def copy_paths(self):
        sel = self.selected_all() or ([self.folder] if self.folder else [])
        if sel:
            fileops.copy_as_path([p.replace("|", os.sep) for p in sel])

    def properties(self):
        sel = self.selected_all()
        target = sel[0] if len(sel) == 1 else (self.folder if not sel else None)
        if target:
            fileops.show_properties(self, target)

    def image_info(self):
        """Informazioni ed EXIF dell'immagine selezionata; su una cartella, le proprietà."""
        files = self.selected_paths()
        if len(files) == 1 and len(self.selected_all()) == 1:
            from .imageinfo import show_image_info
            show_image_info(self, files[0])
        else:
            self.properties()

    def reveal_in_explorer(self):
        sel = self.selected_all()
        if sel:
            show_in_explorer(sel[0].split("|", 1)[0])
        elif self.folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.folder))

    def show_options(self):
        from .options import OptionsDialog
        if OptionsDialog(self.settings, self).run():
            for v in self.app.viewers:
                v.apply_options()

    def show_help(self):
        QMessageBox.information(self, tr("Scorciatoie da tastiera"), help_html())

    def show_about(self):
        from .about import AboutDialog
        AboutDialog(self).exec()

    def toggle_shell_menu(self, on):
        try:
            if on:
                shell.install()
                QMessageBox.information(
                    self, APP_NAME,
                    tr("Fatto. Facendo clic destro su una cartella, un archivio CBZ/ZIP o "
                       "un'immagine in Esplora risorse trovi il sottomenu «{app}» con "
                       "slideshow, rinomina e conversione.\n\nSu Windows 11 è sotto "
                       "«Mostra altre opzioni» (oppure Maiusc+F10).", app=APP_NAME))
            else:
                shell.uninstall()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, tr("Operazione non riuscita: {err}", err=e))
        self.a_shell.setChecked(shell.is_installed())

    def set_theme(self, code):
        """Cambia tema subito, senza riavviare."""
        from PySide6.QtWidgets import QApplication
        from . import theme
        self.settings.setValue("app/theme", code)
        theme.apply(QApplication.instance(), code)
        for c, a in self._theme_actions.items():
            a.setChecked(c == code)

    def set_language(self, code):
        if code == self.settings.value("app/language", "auto"):
            return
        self.settings.setValue("app/language", code)
        from . import i18n
        i18n.init(self.settings)
        if shell.is_installed():
            try:
                shell.install()   # voci del menu di Esplora risorse nella nuova lingua
            except OSError:
                pass
        r = QMessageBox.question(self, APP_NAME, tr("La nuova lingua verrà usata al prossimo avvio.\n\nRiavviare adesso?"))
        if r == QMessageBox.StandardButton.Yes:
            self.restart()

    def restart(self):
        import sys
        from PySide6.QtCore import QProcess
        args = [] if getattr(sys, "frozen", False) else [os.path.abspath(sys.argv[0])]
        if self.folder:
            args.append(self.folder)
        r = QProcess.startDetached(sys.executable, args)
        if (r[0] if isinstance(r, tuple) else r):
            for v in list(self.app.viewers):
                v.close()
            self.close()
            QApplication.quit()

    def closeEvent(self, e):
        self.settings.setValue("browser/geometry", self.saveGeometry())
        self.settings.setValue("browser/splitter", self.split.saveState())
        super().closeEvent(e)
