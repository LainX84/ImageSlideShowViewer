"""Traduzioni dell'interfaccia (italiano / inglese).

I testi nel codice sono scritti in italiano e passano da tr(); in inglese vengono
sostituiti con le voci di lang_en.EN. Per aggiungere una lingua basta creare un
dizionario analogo e registrarlo in LANGUAGES.
"""
from PySide6.QtCore import QLocale

from .lang_en import EN

# codice -> (nome mostrato, dizionario; None = testi originali in italiano)
LANGUAGES = {
    "it": ("Italiano", None),
    "en": ("English", EN),
}

_lang = "it"
_table = None


def system_language():
    name = QLocale.system().name().lower()
    return "it" if name.startswith("it") else "en"


def init(settings):
    """Legge la lingua scelta ("auto" = quella di Windows) e la attiva."""
    choice = settings.value("app/language", "auto")
    set_language(system_language() if choice not in LANGUAGES else choice)


def set_language(code):
    global _lang, _table
    _lang = code if code in LANGUAGES else "en"
    _table = LANGUAGES[_lang][1]


def language():
    return _lang


def tr(text, **kw):
    """Traduce `text` nella lingua attiva; i segnaposto {x} si riempiono con kw."""
    if _table is not None:
        text = _table.get(text, text)
    return text.format(**kw) if kw else text


def num(value, fmt="g"):
    """Numero con il separatore decimale della lingua (4,5 s / 4.5 s)."""
    s = format(value, fmt)
    return s.replace(".", ",") if _lang == "it" else s
