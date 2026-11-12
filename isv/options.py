"""Opzioni: avvisi e aspetto, slideshow, visualizzatore, animazioni e GPU, smistamento,
salvaschermo, formati. Una scheda per argomento."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

DEFAULTS = {
    "osd/folder": True,          # nome cartella quando cambia
    "osd/messages": True,        # pausa, intervallo, fine, zoom...
    "osd/pause_badge": True,     # indicatore fisso "In pausa"
    "osd/folder_pos": "top",     # top | center | bottom
    "osd/color": "#ebebeb",
    "osd/bg": "#000000",
    "osd/bg_alpha": 67,          # percentuale
    "osd/size": 15,
    "osd/folder_ms": 1800,
    "viewer/controls": True,     # barra comandi al movimento del mouse
    "viewer/animate_slideshow": True,  # GIF/WebP animate nello slideshow in pausa
    "viewer/animate_pair": False,      # ... anche con 2 immagini affiancate (in pausa)
    "browser/animate_thumbs": True,    # miniatura animata della GIF/WebP selezionata
    "gpu/render": "auto",        # auto | gl | gl_soft | cpu (vedi gpu.py; serve il riavvio)
    "gpu/nvjpeg": False,         # JPEG decodificati dalla GPU NVIDIA (nvImageCodec)
    "viewer/quick_delete": True,       # Canc senza conferma (annullabile con Ctrl+Z)
    "viewer/video_audio": False,       # audio dei video
    "viewer/loupe_mag": 3.0,
    "slideshow/transition": "fade",    # none | fade | slide | kenburns
    "slideshow/transition_ms": 600,
    "slideshow/kenburns_zoom": 12,     # percentuale di zoom del Ken Burns
    "slideshow/music": "",             # file o cartella
    "slideshow/music_shuffle": True,
    "slideshow/music_volume": 60,
    "slideshow/double_pages": True,    # pagine doppie da sole con 2 affiancate
    "slideshow/screen": "window",      # window | primary | secondary | <nome schermo>
    "slideshow/videos": True,          # video nel browser e nello slideshow
    "comics/resume": True,             # archivi: riprendi dall'ultima pagina letta
    "sort/advance": True,
    "screensaver/enabled": False,
    "screensaver/minutes": 10,
    "screensaver/folder": "",
    "screensaver/subfolders": True,
    "screensaver/interval": 6.0,
}
from .i18n import tr

POSITION_KEYS = ["top", "center", "bottom"]


def position_names():
    return [tr("In alto"), tr("Al centro"), tr("In basso")]


def load_style(settings):
    out = {}
    for k, d in DEFAULTS.items():
        out[k] = settings.value(k, d, type=type(d))
    return out


class _Preview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(90)
        self.style_ = dict(DEFAULTS)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # sfondo a scacchi chiaro/scuro: si vede se il testo resta leggibile ovunque
        w = self.width() // 2
        p.fillRect(0, 0, w, self.height(), QColor(245, 245, 240))
        p.fillRect(w, 0, self.width() - w, self.height(), QColor(25, 25, 28))
        s = self.style_
        f = QFont(self.font())
        f.setPointSize(int(s["osd/size"]))
        f.setBold(True)
        p.setFont(f)
        txt = tr("Cartella: ") + tr("Esempio") + " (3/12)"
        fm = p.fontMetrics()
        bw, bh = fm.horizontalAdvance(txt) + 26, fm.height() + 20
        x, y = (self.width() - bw) / 2, (self.height() - bh) / 2
        bg = QColor(s["osd/bg"])
        bg.setAlpha(round(int(s["osd/bg_alpha"]) * 2.55))
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, bw, bh), 8, 8)
        p.fillPath(path, bg)
        p.setPen(QColor(s["osd/color"]))
        p.drawText(QRectF(x, y, bw, bh), Qt.AlignmentFlag.AlignCenter, txt)


def _spacer(h=6):
    w = QWidget()
    w.setFixedHeight(h)
    return w


class OptionsDialog(QDialog):
    TABS = ["osd", "slideshow", "viewer", "anim", "sort", "screensaver", "formats"]

    def __init__(self, settings, parent=None, tab=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Opzioni"))
        self.settings = settings
        self.s = load_style(settings)
        from . import gpu, gpudecode
        self._render_at_start = gpu.mode()
        self.restart_needed = False
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_osd(), tr("Avvisi e aspetto"))
        self.tabs.addTab(self._tab_slideshow(), tr("Slideshow"))
        self.tabs.addTab(self._tab_viewer(), tr("Visualizzatore"))
        self.tabs.addTab(self._tab_anim(gpu, gpudecode), tr("Animazioni e GPU"))
        self.tabs.addTab(self._tab_sort(), tr("Smistamento"))
        self.tabs.addTab(self._tab_screensaver(), tr("Salvaschermo"))
        self.tabs.addTab(self._tab_formats(), tr("Formati"))
        if tab in self.TABS:
            self.tabs.setCurrentIndex(self.TABS.index(tab))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel |
                              QDialogButtonBox.StandardButton.RestoreDefaults)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText(tr("Predefiniti"))
        bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        b_keys = bb.addButton(tr("Tasti di scelta rapida…"), QDialogButtonBox.ButtonRole.ActionRole)
        b_keys.clicked.connect(self._keys)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(bb)
        self.resize(720, 600)
        self._fill()

    @staticmethod
    def _page(*widgets):
        w = QWidget()
        v = QVBoxLayout(w)
        for x in widgets:
            v.addWidget(x)
        v.addStretch()
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setWidget(w)
        return sa

    @staticmethod
    def _path_row(edit, title, folder=True, files_filter=""):
        b = QPushButton(tr("Sfoglia…"))

        def pick():
            if folder:
                d = QFileDialog.getExistingDirectory(edit, title, edit.text())
            else:
                d, _f = QFileDialog.getOpenFileName(edit, title, edit.text(), files_filter)
            if d:
                edit.setText(d)
        b.clicked.connect(pick)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit)
        row.addWidget(b)
        w = QWidget()
        w.setLayout(row)
        return w

    # ------------------------------------------------------------- schede
    def _tab_osd(self):
        self.ck_folder = QCheckBox(tr("Mostra il nome della cartella quando cambia"))
        self.ck_msgs = QCheckBox(tr("Mostra gli altri avvisi (pausa, intervallo, fine slideshow, zoom)"))
        self.ck_badge = QCheckBox(tr("Mostra l'indicatore \"In pausa\" mentre lo slideshow è fermo"))
        self.ck_controls = QCheckBox(tr("Mostra la barra dei comandi quando muovi il mouse"))
        self.cb_pos = QComboBox()
        self.cb_pos.addItems(position_names())
        self.sp_ms = QSpinBox(minimum=500, maximum=10000, singleStep=250)
        self.sp_ms.setSuffix(" ms")
        self.b_color = QPushButton()
        self.b_bg = QPushButton()
        self.sl_alpha = QSlider(Qt.Orientation.Horizontal)
        self.sl_alpha.setRange(0, 100)
        self.sp_size = QSpinBox(minimum=8, maximum=48)
        self.sp_size.setSuffix(" pt")
        self.preview = _Preview()
        g1 = QGroupBox(tr("Avvisi a schermo"))
        f1 = QFormLayout(g1)
        f1.addRow(self.ck_folder)
        f1.addRow(tr("Posizione nome cartella:"), self.cb_pos)
        f1.addRow(tr("Durata nome cartella:"), self.sp_ms)
        f1.addRow(self.ck_msgs)
        f1.addRow(self.ck_badge)
        g2 = QGroupBox(tr("Aspetto"))
        f2 = QFormLayout(g2)
        f2.addRow(tr("Colore del testo:"), self.b_color)
        f2.addRow(tr("Colore dello sfondo:"), self.b_bg)
        f2.addRow(tr("Opacità dello sfondo:"), self.sl_alpha)
        f2.addRow(tr("Dimensione del testo:"), self.sp_size)
        f2.addRow(self.preview)
        presets = QHBoxLayout()
        for name, fg, bg, a in ((tr("Bianco su nero"), "#ebebeb", "#000000", 67),
                                (tr("Giallo su nero"), "#ffd84a", "#000000", 75),
                                (tr("Nero su bianco"), "#111111", "#ffffff", 80),
                                (tr("Solo testo"), "#ffffff", "#000000", 0)):
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, fg=fg, bg=bg, a=a: self._preset(fg, bg, a))
            presets.addWidget(b)
        f2.addRow(tr("Rapidi:"), presets)
        g3 = QGroupBox(tr("Comandi"))
        f3 = QFormLayout(g3)
        f3.addRow(self.ck_controls)
        self.b_color.clicked.connect(lambda: self._pick("osd/color", tr("Colore del testo")))
        self.b_bg.clicked.connect(lambda: self._pick("osd/bg", tr("Colore dello sfondo")))
        for w in (self.sl_alpha, self.sp_size):
            w.valueChanged.connect(self._sync)
        return self._page(g1, g2, g3)

    def _tab_slideshow(self):
        from .canvas import TRANSITIONS, transition_name
        self.cb_trans = QComboBox()
        self.cb_trans.addItems([transition_name(t) for t in TRANSITIONS])
        self.sp_trans = QSpinBox(minimum=100, maximum=5000, singleStep=100)
        self.sp_trans.setSuffix(" ms")
        self.sp_kb = QSpinBox(minimum=2, maximum=40)
        self.sp_kb.setSuffix(" %")
        g1 = QGroupBox(tr("Transizioni"))
        f1 = QFormLayout(g1)
        f1.addRow(tr("Transizione tra le immagini:"), self.cb_trans)
        f1.addRow(tr("Durata:"), self.sp_trans)
        f1.addRow(tr("Zoom del Ken Burns:"), self.sp_kb)
        self.ed_music = QLineEdit()
        self.ed_music.setPlaceholderText(tr("un file audio oppure una cartella di brani"))
        self.ck_music_shuffle = QCheckBox(tr("Brani in ordine casuale"))
        self.sl_volume = QSlider(Qt.Orientation.Horizontal)
        self.sl_volume.setRange(0, 100)
        g2 = QGroupBox(tr("Musica di sottofondo"))
        f2 = QFormLayout(g2)
        mrow = QHBoxLayout()
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.addWidget(self.ed_music)
        for text, folder in ((tr("File…"), False), (tr("Cartella…"), True)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, folder=folder: self._pick_music(folder))
            mrow.addWidget(b)
        mw = QWidget()
        mw.setLayout(mrow)
        f2.addRow(tr("Musica:"), mw)
        f2.addRow("", self.ck_music_shuffle)
        f2.addRow(tr("Volume:"), self.sl_volume)
        f2.addRow(QLabel(tr("Si ferma con la pausa; Ctrl+M la accende e la spegne durante lo slideshow.")))
        self.ck_double = QCheckBox(tr("Con 2 affiancate, le pagine doppie (immagini orizzontali) si mostrano da sole"))
        self.ck_resume = QCheckBox(tr("Archivi di fumetti: riprendi dall'ultima pagina letta"))
        self.ck_videos = QCheckBox(tr("Mostra i video nel browser e nello slideshow"))
        self.cb_screen = QComboBox()
        from PySide6.QtGui import QGuiApplication
        self._screens = [("window", tr("Quello della finestra del programma")),
                         ("primary", tr("Schermo principale")), ("secondary", tr("Secondo schermo (se c'è)"))]
        for sc in QGuiApplication.screens():
            g = sc.geometry()
            self._screens.append((sc.name(), f"{sc.name()}  ({g.width()}×{g.height()})"))
        self.cb_screen.addItems([n for _k, n in self._screens])
        g3 = QGroupBox(tr("Altro"))
        f3 = QFormLayout(g3)
        f3.addRow(self.ck_double)
        f3.addRow(self.ck_resume)
        f3.addRow(self.ck_videos)
        f3.addRow(tr("Schermo dello slideshow:"), self.cb_screen)
        return self._page(g1, g2, g3)

    def _tab_viewer(self):
        self.ck_quick = QCheckBox(tr("Eliminazione rapida senza conferma (annullabile con Ctrl+Z)"))
        self.ck_vaudio = QCheckBox(tr("Audio dei video attivo (tasto A per cambiare al volo)"))
        self.sp_loupe = QDoubleSpinBox(minimum=1.5, maximum=16, singleStep=0.5, decimals=1)
        self.sp_loupe.setPrefix("× ")
        g = QGroupBox(tr("Visualizzatore"))
        f = QFormLayout(g)
        f.addRow(self.ck_quick)
        f.addRow(self.ck_vaudio)
        f.addRow(tr("Ingrandimento della lente:"), self.sp_loupe)
        return self._page(g)

    def _tab_anim(self, gpu, gpudecode):
        self.ck_anim_play = QCheckBox(tr("Animazione di file GIF e WebP in modalità Slideshow "
                                         "(con presentazione in pausa)"))
        self.ck_anim_play.setToolTip(tr("Mentre la presentazione scorre si vede sempre il primo "
                                        "fotogramma. Nel visualizzatore le animazioni partono comunque."))
        self.ck_anim_pair = QCheckBox(tr("Animazione di file GIF e WebP in modalità Slideshow con due "
                                         "immagini affiancate (con presentazione in pausa)"))
        self.ck_anim_pair.setToolTip(tr("Spento: con 2 affiancate le immagini restano ferme sul "
                                        "primo fotogramma."))
        self.ck_anim_thumbs = QCheckBox(tr("Animazione della miniatura del file GIF/WebP selezionato "
                                           "nel browser"))
        self.cb_render = QComboBox()
        self.cb_render.addItems(gpu.mode_names())
        self.lb_gpu = QLabel(gpu.description())
        self.lb_gpu.setWordWrap(True)
        self.lb_gpu.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ck_nvjpeg = QCheckBox(tr("Decodifica i JPEG grandi con la GPU NVIDIA (nvImageCodec / nvJPEG)"))
        self.lb_nv = QLabel(gpudecode.status())
        self.lb_nv.setWordWrap(True)
        self.lb_nv.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if not gpudecode.available():
            self.ck_nvjpeg.setEnabled(False)
        from . import nvsupport
        self.lb_nvsup = QLabel(nvsupport.describe())
        self.lb_nvsup.setWordWrap(True)
        self.b_nv_install = QPushButton()
        self.b_nv_install.clicked.connect(self._nv_install)
        self.b_nv_remove = QPushButton(tr("Rimuovi"))
        self.b_nv_remove.clicked.connect(self._nv_remove)
        nvrow = QHBoxLayout()
        nvrow.setContentsMargins(0, 0, 0, 0)
        nvrow.addWidget(self.b_nv_install)
        nvrow.addWidget(self.b_nv_remove)
        nvrow.addStretch()
        nvw = QWidget()
        nvw.setLayout(nvrow)
        self._nv_widgets = (self.lb_nvsup, nvw)
        self._nv_refresh()
        g = QGroupBox(tr("Animazioni e accelerazione GPU"))
        f = QFormLayout(g)
        f.addRow(self.ck_anim_play)
        f.addRow(self.ck_anim_pair)
        f.addRow(_spacer())
        f.addRow(self.ck_anim_thumbs)
        f.addRow(_spacer())
        f.addRow(tr("Disegno immagini:"), self.cb_render)
        f.addRow("", self.lb_gpu)
        f.addRow(_spacer())
        f.addRow(QLabel("<b>" + tr("Supporto GPU NVIDIA") + "</b>"))
        f.addRow(self.lb_nvsup)
        f.addRow(nvw)
        f.addRow(self.ck_nvjpeg)
        f.addRow("", self.lb_nv)
        return self._page(g)

    def _tab_sort(self):
        g = QGroupBox(tr("Cartelle di destinazione (tasti 1-9 nel visualizzatore e nello slideshow)"))
        grid = QGridLayout(g)
        self.sort_edits = []
        for i in range(1, 10):
            ed = QLineEdit(self.settings.value(f"sort/target{i}", ""))
            ed.setPlaceholderText(tr("nessuna"))
            grid.addWidget(QLabel(f"<b>{i}</b>"), i, 0)
            grid.addWidget(self._path_row(ed, tr("Cartella per il tasto {i}", i=i)), i, 1)
            self.sort_edits.append(ed)
        self.cb_sort_mode = QComboBox()
        self.cb_sort_mode.addItems([tr("Sposta il file"), tr("Copia il file")])
        self.cb_sort_mode.setCurrentIndex(1 if self.settings.value("sort/mode", "move") == "copy" else 0)
        self.ck_advance = QCheckBox(tr("Dopo la copia passa all'immagine successiva"))
        g2 = QGroupBox(tr("Comportamento"))
        f = QFormLayout(g2)
        f.addRow(tr("Premendo il tasto:"), self.cb_sort_mode)
        f.addRow(self.ck_advance)
        f.addRow(QLabel(tr("Ctrl+Z annulla l'ultimo smistamento. Le immagini dentro gli archivi "
                           "vengono sempre copiate.")))
        return self._page(g, g2)

    def _tab_screensaver(self):
        self.ck_ss = QCheckBox(tr("Avvia uno slideshow casuale dopo un periodo di inattività"))
        self.sp_ss_min = QSpinBox(minimum=1, maximum=240)
        self.sp_ss_min.setSuffix(" " + tr("minuti"))
        self.ed_ss = QLineEdit()
        self.ck_ss_sub = QCheckBox(tr("Includi sottocartelle"))
        self.sp_ss_int = QDoubleSpinBox(minimum=1, maximum=600, singleStep=1, decimals=1)
        self.sp_ss_int.setSuffix(" s")
        g = QGroupBox(tr("Salvaschermo"))
        f = QFormLayout(g)
        f.addRow(self.ck_ss)
        f.addRow(tr("Dopo:"), self.sp_ss_min)
        f.addRow(tr("Cartella:"), self._path_row(self.ed_ss, tr("Cartella del salvaschermo")))
        f.addRow("", self.ck_ss_sub)
        f.addRow(tr("Intervallo:"), self.sp_ss_int)
        f.addRow(QLabel(tr("Funziona mentre il programma è aperto (anche ridotto a icona). "
                           "Si chiude muovendo il mouse o premendo un tasto.")))
        return self._page(g)

    def _tab_formats(self):
        from . import archive, codecs
        g = QGroupBox(tr("Formati disponibili"))
        v = QVBoxLayout(g)
        lines = codecs.status_lines()
        t = archive.tools_status()
        lines.append("ZIP / CBZ: ✓")
        lines.append("7Z / CB7: " + ("✓ py7zr" if t["py7zr"] else ("✓ 7-Zip" if t["7zip"] else "—")))
        lines.append("RAR / CBR: " + ("✓ 7-Zip" if t["7zip"] else ("✓ UnRAR" if t["unrar"] and t["rarfile"] else
                                                                  tr("— serve 7-Zip (consigliato) o UnRAR"))))
        lab = QLabel("<br>".join(lines))
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(lab)
        v.addWidget(QLabel(tr("Scrittura (conversione e salvataggio): ") +
                           ", ".join(n for n, _k, _e in codecs.write_formats())))
        hint = QLabel(tr("Per HEIC, AVIF e JPEG XL: pip install pillow-heif pillow-jxl-plugin\n"
                         "Per i RAW: pip install rawpy · Per CBR/RAR installa 7-Zip (www.7-zip.org)"))
        hint.setStyleSheet("color: gray")
        v.addWidget(hint)
        return self._page(g)

    # ------------------------------------------------------------- valori
    def _fill(self):
        s = self.s
        self.ck_folder.setChecked(s["osd/folder"])
        self.ck_msgs.setChecked(s["osd/messages"])
        self.ck_badge.setChecked(s["osd/pause_badge"])
        self.ck_controls.setChecked(s["viewer/controls"])
        keys = POSITION_KEYS
        self.cb_pos.setCurrentIndex(keys.index(s["osd/folder_pos"]) if s["osd/folder_pos"] in keys else 0)
        self.sp_ms.setValue(int(s["osd/folder_ms"]))
        for w, k in ((self.sl_alpha, "osd/bg_alpha"), (self.sp_size, "osd/size")):
            w.blockSignals(True)
            w.setValue(int(s[k]))
            w.blockSignals(False)
        from .canvas import TRANSITIONS
        self.cb_trans.setCurrentIndex(TRANSITIONS.index(s["slideshow/transition"])
                                      if s["slideshow/transition"] in TRANSITIONS else 1)
        self.sp_trans.setValue(int(s["slideshow/transition_ms"]))
        self.sp_kb.setValue(int(s["slideshow/kenburns_zoom"]))
        self.ed_music.setText(s["slideshow/music"])
        self.ck_music_shuffle.setChecked(s["slideshow/music_shuffle"])
        self.sl_volume.setValue(int(s["slideshow/music_volume"]))
        self.ck_double.setChecked(s["slideshow/double_pages"])
        self.ck_resume.setChecked(s["comics/resume"])
        self.ck_videos.setChecked(s["slideshow/videos"])
        keys = [k for k, _n in self._screens]
        self.cb_screen.setCurrentIndex(keys.index(s["slideshow/screen"]) if s["slideshow/screen"] in keys else 0)
        self.ck_quick.setChecked(s["viewer/quick_delete"])
        self.ck_vaudio.setChecked(s["viewer/video_audio"])
        self.sp_loupe.setValue(float(s["viewer/loupe_mag"]))
        self.ck_anim_play.setChecked(s["viewer/animate_slideshow"])
        self.ck_anim_pair.setChecked(s["viewer/animate_pair"])
        self.ck_anim_thumbs.setChecked(s["browser/animate_thumbs"])
        from .gpu import MODES
        self.cb_render.setCurrentIndex(MODES.index(s["gpu/render"]) if s["gpu/render"] in MODES else 0)
        self.ck_nvjpeg.setChecked(s["gpu/nvjpeg"] and self.ck_nvjpeg.isEnabled())
        self.ck_advance.setChecked(s["sort/advance"])
        self.ck_ss.setChecked(s["screensaver/enabled"])
        self.sp_ss_min.setValue(int(s["screensaver/minutes"]))
        self.ed_ss.setText(s["screensaver/folder"])
        self.ck_ss_sub.setChecked(s["screensaver/subfolders"])
        self.sp_ss_int.setValue(float(s["screensaver/interval"]))
        self._sync()

    def _sync(self, *_):
        self.s["osd/bg_alpha"] = self.sl_alpha.value()
        self.s["osd/size"] = self.sp_size.value()
        for b, k in ((self.b_color, "osd/color"), (self.b_bg, "osd/bg")):
            c = QColor(self.s[k])
            fg = "#000" if c.lightness() > 128 else "#fff"
            b.setText(c.name())
            b.setStyleSheet(f"background:{c.name()}; color:{fg}; padding:4px 16px;")
        self.preview.style_ = self.s
        self.preview.update()

    def _pick(self, key, title):
        c = QColorDialog.getColor(QColor(self.s[key]), self, title)
        if c.isValid():
            self.s[key] = c.name()
            self._sync()

    def _pick_music(self, folder):
        if folder:
            d = QFileDialog.getExistingDirectory(self, tr("Cartella della musica"), self.ed_music.text())
        else:
            d, _f = QFileDialog.getOpenFileName(self, tr("File musicale"), self.ed_music.text(),
                                                tr("Audio") + " (*.mp3 *.ogg *.flac *.wav *.m4a *.aac *.opus *.wma)")
        if d:
            self.ed_music.setText(d)

    def _preset(self, fg, bg, a):
        self.s["osd/color"], self.s["osd/bg"] = fg, bg
        self.sl_alpha.setValue(a)
        self._sync()

    def _defaults(self):
        self.s = dict(DEFAULTS)
        self._fill()

    def _nv_refresh(self):
        from . import gpudecode, nvsupport
        ok = nvsupport.supported()
        has = nvsupport.info() is not None
        self.b_nv_install.setText(tr("Reinstalla") if has else tr("Installa"))
        self.b_nv_install.setEnabled(ok)
        self.b_nv_install.setToolTip(tr("Scarica da PyPI le librerie NVIDIA ufficiali (circa 25 MB)"))
        self.b_nv_remove.setEnabled(ok and has)
        self.lb_nvsup.setText(nvsupport.describe())
        if hasattr(self, "lb_nv"):
            self.lb_nv.setText(gpudecode.status())
            self.ck_nvjpeg.setEnabled(gpudecode.available())

    def _nv_install(self):
        from . import nvsupport
        if not nvsupport.driver_present():
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(self, self.windowTitle(),
                                     tr("Non ho trovato il driver NVIDIA: senza, le librerie non funzionano.\n\n"
                                        "Scaricarle lo stesso?"))
            if r != QMessageBox.StandardButton.Yes:
                return
        if install_nvidia(self, self.settings):
            self.ck_nvjpeg.setChecked(self.ck_nvjpeg.isEnabled())
        self._nv_refresh()

    def _nv_remove(self):
        from . import gpudecode, nvsupport
        nvsupport.uninstall()
        gpudecode.set_enabled(False)
        self.ck_nvjpeg.setChecked(False)
        self._nv_refresh()
        if nvsupport.activated_folder():
            self.lb_nv.setText(tr("Rimosse: smetteranno di essere usate al prossimo avvio."))

    def _keys(self):
        from .shortcuts import ShortcutsDialog
        self.keys_changed = ShortcutsDialog(self.settings, self).run() or getattr(self, "keys_changed", False)

    def run(self):
        if self.exec() != QDialog.DialogCode.Accepted:
            return getattr(self, "keys_changed", False)
        s = self.s
        s["osd/folder"] = self.ck_folder.isChecked()
        s["osd/messages"] = self.ck_msgs.isChecked()
        s["osd/pause_badge"] = self.ck_badge.isChecked()
        s["viewer/controls"] = self.ck_controls.isChecked()
        s["osd/folder_pos"] = POSITION_KEYS[self.cb_pos.currentIndex()]
        s["osd/folder_ms"] = self.sp_ms.value()
        from .canvas import TRANSITIONS
        s["slideshow/transition"] = TRANSITIONS[self.cb_trans.currentIndex()]
        s["slideshow/transition_ms"] = self.sp_trans.value()
        s["slideshow/kenburns_zoom"] = self.sp_kb.value()
        s["slideshow/music"] = self.ed_music.text().strip()
        s["slideshow/music_shuffle"] = self.ck_music_shuffle.isChecked()
        s["slideshow/music_volume"] = self.sl_volume.value()
        s["slideshow/double_pages"] = self.ck_double.isChecked()
        s["comics/resume"] = self.ck_resume.isChecked()
        s["slideshow/videos"] = self.ck_videos.isChecked()
        s["slideshow/screen"] = self._screens[self.cb_screen.currentIndex()][0]
        s["viewer/quick_delete"] = self.ck_quick.isChecked()
        s["viewer/video_audio"] = self.ck_vaudio.isChecked()
        s["viewer/loupe_mag"] = self.sp_loupe.value()
        s["viewer/animate_slideshow"] = self.ck_anim_play.isChecked()
        s["viewer/animate_pair"] = self.ck_anim_pair.isChecked()
        s["browser/animate_thumbs"] = self.ck_anim_thumbs.isChecked()
        from . import gpu, gpudecode, utils
        s["gpu/render"] = gpu.MODES[self.cb_render.currentIndex()]
        if self.ck_nvjpeg.isEnabled():
            s["gpu/nvjpeg"] = self.ck_nvjpeg.isChecked()
        gpudecode.set_enabled(s["gpu/nvjpeg"])
        utils.SHOW_VIDEOS = s["slideshow/videos"]
        s["sort/advance"] = self.ck_advance.isChecked()
        s["screensaver/enabled"] = self.ck_ss.isChecked()
        s["screensaver/minutes"] = self.sp_ss_min.value()
        s["screensaver/folder"] = self.ed_ss.text().strip()
        s["screensaver/subfolders"] = self.ck_ss_sub.isChecked()
        s["screensaver/interval"] = self.sp_ss_int.value()
        for i, ed in enumerate(self.sort_edits, 1):
            self.settings.setValue(f"sort/target{i}", ed.text().strip())
        self.settings.setValue("sort/mode", "copy" if self.cb_sort_mode.currentIndex() == 1 else "move")
        self.restart_needed = s["gpu/render"] != self._render_at_start
        for k, v in s.items():
            self.settings.setValue(k, v)
        if self.restart_needed:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, self.windowTitle(),
                                    tr("Il nuovo metodo di disegno delle immagini verrà usato "
                                       "al prossimo avvio del programma."))
        return True


def install_nvidia(parent, settings):
    """Scarica e attiva il supporto NVIDIA, con barra di avanzamento e messaggi.
    Ritorna True se ora la decodifica su GPU funziona."""
    from PySide6.QtWidgets import QMessageBox
    from . import APP_NAME, gpudecode, nvsupport
    from .worker import run_with_progress
    reinstall = nvsupport.activated_folder() is not None
    try:
        res = run_with_progress(parent, tr("Supporto GPU NVIDIA"), nvsupport.install)
    except Exception as e:  # noqa: BLE001 - rete assente, PyPI non raggiungibile...
        QMessageBox.warning(parent, APP_NAME, tr("Scaricamento non riuscito:\n{err}", err=e))
        return False
    if res is None:
        return False
    if reinstall:
        QMessageBox.information(parent, APP_NAME, tr("Librerie NVIDIA aggiornate: verranno usate al prossimo avvio."))
        return False
    gpudecode.reset()
    if gpudecode.available():
        gpudecode.set_enabled(True)
        settings.setValue("gpu/nvjpeg", True)
        QMessageBox.information(parent, APP_NAME, tr("Fatto: i JPEG grandi ora vengono decodificati dalla scheda NVIDIA."))
        return True
    QMessageBox.warning(parent, APP_NAME, tr("Librerie scaricate, ma la scheda NVIDIA non le ha accettate:\n{err}\n\n"
                                             "Controlla di avere un driver NVIDIA recente.", err=gpudecode.status()))
    return False
