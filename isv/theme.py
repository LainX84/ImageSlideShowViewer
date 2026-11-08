"""Tema dell'interfaccia: chiaro, scuro o automatico (segue l'impostazione di Windows).

Il visualizzatore e lo slideshow restano sempre su fondo nero: il tema riguarda il
browser e le finestre di dialogo.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

THEMES = ("auto", "light", "dark")
_choice = "auto"
_dark = True
_hooked = False


def _palette(win, base, alt, text, button, tip_bg, tip_text, disabled, link):
    p = QPalette()
    C = QPalette.ColorRole
    p.setColor(C.Window, win)
    p.setColor(C.WindowText, text)
    p.setColor(C.Base, base)
    p.setColor(C.AlternateBase, alt)
    p.setColor(C.ToolTipBase, tip_bg)
    p.setColor(C.ToolTipText, tip_text)
    p.setColor(C.PlaceholderText, disabled)
    p.setColor(C.Text, text)
    p.setColor(C.Button, button)
    p.setColor(C.ButtonText, text)
    p.setColor(C.BrightText, QColor(255, 80, 80))
    p.setColor(C.Highlight, QColor(52, 120, 200))
    p.setColor(C.HighlightedText, QColor(255, 255, 255))
    p.setColor(C.Link, link)
    for role in (C.Text, C.ButtonText, C.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled)
    return p


def dark_palette():
    win, text = QColor(42, 42, 45), QColor(225, 225, 225)
    return _palette(win, QColor(30, 30, 32), win, text, win,
                    QColor(55, 55, 58), text, QColor(120, 120, 120), QColor(90, 160, 240))


def light_palette():
    text = QColor(25, 25, 28)
    return _palette(QColor(240, 240, 242), QColor(255, 255, 255), QColor(246, 246, 248), text,
                    QColor(232, 232, 235), QColor(255, 255, 225), text,
                    QColor(150, 150, 150), QColor(20, 100, 200))


def system_is_dark():
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:      # Qt più vecchio di 6.5: si resta sul tema scuro
        return True


def is_dark():
    """True se l'interfaccia è scura in questo momento (per i colori disegnati a mano)."""
    return _dark


def apply(app, choice):
    """Applica il tema scelto ("auto", "light", "dark") all'applicazione, subito."""
    global _choice, _dark, _hooked
    _choice = choice if choice in THEMES else "auto"
    _dark = system_is_dark() if _choice == "auto" else _choice == "dark"
    app.setPalette(dark_palette() if _dark else light_palette())
    if not _hooked:
        try:   # in automatico segue Windows anche mentre il programma è aperto
            QGuiApplication.styleHints().colorSchemeChanged.connect(
                lambda _s: apply(app, _choice) if _choice == "auto" else None)
            _hooked = True
        except AttributeError:
            pass


def init(app, settings):
    apply(app, settings.value("app/theme", "auto"))
