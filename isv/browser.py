"""Finestra principale: albero cartelle + griglia miniature (come la modalità Gestione di ACDSee).

Tutti i comandi sono QAction costruite dall'elenco di shortcuts.BROWSER: gli stessi
oggetti compaiono nel menu in alto, nei pulsanti e nel menu del tasto destro, quindi
testi, tasti e abilitazione sono sempre coerenti (_update_actions).
"""
import os

from PySide6.QtCore import (QDir, QEvent, QFileSystemWatcher, QItemSelection, QItemSelectionModel, QSize,
                            QStandardPaths, Qt, QTimer, QUrl)
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFileSystemModel, QInputDialog, QLabel, QLineEdit,
                               QListView, QMainWindow, QMenu, QMessageBox, QSlider, QSplitter, QStyle,
                               QToolBar, QToolButton, QTreeView)

from . import APP_NAME, batch, fileops, library, shell, shortcuts
from .app import expand_folders
from .archive import is_archive, is_virtual, parent_of, stat_any
from .i18n import LANGUAGES, tr
from .navigator import Navigator
from .thumbs import ThumbAnimator, ThumbDelegate, ThumbModel
from .undo import flush_leftovers, manager as undo_manager
from .utils import (FileItem, has_images, human_size, is_image, is_video, list_folder_items,
                    list_unc_shares, samepath, show_in_explorer, unc_parent, unc_server)

SORT_KEYS = ["name", "date", "size"]
# comandi attivi solo quando la griglia ha il fuoco (così Ctrl+C, Canc… funzionano
# normalmente nella casella del percorso)
VIEW_ONLY = {"delete", "select_all", "cut", "copy", "paste", "rename", "info", "undo",
             *[f"rating_{i}" for i in range(6)], *[f"label_{i}" for i in range(6)]}
ICONS = {"back": "SP_ArrowBack", "up": "SP_ArrowUp", "pictures": "SP_DirHomeIcon",
         "refresh": "SP_BrowserReload", "open_dir": "SP_DirOpenIcon", "delete": "SP_TrashIcon",
         "new_folder": "SP_FileDialogNewFolder", "help": "SP_DialogHelpButton",
         "properties": "SP_FileDialogInfoView", "info": "SP_MessageBoxInformation"}
# pulsanti della barra: simbolo (disegnato come icona nel colore del tema) e testo breve;
# il testo completo resta nel menu e nel suggerimento
TOOL_GLYPH = {"view": "🖼", "slideshow": "▶", "compare": "⧉", "webtoon": "⇩", "edit": "✎",
              "rotate_left": "⟲", "rotate_right": "⟳", "favorite": "♥", "undo": "↶", "search": "🔍",
              "preview": "▣"}
TOOL_LABEL = {"view": "Visualizza", "slideshow": "Slideshow", "compare": "Confronta", "webtoon": "Verticale",
              "edit": "Modifica", "rotate_left": "Sinistra", "rotate_right": "Destra", "favorite": "Preferiti",
              "delete": "Elimina", "undo": "Annulla operazione", "search": "Cerca", "preview": "Anteprima"}
# dimensioni della barra dei pulsanti: (icona px, testo sotto l'icona, punti in più per il testo)
TOOLBAR_SIZES = {"small": (16, False, 0), "medium": (24, False, 1), "large": (36, True, 1)}


def glyph_icon(ch, color, size=64):
    """Icona disegnata da un simbolo di testo (nitida a ogni dimensione, nel colore del tema)."""
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    f = QFont()
    f.setPixelSize(int(size * 0.82))
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, ch)
    p.end()
    return QIcon(pm)

FILTERS = [("all", "Tutte"), ("r1", "★ 1 o più"), ("r2", "★ 2 o più"), ("r3", "★ 3 o più"),
           ("r4", "★ 4 o più"), ("r5", "★ 5"), ("r0", "Senza valutazione"),
           ("l1", "Etichetta rossa"), ("l2", "Etichetta gialla"), ("l3", "Etichetta verde"),
           ("l4", "Etichetta blu"), ("l5", "Etichetta viola"), ("lx", "Con etichetta"),
           ("fav", "Preferiti"), ("img", "Solo immagini"), ("vid", "Solo video")]


def sort_names():
    return [tr("Nome"), tr("Data"), tr("Dimensione")]


class BrowserWindow(QMainWindow):
    def __init__(self, app, settings):
        super().__init__()
        self.app, self.settings = app, settings
        self.setWindowTitle(APP_NAME)
        self.resize(1360, 840)
        self.folder = None
        self.virtual = None         # elenco "virtuale": raccolta, ricerca, calendario, duplicati
        self.history = []
        self.filter = settings.value("browser/filter", "all")

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
        self.view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.animator = ThumbAnimator(self.model, self)
        self._sel_timer = QTimer(self, singleShot=True, interval=150)
        self._sel_timer.timeout.connect(self._after_selection)
        self.view.selectionModel().currentChanged.connect(lambda *_: self._sel_timer.start())

        # --- anteprima
        from .preview import PreviewPanel
        self.preview = PreviewPanel(settings)
        self.inner = QSplitter()
        self.inner.addWidget(self.view)
        self.inner.addWidget(self.preview)
        self.inner.setStretchFactor(0, 1)
        self.inner.setOrientation(Qt.Orientation.Vertical if settings.value("browser/preview_pos", "right") == "bottom"
                                  else Qt.Orientation.Horizontal)
        split = QSplitter()
        split.addWidget(self.tree)
        split.addWidget(self.inner)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 1080])
        self.split = split
        self.setCentralWidget(split)

        self._build_actions()
        self._build_toolbars()
        self._build_menus()
        self.status = QLabel()
        self.statusBar().addWidget(self.status, 1)
        self.preview.setVisible(settings.value("browser/preview", False, type=bool))
        self.A["preview"].setChecked(self.preview.isVisible())

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self._reload_timer.start())
        self._reload_timer = QTimer(self, singleShot=True, interval=600)
        self._reload_timer.timeout.connect(self.reload)
        QApplication.clipboard().dataChanged.connect(self._update_actions)

        g = settings.value("browser/geometry")
        if g is not None:
            self.restoreGeometry(g)
        s = settings.value("browser/splitter")
        if s is not None:
            self.split.restoreState(s)
        s = settings.value("browser/inner_splitter")
        if s is not None:
            self.inner.restoreState(s)
        else:
            self.inner.setSizes([760, 380])
        QTimer.singleShot(1500, shell.refresh_if_moved)
        self._update_actions()

    # ============================================================ comandi
    def _build_actions(self):
        slots = {
            "back": self.go_back, "up": self.go_up, "pictures": self.go_pictures, "refresh": self.reload,
            "open_dir": self.choose_folder, "new_folder": self.make_folder, "view": lambda: self.open_viewer(),
            "slideshow": self.start_slideshow, "dual": self.dual_slideshow, "webtoon": self.open_webtoon,
            "compare": self.compare, "preview": self.toggle_preview, "info": self.image_info,
            "undo": self.undo, "cut": lambda: self.to_clipboard(True), "copy": lambda: self.to_clipboard(False),
            "paste": self.paste, "select_all": lambda: self.view.selectAll(), "rename": self.rename_item,
            "batch_rename": self.batch_rename, "convert": self.batch_convert, "to_cbz": self.to_cbz,
            "edit": self.edit_image, "rotate_right": lambda: self.rotate_files("right"),
            "rotate_left": lambda: self.rotate_files("left"), "rotate_180": lambda: self.rotate_files("180"),
            "flip_h": lambda: self.rotate_files("flip_h"), "flip_v": lambda: self.rotate_files("flip_v"),
            "copy_to": lambda: self.batch_copy(False), "move_to": lambda: self.batch_copy(True),
            "delete": self.batch_delete, "favorite": self.toggle_favorite, "copy_path": self.copy_paths,
            "wallpaper": self.set_wallpaper, "print": self.print_selected, "properties": self.properties,
            "explorer": self.reveal_in_explorer, "search": self.search, "duplicates": self.find_duplicates,
            "calendar": self.calendar, "map": self.photo_map, "options": self.show_options,
            "shortcuts": self.show_shortcuts, "help": self.show_help, "quit": self.close,
        }
        for i in range(6):
            slots[f"rating_{i}"] = lambda _=False, i=i: self.set_rating(i)
            slots[f"label_{i}"] = lambda _=False, i=i: self.set_label(i)
        SP = QStyle.StandardPixmap
        self.A = {}
        self._proxies = {}
        for aid, _text, _d in shortcuts.BROWSER:
            a = QAction(shortcuts.label("browser", aid), self)
            if aid in ICONS:
                a.setIcon(self.style().standardIcon(getattr(SP, ICONS[aid])))
            if aid in TOOL_LABEL:
                a.setIconText(tr(TOOL_LABEL[aid]))
                a.setToolTip(a.text())
            a.triggered.connect(lambda _=False, f=slots[aid]: f())
            if aid in VIEW_ONLY:
                a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
                self.view.addAction(a)
            else:
                a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
                self.addAction(a)
            self.A[aid] = a
        for k in ("preview",):
            self.A[k].setCheckable(True)
        self.a_about = QAction(tr("Informazioni su {app}…", app=APP_NAME), self)
        self.a_about.triggered.connect(self.show_about)
        self.a_shell = QAction(tr("Menu contestuale di Esplora risorse"), self)
        self.a_shell.setCheckable(True)
        self.a_shell.setEnabled(shell.supported())
        self.a_shell.triggered.connect(self.toggle_shell_menu)
        ent = QAction(self.view)
        ent.setShortcuts([QKeySequence("Return"), QKeySequence("Enter")])
        ent.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        ent.triggered.connect(lambda: self.activate())
        self.view.addAction(ent)
        self._apply_shortcuts()

    def _apply_shortcuts(self):
        """Tasti dalle impostazioni. I tasti "semplici" (Backspace, lettere…) dei comandi
        globali valgono solo nella griglia, per non disturbare la casella del percorso."""
        for aid, a in self.A.items():
            seqs = shortcuts.sequences(self.settings, "browser", aid)
            if aid in VIEW_ONLY:
                a.setShortcuts(seqs)
                continue
            glob, local = [], []
            for s in seqs:
                k = s[0] if s.count() else None
                plain = k is not None and k.keyboardModifiers() == Qt.KeyboardModifier.NoModifier \
                    and not (Qt.Key.Key_F1 <= k.key() <= Qt.Key.Key_F35)
                (local if plain else glob).append(s)
            a.setShortcuts(glob)
            px = self._proxies.get(aid)
            if local:
                if px is None:
                    px = QAction(self.view)
                    px.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
                    px.triggered.connect(a.trigger)
                    self.view.addAction(px)
                    self._proxies[aid] = px
                px.setShortcuts(local)
            elif px is not None:
                px.setShortcuts([])

    def _update_actions(self, *_):
        """Abilita ogni comando solo se ha senso con la selezione e la cartella attuali."""
        if not hasattr(self, "A"):
            return
        A = self.A
        inside = bool(self.folder and is_archive(self.folder))
        virtual = self.virtual is not None
        files = self.selected_paths()
        dirs = self.selected_folders()
        rows = self.selected_rows()
        real_files = [p for p in files if not is_virtual(p)]
        images = [p for p in files if is_image(p)]
        real_images = [p for p in real_images_of(files)]
        folder_ok = bool(self.folder) and not inside and not unc_server(self.folder or "") and not virtual
        has_items = bool(self.model.items)
        en = {
            "back": bool(self.history) or virtual, "up": bool(self.folder) or virtual,
            "view": bool(rows), "slideshow": has_items or bool(rows),
            "dual": True,   # la finestra permette di scegliere le due cartelle
            "webtoon": bool(rows) or has_items, "compare": len(images) == 2 and len(rows) == 2,
            "info": len(rows) == 1, "undo": undo_manager.can_undo(),
            "cut": bool(rows) and not inside, "copy": bool(rows) and not inside,
            "paste": folder_ok and fileops.clipboard_has_files(),
            "select_all": has_items, "rename": bool(rows) and not inside,
            "batch_rename": not inside and bool(real_files or self._renamable_archives()),
            "convert": not inside and bool(real_images), "to_cbz": bool(self._convertible_archives()),
            "edit": len(real_images) == 1 and len(rows) == 1,
            "copy_to": bool(rows) and not inside, "move_to": bool(rows) and not inside,
            "delete": bool(rows) and not inside, "favorite": bool(files),
            "copy_path": bool(rows) or bool(self.folder), "wallpaper": len(images) == 1,
            "print": bool(images), "properties": len(rows) <= 1 and (bool(rows) or folder_ok),
            "explorer": bool(rows) or bool(self.folder), "new_folder": folder_ok,
            "map": has_items, "calendar": bool(self.folder) and not virtual and not inside,
        }
        for k in ("rotate_right", "rotate_left", "rotate_180", "flip_h", "flip_v"):
            en[k] = bool(real_images)
        for i in range(6):
            en[f"rating_{i}"] = bool(files)
            en[f"label_{i}"] = bool(files)
        for k, v in en.items():
            A[k].setEnabled(bool(v))
        if hasattr(self, "_raccolte_menu"):
            self._raccolte_add.setEnabled(bool(files))

    # ============================================================ interfaccia
    def _build_toolbars(self):
        A = self.A
        tb = QToolBar(tr("Navigazione"))
        tb.setObjectName("nav")
        tb.setMovable(False)
        for k in ("back", "up", "pictures", "refresh"):
            tb.addAction(A[k])
        self.path_edit = QLineEdit()
        self.path_edit.returnPressed.connect(lambda: self.set_folder(self.path_edit.text().strip()))
        tb.addWidget(self.path_edit)
        self.addToolBar(tb)
        self.addToolBarBreak()

        ct = QToolBar(tr("Comandi"))
        ct.setObjectName("commands")
        ct.setMovable(False)
        for k in ("view", "slideshow", "compare", "webtoon", None, "edit", "rotate_left", "rotate_right",
                  None, "favorite", "delete", "undo", None, "search", "preview"):
            if k is None:
                ct.addSeparator()
            else:
                ct.addAction(A[k])
        ct.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        ct.customContextMenuRequested.connect(
            lambda pos: self._toolbar_menu(QMenu(self)).exec(ct.mapToGlobal(pos)))
        self.tools = ct
        self._base_font = QApplication.font()
        self.addToolBar(ct)
        self.set_toolbar_size(self.settings.value("browser/toolbar_size", "small"), save=False)
        ct.setVisible(self.settings.value("browser/toolbar_visible", True, type=bool))
        self.addToolBarBreak()

        st = QToolBar("Slideshow")
        st.setObjectName("slideshow")
        st.setMovable(False)
        s = self.settings
        st.addWidget(QLabel(" " + tr("Intervallo") + " "))
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
                                   "1-2, poi 3-4, 5-6… (nello slideshow anche con il tasto D). "
                                   "Le pagine doppie si mostrano da sole."))
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
        cur = s.value("browser/sort", "name")
        self.cb_sort.setCurrentIndex(SORT_KEYS.index(cur) if cur in SORT_KEYS else 0)
        self.cb_sort.currentIndexChanged.connect(self._sort_changed)
        st.addWidget(self.cb_sort)
        self.ck_rev = QCheckBox(tr("Decrescente"))
        self.ck_rev.setChecked(s.value("browser/sort_reverse", False, type=bool))
        self.ck_rev.toggled.connect(self._sort_changed)
        st.addWidget(QLabel(" "))
        st.addWidget(self.ck_rev)
        st.addSeparator()
        st.addWidget(QLabel(" " + tr("Filtro") + " "))
        self.cb_filter = QComboBox()
        self.cb_filter.addItems([tr(n) for _k, n in FILTERS])
        keys = [k for k, _n in FILTERS]
        self.cb_filter.setCurrentIndex(keys.index(self.filter) if self.filter in keys else 0)
        self.cb_filter.currentIndexChanged.connect(lambda i: self.set_filter(FILTERS[i][0]))
        st.addWidget(self.cb_filter)
        st.addSeparator()
        st.addWidget(QLabel(" " + tr("Miniature") + " "))
        self.sl_size = QSlider(Qt.Orientation.Horizontal)
        self.sl_size.setRange(64, 240)
        self.sl_size.setFixedWidth(130)
        self.sl_size.setValue(s.value("browser/thumb_size", 150, type=int))
        self.sl_size.valueChanged.connect(self._thumb_size)
        st.addWidget(self.sl_size)
        self.addToolBar(st)
        self._thumb_size(self.sl_size.value())

    def _rating_menu(self, parent):
        m = parent.addMenu(tr("Valutazione"))
        for i in range(6):
            m.addAction(self.A[f"rating_{i}"])
        return m

    def _label_menu(self, parent):
        from .viewer import color_icon
        m = parent.addMenu(tr("Etichetta"))
        for i, _n, color in library.LABELS:
            a = self.A[f"label_{i}"]
            a.setIcon(color_icon(color))
            m.addAction(a)
        return m

    def _rotate_menu(self, parent):
        m = parent.addMenu(tr("Ruota e specchia (nel file)"))
        for k in ("rotate_right", "rotate_left", "rotate_180", "flip_h", "flip_v"):
            m.addAction(self.A[k])
        return m

    def _build_menus(self):
        A = self.A
        mb = self.menuBar()
        m = mb.addMenu(tr("&File"))
        for k in ("open_dir", "new_folder", "explorer", None, "print", "properties", None, "quit"):
            m.addSeparator() if k is None else m.addAction(A[k])

        m = mb.addMenu(tr("&Modifica"))
        for k in ("undo", None, "cut", "copy", "paste", "select_all", None, "rename", "edit"):
            m.addSeparator() if k is None else m.addAction(A[k])
        self._rotate_menu(m)
        m.addSeparator()
        self._rating_menu(m)
        self._label_menu(m)
        m.addAction(A["favorite"])
        m.addSeparator()
        for k in ("copy_to", "move_to", "delete", None, "copy_path", "wallpaper"):
            m.addSeparator() if k is None else m.addAction(A[k])

        m = mb.addMenu(tr("&Visualizza"))
        for k in ("view", "slideshow", "dual", "webtoon", "compare", None, "preview"):
            m.addSeparator() if k is None else m.addAction(A[k])
        pm = m.addMenu(tr("Posizione dell'anteprima"))
        g = QActionGroup(pm)
        cur = self.settings.value("browser/preview_pos", "right")
        for code, name in (("right", tr("A destra")), ("bottom", tr("In basso"))):
            a = pm.addAction(name)
            a.setCheckable(True)
            a.setChecked(cur == code)
            a.triggered.connect(lambda _=False, c=code: self.set_preview_pos(c))
            g.addAction(a)
        bm = m.addMenu(tr("Barra dei pulsanti"))
        bm.aboutToShow.connect(lambda bm=bm: (bm.clear(), self._toolbar_menu(bm)))
        m.addSeparator()
        sm = m.addMenu(tr("Ordina per"))
        self._sort_menu(sm)
        fm = m.addMenu(tr("Filtro"))
        self._filter_menu(fm)
        m.addSeparator()
        m.addAction(A["info"])
        m.addAction(A["refresh"])

        self._raccolte_menu = mb.addMenu(tr("&Raccolte"))
        self._raccolte_menu.aboutToShow.connect(self._fill_collections_menu)
        self._raccolte_add = QAction(tr("Aggiungi la selezione a…"), self)
        self._fill_collections_menu()

        m = mb.addMenu(tr("&Strumenti"))
        bm = m.addMenu(tr("Elaborazione in blocco"))
        for k in ("batch_rename", "convert", "to_cbz"):
            bm.addAction(A[k])
        m.addSeparator()
        for k in ("search", "duplicates", "calendar", "map"):
            m.addAction(A[k])
        m.addSeparator()
        m.addAction(A["options"])
        m.addAction(A["shortcuts"])
        m.addAction(self.a_shell)
        m.aboutToShow.connect(lambda: self.a_shell.setChecked(shell.is_installed()))
        lm = m.addMenu("Lingua / Language")
        cur = self.settings.value("app/language", "auto")
        g = QActionGroup(lm)
        for code, name in [("auto", tr("Automatica (come Windows)"))] + [(k, v[0]) for k, v in LANGUAGES.items()]:
            a = lm.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == cur)
            a.triggered.connect(lambda _=False, c=code: self.set_language(c))
            g.addAction(a)
        tm = m.addMenu(tr("Tema"))
        cur = self.settings.value("app/theme", "auto")
        self._theme_actions = {}
        g = QActionGroup(tm)
        for code, name in (("auto", tr("Automatico (come Windows)")),
                           ("light", tr("Chiaro")), ("dark", tr("Scuro"))):
            a = tm.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == cur)
            a.triggered.connect(lambda _=False, c=code: self.set_theme(c))
            self._theme_actions[code] = a
            g.addAction(a)

        m = mb.addMenu(tr("&Aiuto"))
        m.addAction(A["help"])
        m.addSeparator()
        m.addAction(self.a_about)

    # ------------------------------------------------- barra dei pulsanti
    def _tool_icons(self):
        """Icone dei pulsanti nel colore del testo del tema (chiaro o scuro)."""
        color = self.palette().color(self.palette().ColorRole.WindowText)
        for aid, ch in TOOL_GLYPH.items():
            self.A[aid].setIcon(glyph_icon(ch, color))

    def set_toolbar_size(self, size, save=True):
        size = size if size in TOOLBAR_SIZES else "small"
        px, under, extra = TOOLBAR_SIZES[size]
        ct = self.tools
        self._tool_icons()
        ct.setIconSize(QSize(px, px))
        ct.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon if under
                              else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        f = QApplication.font()
        if extra:
            f.setPointSizeF(f.pointSizeF() + extra)
        ct.setFont(f)
        for b in ct.findChildren(QToolButton):
            b.setFont(f)
        # nella barra piccola le frecce di rotazione restano solo icone, per occupare poco
        for aid in ("rotate_left", "rotate_right"):
            w = ct.widgetForAction(self.A[aid])
            if w is not None:
                w.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly if size == "small"
                                     else ct.toolButtonStyle())
        self.toolbar_size = size
        if save:
            self.settings.setValue("browser/toolbar_size", size)
        for a in getattr(self, "_toolbar_size_actions", {}).values():
            a.setChecked(a.data() == size)

    def toggle_toolbar(self, on):
        self.tools.setVisible(on)
        self.settings.setValue("browser/toolbar_visible", on)

    def _toolbar_menu(self, m):
        """Voci per la barra dei pulsanti (menu Visualizza e tasto destro sulla barra)."""
        a = m.addAction(tr("Mostra la barra dei pulsanti"))
        a.setCheckable(True)
        a.setChecked(self.tools.isVisible())
        a.toggled.connect(self.toggle_toolbar)
        m.addSeparator()
        g = QActionGroup(m)
        for code, name in (("small", tr("Pulsanti piccoli")), ("medium", tr("Pulsanti medi")),
                           ("large", tr("Pulsanti grandi"))):
            b = m.addAction(name)
            b.setCheckable(True)
            b.setChecked(getattr(self, "toolbar_size", "small") == code)
            b.triggered.connect(lambda _=False, c=code: self.set_toolbar_size(c))
            g.addAction(b)
        return m

    def _sort_menu(self, sm):
        g = QActionGroup(sm)
        for i, name in enumerate(sort_names()):
            a = sm.addAction(name)
            a.setCheckable(True)
            a.setChecked(self.cb_sort.currentIndex() == i)
            a.triggered.connect(lambda _=False, i=i: self.cb_sort.setCurrentIndex(i))
            g.addAction(a)
        sm.aboutToShow.connect(lambda: [a.setChecked(j == self.cb_sort.currentIndex())
                                        for j, a in enumerate(g.actions())])
        sm.addSeparator()
        a = sm.addAction(tr("Decrescente"))
        a.setCheckable(True)
        a.setChecked(self.ck_rev.isChecked())
        a.toggled.connect(self.ck_rev.setChecked)
        sm.aboutToShow.connect(lambda: a.setChecked(self.ck_rev.isChecked()))

    def _filter_menu(self, fm):
        g = QActionGroup(fm)
        for i, (k, name) in enumerate(FILTERS):
            if k in ("r0", "l1", "fav"):
                fm.addSeparator()
            a = fm.addAction(tr(name))
            a.setCheckable(True)
            a.setChecked(self.filter == k)
            a.triggered.connect(lambda _=False, i=i: self.cb_filter.setCurrentIndex(i))
            g.addAction(a)
        fm.aboutToShow.connect(lambda: [a.setChecked(FILTERS[j][0] == self.filter)
                                        for j, a in enumerate(g.actions())])

    def _fill_collections_menu(self):
        m = self._raccolte_menu
        m.clear()
        for cid, _name, cnt in library.collections():
            a = m.addAction(f"{library.display_name(cid)}  ({cnt})")
            a.triggered.connect(lambda _=False, cid=cid: self.show_collection(cid))
        m.addSeparator()
        am = m.addMenu(tr("Aggiungi la selezione a"))
        am.setEnabled(bool(self.selected_paths()))
        self._collections_submenu(am)
        if self.virtual and self.virtual.get("kind") == "collection":
            a = m.addAction(tr("Togli la selezione da questa raccolta"))
            a.setEnabled(bool(self.selected_all()))
            a.triggered.connect(self.remove_from_collection)
        m.addSeparator()
        m.addAction(tr("Nuova raccolta…"), self.new_collection)
        cur = self.virtual.get("cid") if self.virtual else None
        a = m.addAction(tr("Rinomina questa raccolta…"), self.rename_collection)
        a.setEnabled(cur is not None and library.collection_name(cur) != library.FAVORITES)
        a = m.addAction(tr("Elimina questa raccolta…"), self.delete_collection)
        a.setEnabled(cur is not None and library.collection_name(cur) != library.FAVORITES)

    def _collections_submenu(self, m):
        for cid, _name, cnt in library.collections():
            m.addAction(f"{library.display_name(cid)}  ({cnt})",
                        lambda cid=cid: self.add_to_collection(cid))
        m.addSeparator()
        m.addAction(tr("Nuova raccolta…"), lambda: self.add_to_collection(None))

    def _open_with_menu(self, parent, files, inside):
        om = parent.addMenu(tr("Apri con"))
        om.setEnabled(bool(files) and not inside)
        om.addAction(tr("Programma predefinito"), lambda: self._each_file(fileops.open_default))
        om.addAction(tr("Scegli un programma…"), lambda: self._each_file(fileops.open_with, 1))
        om.addAction(tr("Modifica con Paint"), lambda: self._each_file(fileops.edit_with_paint))
        return om

    def _sort_to_menu(self, parent, enabled):
        om = parent.addMenu(tr("Smista in"))
        om.setEnabled(enabled)
        mode = self.settings.value("sort/mode", "move")
        any_target = False
        for i in range(1, 10):
            t = self.settings.value(f"sort/target{i}", "")
            if t:
                any_target = True
                name = os.path.basename(t.rstrip("\\/")) or t
                om.addAction(f"{i}: " + (tr("Sposta in {name}", name=name) if mode == "move"
                                         else tr("Copia in {name}", name=name)),
                             lambda t=t: self.sort_to(t))
        if any_target:
            om.addSeparator()
        om.addAction(tr("Imposta le cartelle…"), lambda: self.show_options("sort"))

    def _context_menu(self, pos):
        on_item = self.view.indexAt(pos).isValid()
        if not on_item:
            self.view.clearSelection()
        self._update_actions()
        A = self.A
        inside = bool(self.folder and is_archive(self.folder))
        rows = self.selected_rows()
        files = self.selected_paths()
        dirs = self.selected_folders()
        m = QMenu(self)

        if not rows:
            for k in ("paste", "new_folder", None, "slideshow", "webtoon", "select_all"):
                m.addSeparator() if k is None else m.addAction(A[k])
            self._sort_menu(m.addMenu(tr("Ordina per")))
            self._filter_menu(m.addMenu(tr("Filtro")))
            m.addAction(A["refresh"])
            m.addSeparator()
            for k in ("search", "calendar", "map"):
                m.addAction(A[k])
            m.addSeparator()
            m.addAction(A["explorer"])
            m.addAction(A["properties"])
            m.exec(self.view.viewport().mapToGlobal(pos))
            return

        for k in ("view", "slideshow", "webtoon"):
            m.addAction(A[k])
        if len(dirs) == 2 and len(rows) == 2:
            m.addAction(A["dual"])
        if A["compare"].isEnabled():
            m.addAction(A["compare"])
        m.addSeparator()
        self._open_with_menu(m, files, inside)
        m.addAction(A["edit"])
        self._rotate_menu(m)
        bm = m.addMenu(tr("Elaborazione in blocco"))
        for k in ("batch_rename", "convert", "to_cbz"):
            bm.addAction(A[k])
        m.addAction(A["wallpaper"])
        m.addSeparator()
        self._rating_menu(m)
        self._label_menu(m)
        fav = A["favorite"]
        m.addAction(fav)
        cm = m.addMenu(tr("Aggiungi a raccolta"))
        cm.setEnabled(bool(files))
        self._collections_submenu(cm)
        if self.virtual and self.virtual.get("kind") == "collection":
            m.addAction(tr("Togli dalla raccolta"), self.remove_from_collection)
        m.addSeparator()
        for k in ("cut", "copy"):
            m.addAction(A[k])
        paste_into = len(rows) == 1 and dirs and not inside and not is_archive(dirs[0])
        if paste_into:
            A["paste"].setText(tr("Incolla nella cartella"))
            A["paste"].setEnabled(fileops.clipboard_has_files())
        m.addAction(A["paste"])
        for k in ("rename", "copy_to", "move_to"):
            m.addAction(A[k])
        self._sort_to_menu(m, bool(files) and not inside)
        m.addAction(A["delete"])
        if A["undo"].isEnabled():
            m.addAction(A["undo"])
        m.addSeparator()
        m.addAction(A["print"])
        m.addAction(A["explorer"])
        m.addAction(A["copy_path"])
        m.addSeparator()
        if len(rows) == 1 and files:
            m.addAction(A["info"])
        else:
            m.addAction(A["properties"])
        m.exec(self.view.viewport().mapToGlobal(pos))
        A["paste"].setText(shortcuts.label("browser", "paste"))
        self._update_actions()

    def _renamable_archives(self):
        return [p for p in self.selected_folders() if is_archive(p) and os.path.isfile(p)]

    def _convertible_archives(self):
        return [p for p in self.selected_folders() if is_archive(p) and os.path.isfile(p)
                and os.path.splitext(p)[1].lower() != ".cbz"]

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

    def set_filter(self, key):
        self.filter = key
        self.settings.setValue("browser/filter", key)
        self.reload()

    def toggle_preview(self):
        on = not self.preview.isVisible()
        self.preview.setVisible(on)
        self.A["preview"].setChecked(on)
        self.settings.setValue("browser/preview", on)
        if on:
            self._after_selection()

    def set_preview_pos(self, code):
        self.settings.setValue("browser/preview_pos", code)
        self.inner.setOrientation(Qt.Orientation.Vertical if code == "bottom" else Qt.Orientation.Horizontal)

    # ============================================================ cartelle
    def _tree_changed(self, cur, _prev):
        if cur.isValid():
            path = self.fs.filePath(cur)
            if path and (self.virtual is not None or not samepath(path, self.folder)):
                self.set_folder(path, sync_tree=False)

    def set_folder(self, path, sync_tree=True, select=None, add_history=True):
        path = (path or "").strip().strip('"')
        host = unc_server(path)
        if host:
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
        if add_history and (self.virtual is not None or (self.folder and not samepath(self.folder, path))):
            self.history.append(self.virtual if self.virtual is not None else self.folder)
            self.history = self.history[-50:]
        self.virtual = None
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.folder = path
        if not host and not is_archive(path):
            self.watcher.addPath(path)
            try:
                flush_leftovers(path)
            except OSError:
                pass
        self.settings.setValue("browser/last_folder", path)
        self.path_edit.setText(path)
        self.setWindowTitle(f"{os.path.basename(path) or path} - {APP_NAME}")
        if select is None and is_archive(path) and self.settings.value("comics/resume", True, type=bool):
            lp = library.last_page(path)
            if lp:
                select = path + "|" + lp[0]
                self.statusBar().showMessage(tr("Ultima pagina letta: {i} di {n}", i=lp[1], n=lp[2]), 5000)
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

    def show_virtual(self, title, paths, kind="list", cid=None):
        """Mostra un elenco di file da cartelle diverse (raccolta, ricerca, calendario…)."""
        if self.virtual is None and self.folder:
            self.history.append(self.folder)
        elif self.virtual is not None:
            self.history.append(self.virtual)
        self.history = self.history[-50:]
        self.virtual = {"kind": kind, "title": title, "paths": list(paths), "cid": cid}
        if self.watcher.directories():
            self.watcher.removePaths(self.watcher.directories())
        self.path_edit.setText(title)
        self.setWindowTitle(f"{title} - {APP_NAME}")
        self.tree.clearSelection()
        self._load(scroll_top=True)

    def _virtual_items(self):
        v = self.virtual
        if v["kind"] == "collection":
            v["paths"] = library.collection_items(v["cid"])
        items = []
        for p in v["paths"]:
            try:
                mt, sz = stat_any(p)
            except OSError:
                continue
            items.append(FileItem(p, os.path.basename(p.split("|")[-1]), sz, mt))
        k, r = self._sort_key()
        if v["kind"] != "collection" or k != "name":
            from .utils import natural_key
            if k == "date":
                items.sort(key=lambda i: i.mtime)
            elif k == "size":
                items.sort(key=lambda i: i.size)
            elif v["kind"] != "collection":
                items.sort(key=lambda i: natural_key(i.name))
        if r:
            items.reverse()
        return items

    def _apply_filter(self, items):
        f = self.filter
        if f == "all":
            return items
        files = [i for i in items if not i.is_dir]
        dirs = [i for i in items if i.is_dir]
        meta = library.get_many([i.path for i in files])
        fav = set()
        if f == "fav":
            fid = library.favorites_id()
            fav = {i.path for i in files if library.in_collection(fid, i.path)}

        def ok(it):
            r, lb = meta.get(it.path, (0, 0))
            if f.startswith("r"):
                n = int(f[1])
                return r == 0 if n == 0 else r >= n
            if f == "lx":
                return lb > 0
            if f.startswith("l"):
                return lb == int(f[1])
            if f == "fav":
                return it.path in fav
            if f == "img":
                return not is_video(it.path)
            if f == "vid":
                return is_video(it.path)
            return True
        return dirs + [i for i in files if ok(i)]

    def _load(self, select=None, scroll_top=False):
        k, r = self._sort_key()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            items = self._virtual_items() if self.virtual is not None else list_folder_items(self.folder, k, r)
        except OSError:
            items = []
        finally:
            QApplication.restoreOverrideCursor()
        total = len(items)
        items = self._apply_filter(items)
        self.animator.stop()
        self.model.set_items(items)
        self._hidden_by_filter = total - len(items)
        if select:
            self.select_paths(select)
        elif scroll_top:
            self.view.scrollToTop()
            if items:
                self.view.selectionModel().setCurrentIndex(
                    self.model.index(0), QItemSelectionModel.SelectionFlag.NoUpdate)
        self._selection_changed()

    def reload(self):
        if self.virtual is None:
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
        cur_path = self.model.path(cur.row()) if cur.isValid() and cur.row() < len(self.model.items) else None
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
        if not path:
            return
        if os.path.isdir(path):
            if self.virtual is not None or not samepath(path, self.folder):
                self.set_folder(path)
            return
        if self.virtual is not None and any(samepath(p, path) for p in self.virtual["paths"]):
            self.reload()
            self.select_paths([path])
            return
        d = parent_of(path)
        if self.virtual is not None or not samepath(d, self.folder):
            self.set_folder(d, select=path)
        else:
            self.reload()
            self.select_paths([path])

    def go_back(self):
        while self.history:
            p = self.history.pop()
            if isinstance(p, dict):
                self.virtual = None
                self.show_virtual(p["title"], p["paths"], p["kind"], p.get("cid"))
                self.history.pop()   # show_virtual ha rimesso in cronologia la vista attuale
                return
            if os.path.isdir(p) or (is_archive(p) and os.path.isfile(p)):
                self.set_folder(p, add_history=False)
                return

    def go_up(self):
        if self.virtual is not None:
            self.go_back() if self.history else self.set_folder(self.folder or os.path.expanduser("~"))
            return
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

    # ============================================================ selezione
    def selected_rows(self):
        return sorted(i.row() for i in self.view.selectionModel().selectedIndexes()
                      if i.row() < len(self.model.items))

    def selected_all(self):
        return [self.model.path(r) for r in self.selected_rows()]

    def selected_paths(self):
        """Solo i file (immagini e video) selezionati."""
        return [self.model.path(r) for r in self.selected_rows() if not self.model.is_dir(r)]

    def selected_folders(self):
        return [self.model.path(r) for r in self.selected_rows() if self.model.is_dir(r)]

    def _selection_changed(self, *_):
        self._update_status()
        self._update_actions()
        self._sel_timer.start()

    def _after_selection(self):
        rows = self.selected_rows()
        path = None
        if len(rows) == 1 and not self.model.is_dir(rows[0]):
            path = self.model.path(rows[0])
        if self.settings.value("browser/animate_thumbs", True, type=bool) and not self.preview.isVisible():
            self.animator.play(path)
        else:
            self.animator.play(None)
        if self.preview.isVisible():
            if path is None:
                cur = self.view.currentIndex()
                if cur.isValid() and cur.row() < len(self.model.items) and not self.model.is_dir(cur.row()):
                    path = self.model.path(cur.row())
            self.preview.show_path(path)

    def _update_status(self):
        nd, ni = self.model.counts()
        na = sum(1 for it in self.model.items if it.is_dir and is_archive(it.name))
        nv = sum(1 for it in self.model.items if not it.is_dir and is_video(it.path))
        parts = []
        if nd - na:
            parts.append(tr("{n} cartelle", n=nd - na))
        if na:
            parts.append(tr("{n} archivi", n=na))
        parts.append(tr("{n} immagini", n=ni - nv) + f"  ·  {human_size(self.model.total_size())}")
        if nv:
            parts.append(tr("{n} video", n=nv))
        txt = "   ·   ".join(parts)
        if getattr(self, "_hidden_by_filter", 0):
            txt += "   ·   " + tr("{n} nascosti dal filtro", n=self._hidden_by_filter)
        sd, si = len(self.selected_folders()), self.selected_paths()
        if sd or si:
            sel = []
            if sd:
                sel.append(tr("{n} cartelle", n=sd))
            if si:
                size = 0
                for p in si:
                    try:
                        size += stat_any(p)[1]
                    except OSError:
                        pass
                sel.append(tr("{n} file", n=len(si)) + f" ({human_size(size)})")
            txt += "   |   " + tr("Selezionati:") + " " + ", ".join(sel)
        self.status.setText(txt)

    def _targets(self, folders_ok=False):
        if self.folder and is_archive(self.folder) and self.virtual is None:
            QMessageBox.information(self, APP_NAME,
                                    tr("Le operazioni in blocco non sono disponibili dentro un archivio.\n"
                                       "Torna alla cartella che lo contiene (Backspace) per "
                                       "copiare, spostare o eliminare l'archivio intero."))
            return []
        if folders_ok == "archives":
            paths = self.selected_paths() + self._renamable_archives()
        else:
            paths = self.selected_all() if folders_ok else self.selected_paths()
        paths = [p for p in paths if not is_virtual(p)]
        if not paths:
            QMessageBox.information(self, APP_NAME,
                                    tr("Seleziona prima una o più immagini o cartelle.") if folders_ok is True
                                    else tr("Seleziona prima una o più immagini."))
        return paths

    # ================================================= visualizza / slideshow
    def activate(self, row=None):
        if row is None:
            cur = self.view.currentIndex()
            row = cur.row() if cur.isValid() else (self.selected_rows() or [None])[0]
        if row is None or row >= len(self.model.items):
            return
        if self.model.is_dir(row):
            self.set_folder(self.model.path(row))
        else:
            self.open_viewer(row)

    def _view_files(self):
        return [it.path for it in self.model.items if not it.is_dir]

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
        start = self.model.path(row)
        if self.virtual is not None or self.filter != "all":
            nav = Navigator(parent_of(start), images=self._view_files(), start=start, sort=k, reverse=r)
        else:
            nav = Navigator(self.folder, start=start, sort=k, reverse=r, loop=False)
        self.app.open_viewer(nav, slideshow=False)

    def start_slideshow(self):
        k, r = self._sort_key()
        sel = self.selected_paths()
        sel_dirs = self.selected_folders()
        sub = self.ck_sub.isChecked()
        opts = dict(shuffle=self.ck_random.isChecked(), loop=self.ck_loop.isChecked(), sort=k, reverse=r)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self.virtual is not None or (self.filter != "all" and not sel_dirs):
                files = sel if len(sel) >= 2 else self._view_files()
                if not files:
                    nav = None
                else:
                    start = sel[0] if len(sel) == 1 else None
                    nav = Navigator(parent_of(files[0]), images=files, start=start, **opts)
            elif not self.folder:
                nav = None
            elif len(sel_dirs) == 1:
                all_dirs = [it.path for it in self.model.items if it.is_dir]
                nav = Navigator(self.folder, folders=self._expand(all_dirs, sub),
                                start_folder=sel_dirs[0], **opts)
            elif sel_dirs:
                nav = Navigator(self.folder, folders=self._expand(sel_dirs, sub), **opts)
            elif len(sel) >= 2:
                nav = Navigator(self.folder, images=sel, **opts)
            elif unc_server(self.folder) or (not sub and not has_images(self.folder)):
                all_dirs = [it.path for it in self.model.items if it.is_dir]
                nav = Navigator(self.folder, folders=self._expand(all_dirs, sub), **opts)
            else:
                nav = Navigator(self.folder, start=sel[0] if sel else None, include_sub=sub, **opts)
        finally:
            QApplication.restoreOverrideCursor()
        if nav is None or nav.current() is None:
            QMessageBox.information(self, tr("Slideshow"), tr("Nessuna immagine trovata."))
            return
        self.app.open_viewer(nav, slideshow=True)

    def dual_slideshow(self):
        dirs = self.selected_folders()
        left = dirs[0] if dirs else (self.folder if self.folder and has_images(self.folder) else "")
        right = dirs[1] if len(dirs) > 1 else ""
        self.app.open_dual(left, right, self)

    def open_webtoon(self):
        """Lettura verticale: della cartella / archivio selezionato o di quella corrente."""
        dirs = self.selected_folders()
        k, r = self._sort_key()
        from .utils import list_images
        if len(dirs) == 1:
            paths = [p for p in list_images(dirs[0], k, r) if not is_video(p)]
            start = None
        else:
            paths = [p for p in self._view_files() if not is_video(p)]
            sel = self.selected_paths()
            start = sel[0] if sel else None
        if not paths:
            QMessageBox.information(self, APP_NAME, tr("Nessuna immagine trovata."))
            return
        from .webtoon import start_index
        i = paths.index(start) if start in paths else start_index(paths, self.settings)
        self.app.open_webtoon(paths, i)

    def compare(self):
        files = [p for p in self.selected_paths() if is_image(p)]
        if len(files) != 2:
            QMessageBox.information(self, APP_NAME, tr("Seleziona esattamente due immagini da confrontare."))
            return
        self.app.open_compare(files[0], files[1])

    _expand = staticmethod(expand_folders)

    # ============================================================ in blocco
    def batch_rename(self):
        paths = self._targets(folders_ok="archives")
        if paths and batch.RenameDialog(paths, self.settings, self).run():
            self.reload()

    def batch_convert(self):
        paths = [p for p in self._targets() if is_image(p)]
        if paths and batch.ConvertDialog(paths, self.settings, self).run():
            self.reload()

    def batch_copy(self, move):
        paths = self._targets(folders_ok=True)
        if paths and batch.copy_move_dialog(self, paths, self.settings, move):
            self.reload()

    def batch_delete(self):
        paths = self._targets(folders_ok=True)
        if not paths:
            return
        what = os.path.basename(paths[0]) if len(paths) == 1 else tr("{n} elementi", n=len(paths))
        k = shortcuts.native(self.settings, "browser", "undo", True)
        r = QMessageBox.question(self, tr("Elimina"), tr("Spostare nel Cestino {what}?", what=what) +
                                 (("\n\n" + tr("Si può annullare con {k}.", k=k)) if k else ""))
        if r != QMessageBox.StandardButton.Yes:
            return
        failed = [os.path.basename(p) for p in paths if not undo_manager.delete(p)]
        if failed:
            QMessageBox.warning(self, tr("Elimina"), tr("Non eliminati: {names}", names=", ".join(failed[:10])))
        self.reload()

    def undo(self):
        if not undo_manager.can_undo():
            return
        try:
            op = undo_manager.undo()
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, tr("Impossibile annullare:\n{err}", err=e))
            return
        if op is None:
            return
        self.reload()
        if op.kind != "copy":
            self.reveal(op.src)
        self.statusBar().showMessage({"delete": tr("Eliminazione annullata"), "move": tr("Spostamento annullato"),
                                      "copy": tr("Copia annullata")}[op.kind], 3000)

    def to_cbz(self):
        arcs = self._convertible_archives()
        if not arcs:
            return
        from . import archive
        from .worker import run_with_progress

        def work(progress):
            out, errors = [], []
            for i, a in enumerate(arcs):
                try:
                    out.append(archive.to_cbz(a, progress=lambda j, n, a=a: progress(
                        i * 1000 + j * 1000 // max(1, n), len(arcs) * 1000, os.path.basename(a))))
                except InterruptedError:
                    raise
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{os.path.basename(a)}: {e}")
            return out, errors
        try:
            res = run_with_progress(self, tr("Conversione in CBZ…"), work)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if res is None:
            return
        out, errors = res
        if errors:
            QMessageBox.warning(self, APP_NAME, "\n".join(errors[:15]))
        if out:
            r = QMessageBox.question(self, APP_NAME, tr("Creati {n} file CBZ.\n\nSpostare gli originali nel Cestino?",
                                                        n=len(out)))
            if r == QMessageBox.StandardButton.Yes:
                for a, o in zip(arcs, out):
                    if o:
                        undo_manager.delete(a)
                        library.move_path(a, o)
            self.reload()
            self.select_paths(out)

    def rotate_files(self, op):
        from . import orient
        files = [p for p in self.selected_paths() if orient.can_save(p)]
        if not files:
            return
        o = orient.compose(orient.IDENTITY, op)
        errors, lossy = [], 0
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in files:
                try:
                    if orient.save_to_file(p, o) != "lossless":
                        lossy += 1
                    self.app.loader.forget(p)
                except OSError as e:
                    errors.append(f"{os.path.basename(p)}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        if errors:
            QMessageBox.warning(self, APP_NAME, "\n".join(errors[:15]))
        self.statusBar().showMessage(tr("Ruotate: {n}", n=len(files) - len(errors)) +
                                     (("  ·  " + tr("senza perdita: {n}", n=len(files) - len(errors) - lossy))
                                      if lossy < len(files) else ""), 4000)
        self.reload()

    def edit_image(self):
        files = [p for p in self.selected_paths() if is_image(p) and not is_virtual(p)]
        if len(files) != 1:
            return
        from .edit import EditorDialog
        saved = EditorDialog(files[0], self.settings, self).run()
        if saved:
            self.app.loader.forget(files[0])
            self.reload()
            self.select_paths([saved])

    def sort_to(self, target):
        mode = self.settings.value("sort/mode", "move")
        files = [p for p in self.selected_paths() if not is_virtual(p)]
        if not files:
            return
        errors = []
        for p in files:
            try:
                undo_manager.move(p, target) if mode == "move" else undo_manager.copy(p, target)
            except OSError as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        if errors:
            QMessageBox.warning(self, APP_NAME, "\n".join(errors[:15]))
        self.reload()

    # ============================================ valutazioni e raccolte
    def set_rating(self, n):
        files = self.selected_paths()
        if files:
            library.set_rating(files, n)
            self._meta_changed(files)

    def set_label(self, n):
        files = self.selected_paths()
        if files:
            library.set_label(files, n)
            self._meta_changed(files)

    def _meta_changed(self, files):
        self.model.refresh_meta(files)
        self.preview.refresh()
        if self.filter != "all":
            self.reload()

    def toggle_favorite(self):
        files = self.selected_paths()
        if not files:
            return
        added = library.toggle_favorite(files)
        self.statusBar().showMessage(tr("Aggiunti ai Preferiti: {n}", n=len(files)) if added
                                     else tr("Tolti dai Preferiti: {n}", n=len(files)), 3000)
        self._meta_changed(files)
        if self.virtual and self.virtual.get("kind") == "collection":
            self.reload()

    def add_to_collection(self, cid=None):
        files = self.selected_paths()
        if not files:
            return
        if cid is None:
            name, ok = QInputDialog.getText(self, tr("Nuova raccolta"), tr("Nome della raccolta:"))
            if not ok or not name.strip():
                return
            cid = library.collection_id(name.strip(), create=True)
        n = library.add_to_collection(cid, files)
        self.statusBar().showMessage(tr("Aggiunti a «{name}»: {n}", name=library.display_name(cid), n=n), 3000)
        self.model.refresh_meta(files)

    def remove_from_collection(self):
        if not (self.virtual and self.virtual.get("kind") == "collection"):
            return
        sel = self.selected_all()
        if sel:
            library.remove_from_collection(self.virtual["cid"], sel)
            self.reload()

    def show_collection(self, cid):
        self.show_virtual(library.display_name(cid), library.collection_items(cid), "collection", cid)

    def new_collection(self):
        name, ok = QInputDialog.getText(self, tr("Nuova raccolta"), tr("Nome della raccolta:"))
        if ok and name.strip():
            cid = library.collection_id(name.strip(), create=True)
            if self.selected_paths():
                library.add_to_collection(cid, self.selected_paths())
            self.show_collection(cid)

    def rename_collection(self):
        cid = self.virtual.get("cid") if self.virtual else None
        if cid is None:
            return
        name, ok = QInputDialog.getText(self, tr("Rinomina raccolta"), tr("Nuovo nome:"),
                                        text=library.collection_name(cid))
        if ok and name.strip():
            try:
                library.rename_collection(cid, name.strip())
            except Exception as e:  # noqa: BLE001 - nome già usato
                QMessageBox.warning(self, APP_NAME, str(e))
                return
            self.show_collection(cid)

    def delete_collection(self):
        cid = self.virtual.get("cid") if self.virtual else None
        if cid is None:
            return
        r = QMessageBox.question(self, APP_NAME, tr("Eliminare la raccolta «{name}»?\n(Le immagini restano dove sono.)",
                                                    name=library.display_name(cid)))
        if r == QMessageBox.StandardButton.Yes:
            library.delete_collection(cid)
            self.go_back()

    # ============================================================ strumenti
    def search(self):
        from .search import SearchDialog
        start = self.folder if self.folder and not is_archive(self.folder) and not unc_server(self.folder) else ""
        res = SearchDialog(self.settings, start, self).run()
        if res is not None:
            title, paths = res
            self.show_virtual(title, paths, "search")

    def find_duplicates(self):
        from .duplicates import FindDialog, ResultsWindow
        dirs = [d for d in self.selected_folders() if os.path.isdir(d)]
        roots = dirs or ([self.folder] if self.folder and os.path.isdir(self.folder) else [])
        try:
            groups = FindDialog(self.settings, roots, self).run()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if groups is None:
            return
        if not groups:
            QMessageBox.information(self, APP_NAME, tr("Nessun duplicato trovato."))
            return

        def open_one(p):
            self.app.open_viewer(Navigator(os.path.dirname(p), start=p))

        w = ResultsWindow(groups, open_one,
                          lambda ps: self.show_virtual(tr("Duplicati") + f" ({len(ps)})", ps, "duplicates"), self)
        w.show()

    def calendar(self):
        if not self.folder or not os.path.isdir(self.folder):
            return
        from .timeline import CalendarWindow
        w = CalendarWindow(self.folder, self.settings, lambda title, ps: self.show_virtual(title, ps, "calendar"), self)
        if w.rescan():
            w.show()
        else:
            w.deleteLater()

    def photo_map(self):
        from .gpsmap import show_map
        files = self.selected_paths() if len(self.selected_paths()) > 1 else self._view_files()
        title = self.virtual["title"] if self.virtual else (os.path.basename(self.folder or "") or self.folder or "")
        show_map(self, [p for p in files if is_image(p)], title)

    # ================================================= comandi sui file
    def _real_selection(self):
        if self.folder and is_archive(self.folder) and self.virtual is None:
            return []
        return [p for p in self.selected_all() if not is_virtual(p)]

    def rename_item(self):
        sel = self._real_selection()
        if len(sel) > 1:
            self.batch_rename()
            return
        if not sel:
            return
        new = fileops.rename_single(self, sel[0])
        if new:
            if self.virtual is not None:
                self.virtual["paths"] = [new if samepath(p, sel[0]) else p for p in self.virtual["paths"]]
            self.reload()
            self.select_paths([new])

    def to_clipboard(self, cut):
        sel = self._real_selection()
        if sel:
            fileops.clipboard_set(sel, cut)
            self.statusBar().showMessage(
                (tr("Tagliati: {n}", n=len(sel)) if cut else tr("Copiati negli appunti: {n}", n=len(sel))), 3000)

    def paste(self):
        if self.virtual is not None or not self.folder or is_archive(self.folder) or unc_server(self.folder):
            return
        paths, cut = fileops.clipboard_get()
        if not paths:
            return
        dest = self.folder
        dirs = self.selected_folders()
        if self.A["paste"].text() == tr("Incolla nella cartella") and len(dirs) == 1:
            dest = dirs[0]
        if batch.transfer(self, paths, dest, move=cut):
            if cut:
                QApplication.clipboard().clear()
            self.reload()
            if samepath(dest, self.folder):
                self.select_paths([os.path.join(dest, os.path.basename(p)) for p in paths])

    def make_folder(self):
        if self.virtual is not None or not self.folder or is_archive(self.folder) or unc_server(self.folder):
            return
        new = fileops.new_folder(self, self.folder)
        if new:
            self.reload()
            self.select_paths([new])

    def _each_file(self, fn, limit=20):
        files = [p for p in self.selected_paths() if not is_virtual(p)]
        for p in files[:limit]:
            fn(p)

    def set_wallpaper(self):
        files = [p for p in self.selected_paths() if is_image(p)]
        if files:
            fileops.set_wallpaper(self, files[0])

    def print_selected(self):
        files = [p for p in self.selected_paths() if is_image(p)]
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

    def show_options(self, tab=None):
        from .options import OptionsDialog
        if OptionsDialog(self.settings, self, tab=tab).run():
            for v in self.app.viewers:
                if hasattr(v, "apply_options"):
                    v.apply_options()
            self._apply_shortcuts()
            self.animator.stop()
            self.reload()

    def show_shortcuts(self):
        if shortcuts.ShortcutsDialog(self.settings, self).run():
            self._apply_shortcuts()
            for v in self.app.viewers:
                if hasattr(v, "apply_options"):
                    v.apply_options()

    def show_help(self):
        box = QMessageBox(self)
        box.setWindowTitle(tr("Scorciatoie da tastiera"))
        box.setText(shortcuts.help_html(self.settings))
        box.exec()

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
        from . import theme
        self.settings.setValue("app/theme", code)
        theme.apply(QApplication.instance(), code)
        for c, a in self._theme_actions.items():
            a.setChecked(c == code)
        self._tool_icons()      # icone nel colore del nuovo tema

    def set_language(self, code):
        if code == self.settings.value("app/language", "auto"):
            return
        self.settings.setValue("app/language", code)
        from . import i18n
        i18n.init(self.settings)
        if shell.is_installed():
            try:
                shell.install()
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
        undo_manager.flush()
        r = QProcess.startDetached(sys.executable, args)
        if (r[0] if isinstance(r, tuple) else r):
            for v in list(self.app.viewers):
                v.close()
            self.close()
            QApplication.quit()

    def changeEvent(self, e):
        # tema chiaro / scuro cambiato (anche in automatico, dal sistema): icone ridisegnate
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange) and hasattr(self, "tools"):
            self._tool_icons()
        super().changeEvent(e)

    def closeEvent(self, e):
        self.settings.setValue("browser/geometry", self.saveGeometry())
        self.settings.setValue("browser/splitter", self.split.saveState())
        self.settings.setValue("browser/inner_splitter", self.inner.saveState())
        super().closeEvent(e)


def real_images_of(files):
    return [p for p in files if is_image(p) and not is_virtual(p)]
