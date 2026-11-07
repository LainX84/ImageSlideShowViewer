"""Opzioni del visualizzatore: avvisi a schermo, colori, barra dei comandi."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QPushButton, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

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


class OptionsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Opzioni visualizzatore e slideshow"))
        self.settings = settings
        self.s = load_style(settings)

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

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel |
                              QDialogButtonBox.StandardButton.RestoreDefaults)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText(tr("Predefiniti"))
        bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self._defaults)
        lay = QVBoxLayout(self)
        for g in (g1, g2, g3):
            lay.addWidget(g)
        lay.addWidget(bb)

        self.b_color.clicked.connect(lambda: self._pick("osd/color", tr("Colore del testo")))
        self.b_bg.clicked.connect(lambda: self._pick("osd/bg", tr("Colore dello sfondo")))
        for w in (self.sl_alpha, self.sp_size):
            w.valueChanged.connect(self._sync)
        self._fill()

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

    def _preset(self, fg, bg, a):
        self.s["osd/color"], self.s["osd/bg"] = fg, bg
        self.sl_alpha.setValue(a)
        self._sync()

    def _defaults(self):
        self.s = dict(DEFAULTS)
        self._fill()

    def run(self):
        if self.exec() != QDialog.DialogCode.Accepted:
            return False
        s = self.s
        s["osd/folder"] = self.ck_folder.isChecked()
        s["osd/messages"] = self.ck_msgs.isChecked()
        s["osd/pause_badge"] = self.ck_badge.isChecked()
        s["viewer/controls"] = self.ck_controls.isChecked()
        s["osd/folder_pos"] = POSITION_KEYS[self.cb_pos.currentIndex()]
        s["osd/folder_ms"] = self.sp_ms.value()
        for k, v in s.items():
            self.settings.setValue(k, v)
        return True
