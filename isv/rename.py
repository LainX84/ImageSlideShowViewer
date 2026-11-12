"""Motore della rinomina in blocco, sulla falsariga di ACDSee.

Una rinomina è un elenco di operazioni applicate in ordine al nome di ogni file:

    template   modello con * (nome originale), # (contatore) e campi {nome}, {data}…
    replace    cerca e sostituisci (anche con espressioni regolari)
    case       maiuscole / minuscole per nome ed estensione
    insert     inserisce testo all'inizio, alla fine, in una posizione, prima/dopo un testo
    remove     toglie caratteri da una posizione o da un delimitatore fino a un altro punto
    spaces     elimina, accorcia o sostituisce gli spazi

Ogni operazione è un dizionario (salvabile in JSON); il modulo non usa Qt, così si
può provare da solo.
"""
import os
import re
import time

OP_TYPES = ["template", "replace", "case", "insert", "remove", "spaces"]

DEFAULTS = {
    "template": {"template": "*", "seq": "numbers", "start_mode": "fixed", "start": 1},
    "replace": {"search": "", "replace": "", "case": False, "ext": False, "regex": False},
    "case": {"name": "keep", "ext": "keep"},
    "insert": {"text": "", "where": "prefix", "pos": 0, "anchor": "", "rtl": False,
               "overwrite": False, "ext": False, "case": False},
    "remove": {"start_mode": "position", "start_pos": 0, "start_delim": "",
               "until_mode": "count", "count": 1, "until_delim": "",
               "rtl": False, "remove_delims": False, "ext": False, "case": False},
    "spaces": {"mode": "all", "with": "_"},
}

INVALID_CHARS = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}

# campi del modello: alias italiano e inglese
FIELDS = {
    "name": ("nome", "name"),
    "folder": ("cartella", "folder"),
    "date": ("data", "date"),
    "time": ("ora", "time"),
    "year": ("anno", "year"),
    "month": ("mese", "month"),
    "day": ("giorno", "day"),
    "width": ("larghezza", "width"),
    "height": ("altezza", "height"),
}
_ALIAS = {a: k for k, al in FIELDS.items() for a in al}
_FIELD_RE = re.compile(r"\{(\w+)\}")


def new_op(kind, on=True):
    d = {"type": kind, "on": on}
    d.update(DEFAULTS[kind])
    return d


def normalize(op):
    """Completa un'operazione caricata dalle impostazioni con i valori mancanti."""
    kind = op.get("type")
    if kind not in DEFAULTS:
        return None
    d = new_op(kind, bool(op.get("on", True)))
    for k, v in op.items():
        if k in d and type(v) is type(d[k]):
            d[k] = v
    return d


# ------------------------------------------------------------------ supporto
class FileInfo:
    """Dati del file usati dai campi {data}, {larghezza}… (calcolati solo se servono)."""

    def __init__(self, path):
        self.path = path
        self._mt = None
        self._size = None

    def mtime(self):
        if self._mt is None:
            try:
                self._mt = time.localtime(os.path.getmtime(self.path))
            except OSError:
                self._mt = time.localtime()
        return self._mt

    def image_size(self):
        if self._size is None:
            self._size = ("", "")
            try:
                from PySide6.QtGui import QImageReader
                r = QImageReader(self.path)
                r.setAutoTransform(True)
                s = r.size()
                if s.isValid():
                    if r.transformation().value & 4:   # ruotata di 90°: si scambiano i lati
                        s.transpose()
                    self._size = (str(s.width()), str(s.height()))
            except Exception:  # noqa: BLE001
                pass
        return self._size


def expand_fields(text, info, stem):
    def sub(m):
        key = _ALIAS.get(m.group(1).lower())
        if key is None:
            return m.group(0)
        if key == "name":
            return stem
        if key == "folder":
            return os.path.basename(os.path.dirname(info.path))
        if key in ("width", "height"):
            return info.image_size()[0 if key == "width" else 1]
        fmt = {"date": "%Y-%m-%d", "time": "%H%M%S", "year": "%Y", "month": "%m", "day": "%d"}[key]
        return time.strftime(fmt, info.mtime())
    return _FIELD_RE.sub(sub, text)


def letters(n, width):
    """1 -> a, 26 -> z, 27 -> ba (con larghezza 2: aa, ab, …)."""
    n = max(0, n - 1)
    out = ""
    while True:
        out = chr(ord("a") + n % 26) + out
        n //= 26
        if n == 0:
            break
    return out.rjust(width, "a")


def _find(s, needle, case, last=False):
    if not needle:
        return -1
    if not case:
        s, needle = s.lower(), needle.lower()
    return s.rfind(needle) if last else s.find(needle)


def title_case(s):
    return re.sub(r"[^\W_]+", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), s)


# ------------------------------------------------------------- operazioni
def _template(op, stem, info, n):
    t = op["template"]
    if not t:
        return stem

    def seq(m):
        w = len(m.group())
        return letters(n, w) if op["seq"] == "letters" else str(n).zfill(w)
    # i campi vanno espansi prima di # e *, che potrebbero comparire nel nome originale
    parts = re.split(r"(\*|#+)", expand_fields(t, info, stem))
    out = []
    for p in parts:
        if p == "*":
            out.append(stem)
        elif p and p[0] == "#":
            out.append(seq(re.match(r"#+", p)))
        else:
            out.append(p)
    return "".join(out)


def _replace(op, s):
    if not op["search"]:
        return s
    flags = 0 if op["case"] else re.IGNORECASE
    if op["regex"]:
        try:
            return re.sub(op["search"], op["replace"], s, flags=flags)
        except (re.error, IndexError):
            return s
    return re.sub(re.escape(op["search"]), lambda m: op["replace"], s, flags=flags)


def _insert(op, s, info, stem):
    t = expand_fields(op["text"], info, stem)
    if not t:
        return s
    w = op["where"]
    if w == "prefix":
        i = 0
    elif w == "suffix":
        i = len(s)
    elif w == "position":
        p = max(0, min(int(op["pos"]), len(s)))
        i = len(s) - p if op["rtl"] else p
    else:
        f = _find(s, op["anchor"], op["case"], last=op["rtl"])
        if f < 0:
            return s
        i = f + len(op["anchor"]) if w == "after" else f
    if op["overwrite"]:
        if w == "suffix" or (w == "position" and op["rtl"]):
            # si sovrascrivono i caratteri a sinistra del punto di inserimento
            return s[:max(0, i - len(t))] + t + s[i:]
        return s[:i] + t + s[i + len(t):]
    return s[:i] + t + s[i:]


def _remove(op, s):
    rtl = op["rtl"]
    d1, d2 = op["start_delim"], op["until_delim"]
    if rtl:   # da destra: si lavora sul testo rovesciato
        s, d1, d2 = s[::-1], d1[::-1], d2[::-1]
    rd = op["remove_delims"]
    if op["start_mode"] == "position":
        st = min(max(0, int(op["start_pos"])), len(s))
        search_from = st
    else:
        i = _find(s, d1, op["case"])
        if i < 0:
            return s[::-1] if rtl else s
        st = i if rd else i + len(d1)
        search_from = i + len(d1)
    um = op["until_mode"]
    if um == "count":
        en = min(len(s), st + max(0, int(op["count"])))
    elif um == "delimiter":
        j = _find(s[search_from:], d2, op["case"])
        if j < 0:
            return s[::-1] if rtl else s
        j += search_from
        en = j + len(d2) if rd else j
    else:
        en = len(s)
    out = s[:st] + s[max(st, en):]
    return out[::-1] if rtl else out


def _spaces(op, s):
    m = op["mode"]
    if m == "all":
        return s.replace(" ", "")
    if m == "trim":
        return s.strip(" ")
    if m == "collapse":
        return re.sub(r" {2,}", " ", s)
    return s.replace(" ", op["with"])


def new_name(fname, ops, info, n):
    """Nome nuovo (nome + estensione) del file `fname`; n = numero del contatore."""
    stem, ext = os.path.splitext(fname)
    orig_stem = stem
    for op in ops:
        if not op.get("on", True):
            continue
        k = op["type"]
        if k == "template":
            stem = _template(op, stem, info, n)
            continue
        if k == "case":
            if op["name"] == "lower":
                stem = stem.lower()
            elif op["name"] == "upper":
                stem = stem.upper()
            elif op["name"] == "title":
                stem = title_case(stem)
            elif op["name"] == "sentence":
                stem = stem[:1].upper() + stem[1:].lower()
            if op["ext"] == "lower":
                ext = ext.lower()
            elif op["ext"] == "upper":
                ext = ext.upper()
            continue
        whole = op.get("ext", False)
        s = stem + ext if whole else stem
        if k == "replace":
            s = _replace(op, s)
        elif k == "insert":
            s = _insert(op, s, info, orig_stem)
        elif k == "remove":
            s = _remove(op, s)
        elif k == "spaces":
            s = _spaces(op, s)
        if whole:
            stem, ext = os.path.splitext(s)
            if not stem and ext:          # ".jpg" senza nome: tutto è nome
                stem, ext = ext, ""
        else:
            stem = s
    return stem + ext


# ------------------------------------------------------------- contatore
def _template_regex(t):
    out, group = [], False
    for p in re.split(r"(\*|#+|\{\w+\})", t):
        if not p:
            continue
        if p == "*" or p.startswith("{"):
            out.append(".*?")
        elif p[0] == "#":
            out.append(r"(\d+)" if not group else r"\d+")
            group = True
        else:
            out.append(re.escape(p))
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE) if group else None


def auto_start(paths, op):
    """Continua una numerazione già presente: Foto_001…Foto_012 -> si parte da 13."""
    if op["seq"] == "letters":
        return int(op["start"])
    rx = _template_regex(op["template"])
    if rx is None:
        return int(op["start"])
    mine = {os.path.normcase(p) for p in paths}
    best = 0
    for folder in {os.path.dirname(p) for p in paths}:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for nm in names:
            if os.path.normcase(os.path.join(folder, nm)) in mine:
                continue
            m = rx.match(os.path.splitext(nm)[0])
            if m:
                best = max(best, int(m.group(1)))
    return best + 1 if best else int(op["start"])


# ------------------------------------------------------------- piano completo
OK, SAME, INVALID, CONFLICT, SKIP_CONFLICT, SKIP_EXT, NUMBERED = (
    "ok", "same", "invalid", "conflict", "skip_conflict", "skip_ext", "numbered")


def invalid_reason(name):
    stem = os.path.splitext(name)[0]
    if not name.strip() or not stem.strip(" ."):
        return "empty"
    if any(c in INVALID_CHARS for c in name):
        return "chars"
    if name[-1] in " .":
        return "end"
    if stem.split(".")[0].lower() in RESERVED:
        return "reserved"
    if len(name) > 255:
        return "long"
    return None


def _key(path):
    """Confronto dei nomi come fa Windows: senza distinguere maiuscole e minuscole."""
    return os.path.normcase(path).casefold()


def plan(paths, ops, conflicts="block", ext_change="allow"):
    """Calcola i nuovi nomi.

    Ritorna (righe, bloccato) dove ogni riga è (vecchio, nuovo, stato, dettaglio).
    conflicts: "block" (non rinominare nulla), "skip" (salta quei file), "number" (aggiungi (2), (3)…)
    ext_change: "allow" oppure "skip" (salta i file la cui estensione cambierebbe)
    """
    ops = [o for o in ops if o.get("on", True)]
    start = {}
    for i, op in enumerate(ops):
        if op["type"] == "template":
            start[i] = auto_start(paths, op) if op["start_mode"] == "auto" else int(op["start"])
    rows = []
    for idx, p in enumerate(paths):
        folder, fname = os.path.split(p)
        info = FileInfo(p)
        # ogni modello ha il suo numero iniziale
        cur = fname
        for i, op in enumerate(ops):
            n = start.get(i, 1) + idx
            cur = new_name(cur, [op], info, n)
        rows.append([p, os.path.join(folder, cur), OK, None])

    # nomi non validi, nessun cambiamento, estensione cambiata
    for r in rows:
        old, new = r[0], r[1]
        why = invalid_reason(os.path.basename(new))
        if why:
            r[2], r[3] = INVALID, why
        elif old == new:
            r[2] = SAME
        elif ext_change == "skip" and \
                os.path.splitext(old)[1].lower() != os.path.splitext(new)[1].lower():
            r[2], r[1] = SKIP_EXT, old

    # file già presenti nelle cartelle (esclusi quelli che vengono rinominati)
    mine = {_key(r[0]) for r in rows}
    existing = {}

    def taken_on_disk(path):
        folder = os.path.dirname(path)
        if folder not in existing:
            try:
                existing[folder] = {_key(os.path.join(folder, n)) for n in os.listdir(folder)} - mine
            except OSError:
                existing[folder] = set()
        return _key(path) in existing[folder]

    def final(r):
        return r[0] if r[2] in (INVALID, SKIP_CONFLICT, SKIP_EXT) else r[1]

    def fixed_names():
        return {_key(final(r)) for r in rows if r[2] != OK}

    if conflicts == "number":
        taken = fixed_names()
        for r in rows:
            if r[2] != OK:
                continue
            new = r[1]
            if _key(new) in taken or taken_on_disk(new):
                base, ext = os.path.splitext(new)
                k = 2
                while _key(f"{base} ({k}){ext}") in taken or taken_on_disk(f"{base} ({k}){ext}"):
                    k += 1
                r[1], r[2] = f"{base} ({k}){ext}", NUMBERED
            taken.add(_key(r[1]))
    elif conflicts == "skip":
        # il primo file prende il nome, quelli dopo vengono saltati; si ripete finché
        # anche i nomi rimasti invariati non entrano più in conflitto
        while True:
            taken = fixed_names()
            for r in rows:
                if r[2] != OK:
                    continue
                k = _key(r[1])
                if k in taken or taken_on_disk(r[1]):
                    r[2] = SKIP_CONFLICT
                    break
                taken.add(k)
            else:
                break
    else:
        counts = {}
        for r in rows:
            k = _key(final(r))
            counts[k] = counts.get(k, 0) + 1
        for r in rows:
            if r[2] == OK and (counts[_key(r[1])] > 1 or taken_on_disk(r[1])):
                r[2] = CONFLICT
    blocked = conflicts == "block" and any(r[2] in (INVALID, CONFLICT) for r in rows)
    return [tuple(r) for r in rows], blocked


def _library_moved(old, new):
    """Valutazioni e raccolte seguono il file (se l'interfaccia è disponibile)."""
    try:
        from . import library
        library.move_path(old, new)
    except Exception:  # noqa: BLE001 - usato anche senza Qt (prove)
        pass


def apply_renames(pairs, tag="isvtmp"):
    """Rinomina in due passaggi (evita collisioni tipo 1→2, 2→3). Ritorna (fatti, errori)."""
    todo = [(o, n) for o, n in pairs if o != n]
    temps, errors = [], []
    for i, (o, n) in enumerate(todo):
        tmp = f"{o}.{tag}{i}"
        try:
            os.rename(o, tmp)
            temps.append((tmp, o, n))
        except OSError as e:
            errors.append(f"{os.path.basename(o)}: {e.strerror or e}")
    done = 0
    for tmp, o, n in temps:
        try:
            os.rename(tmp, n)
            done += 1
            _library_moved(o, n)
        except OSError as e:
            errors.append(f"{os.path.basename(o)}: {e.strerror or e}")
            try:
                os.rename(tmp, o)
            except OSError:
                pass
    return done, errors
