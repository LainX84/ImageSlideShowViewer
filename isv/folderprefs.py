"""Impostazioni dello slideshow ricordate per ogni cartella (o archivio).

Quando uno slideshow su una cartella si chiude, si salvano intervallo, ordine casuale,
ripetizione, sottocartelle, 2 affiancate, manga, ordinamento e transizione usati.
Avviando di nuovo lo slideshow su quella cartella dal menu contestuale di Esplora
risorse si riparte con gli stessi valori.

I dati stanno nelle impostazioni del programma (gruppo "folder_slideshow"), una voce
per cartella con chiave = hash del percorso, così non ci sono problemi con \\ e : nel
registro. Si tengono al massimo MAX_ENTRIES cartelle: le meno recenti si scartano.
"""
import hashlib
import json
import os
import time

GROUP = "folder_slideshow"
MAX_ENTRIES = 500
FIELDS = {          # nome -> tipo
    "interval": float,
    "random": bool,
    "random_folders": bool,
    "loop": bool,
    "subfolders": bool,
    "pair": bool,
    "manga": bool,
    "sort": str,
    "reverse": bool,
    "transition": str,
}


def enabled(settings):
    return settings.value("slideshow/per_folder", True, type=bool)


def normalize(path):
    p = os.path.normcase(os.path.abspath(path))
    if len(p) > 3:          # "c:\" resta com'è
        p = p.rstrip("\\/")
    return p


def _key(path):
    return hashlib.sha1(normalize(path).encode("utf-8", "surrogatepass")).hexdigest()


def _clean(data):
    out = {}
    for name, typ in FIELDS.items():
        if name in data:
            try:
                out[name] = typ(data[name])
            except (TypeError, ValueError):
                pass
    return out


def load(settings, path):
    """Valori salvati per `path`, oppure None."""
    if not path or not enabled(settings):
        return None
    raw = settings.value(f"{GROUP}/{_key(path)}", "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("path") != normalize(path):
        return None
    return _clean(data) or None


def save(settings, path, values):
    if not path or not enabled(settings):
        return
    data = _clean(values)
    if not data:
        return
    data["path"] = normalize(path)
    data["t"] = int(time.time())
    settings.setValue(f"{GROUP}/{_key(path)}", json.dumps(data, ensure_ascii=False))
    _prune(settings)


def forget_all(settings):
    settings.remove(GROUP)


def count(settings):
    settings.beginGroup(GROUP)
    try:
        return len(settings.childKeys())
    finally:
        settings.endGroup()


def _prune(settings):
    settings.beginGroup(GROUP)
    try:
        keys = settings.childKeys()
        if len(keys) <= MAX_ENTRIES:
            return
        stamps = []
        for k in keys:
            try:
                t = int(json.loads(settings.value(k, "")).get("t", 0))
            except (TypeError, ValueError, AttributeError):
                t = 0
            stamps.append((t, k))
        stamps.sort()
        for _t, k in stamps[:len(keys) - MAX_ENTRIES]:
            settings.remove(k)
    finally:
        settings.endGroup()
