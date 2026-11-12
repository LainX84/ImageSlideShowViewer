"""Archivio personale dell'utente: valutazioni (stelle), etichette colorate, raccolte
(Preferiti compresi) e ultima pagina letta di ogni archivio di fumetti.

Tutto sta in un piccolo database SQLite nella cartella dei dati del programma
(Windows: %LOCALAPPDATA%\\LainX84\\ImageSlideShowViewer\\library.sqlite3), quindi
non si toccano le immagini. Rinominando o spostando i file con il programma i dati
li seguono (move_path).
"""
import os
import sqlite3
import threading
import time

from PySide6.QtCore import QStandardPaths

from .archive import SEP, is_virtual

LABELS = [  # (numero, nome, colore)
    (0, "Nessuna", None),
    (1, "Rossa", "#e5484d"),
    (2, "Gialla", "#f5c518"),
    (3, "Verde", "#30a46c"),
    (4, "Blu", "#3e8ed0"),
    (5, "Viola", "#8e4ec6"),
]
FAVORITES = "Preferiti"

_db = None
_lock = threading.RLock()


def label_name(n):
    from .i18n import tr
    return tr(dict((k, v) for k, v, _c in LABELS).get(n, "Nessuna"))


def label_color(n):
    return dict((k, c) for k, _v, c in LABELS).get(n)


def db_path():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    base = base or os.path.expanduser("~/.local/share/ImageSlideShowViewer")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "library.sqlite3")


def key(path):
    """Chiave stabile di un file (maiuscole/minuscole come le tratta il sistema)."""
    if is_virtual(path):
        a, m = path.split(SEP, 1)
        return os.path.normcase(os.path.abspath(a)) + SEP + m
    return os.path.normcase(os.path.abspath(path))


def _conn():
    global _db
    if _db is None:
        _db = sqlite3.connect(db_path(), check_same_thread=False, timeout=10)
        _db.execute("PRAGMA journal_mode=WAL")
        _db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY, path TEXT, rating INTEGER DEFAULT 0, label INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS collections (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, created REAL);
            CREATE TABLE IF NOT EXISTS coll_items (
                coll INTEGER, key TEXT, path TEXT, pos REAL, PRIMARY KEY (coll, key));
            CREATE TABLE IF NOT EXISTS reading (
                archive TEXT PRIMARY KEY, member TEXT, page INTEGER, pages INTEGER, updated REAL);
        """)
        cur = _db.execute("SELECT id FROM collections WHERE name=?", (FAVORITES,))
        if cur.fetchone() is None:
            _db.execute("INSERT INTO collections (name, created) VALUES (?, ?)", (FAVORITES, time.time()))
        _db.commit()
    return _db


def _exec(sql, args=(), commit=True):
    with _lock:
        c = _conn()
        cur = c.execute(sql, args)
        if commit:
            c.commit()
        return cur


# ------------------------------------------------------- stelle ed etichette
def get(path):
    """(stelle 0-5, etichetta 0-5)."""
    with _lock:
        r = _conn().execute("SELECT rating, label FROM meta WHERE key=?", (key(path),)).fetchone()
    return (r[0] or 0, r[1] or 0) if r else (0, 0)


def get_many(paths):
    """{percorso: (stelle, etichetta)} solo per i file che hanno dati."""
    out = {}
    keys = {key(p): p for p in paths}
    ks = list(keys)
    with _lock:
        c = _conn()
        for i in range(0, len(ks), 500):
            chunk = ks[i:i + 500]
            q = "SELECT key, rating, label FROM meta WHERE key IN (%s)" % ",".join("?" * len(chunk))
            for k, r, lb in c.execute(q, chunk):
                if r or lb:
                    out[keys[k]] = (r or 0, lb or 0)
    return out


def _set(path, field, value):
    k = key(path)
    with _lock:
        c = _conn()
        c.execute("INSERT INTO meta (key, path) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET path=excluded.path",
                  (k, path))
        c.execute(f"UPDATE meta SET {field}=? WHERE key=?", (int(value), k))
        c.execute("DELETE FROM meta WHERE key=? AND COALESCE(rating,0)=0 AND COALESCE(label,0)=0", (k,))
        c.commit()


def set_rating(paths, stars):
    for p in paths:
        _set(p, "rating", max(0, min(5, int(stars))))


def set_label(paths, label):
    for p in paths:
        _set(p, "label", max(0, min(5, int(label))))


def all_rated(min_rating=1, label=None):
    """Percorsi con almeno min_rating stelle (e l'etichetta, se data)."""
    q = "SELECT path FROM meta WHERE rating>=?"
    args = [min_rating]
    if label is not None:
        q += " AND label=?"
        args.append(label)
    return [r[0] for r in _exec(q, args, commit=False)]


# ---------------------------------------------------------- file spostati
def move_path(old, new):
    """Dopo una rinomina / uno spostamento fatti dal programma (anche di cartelle)."""
    ko, kn = key(old), key(new)
    with _lock:
        c = _conn()
        for table, kcol, pcol in (("meta", "key", "path"), ("coll_items", "key", "path")):
            c.execute(f"UPDATE OR REPLACE {table} SET {kcol}=?, {pcol}=? WHERE {kcol}=?", (kn, new, ko))
            # contenuto di una cartella (o di un archivio) spostata
            for sep in (os.sep, SEP):
                rows = c.execute(f"SELECT {kcol}, {pcol} FROM {table} WHERE {kcol} LIKE ? ESCAPE '\\'",
                                 (_like(ko + sep) + "%",)).fetchall()
                for k, p in rows:
                    rest = k[len(ko):]
                    prest = p[len(old):] if p and p.lower().startswith(old.lower()) else rest
                    c.execute(f"UPDATE OR REPLACE {table} SET {kcol}=?, {pcol}=? WHERE {kcol}=?",
                              (kn + rest, new + prest, k))
        c.execute("UPDATE OR REPLACE reading SET archive=? WHERE archive=?", (kn, ko))
        c.commit()


def _like(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def forget(paths):
    """File eliminati definitivamente: si tolgono valutazioni e raccolte."""
    with _lock:
        c = _conn()
        for p in paths:
            k = key(p)
            c.execute("DELETE FROM meta WHERE key=?", (k,))
            c.execute("DELETE FROM coll_items WHERE key=?", (k,))
        c.commit()


# ---------------------------------------------------------------- raccolte
def collections():
    """[(id, nome, numero di elementi)] con i Preferiti per primi."""
    rows = _exec("""SELECT c.id, c.name, COUNT(i.key) FROM collections c
                    LEFT JOIN coll_items i ON i.coll=c.id GROUP BY c.id
                    ORDER BY c.name<>?, c.name COLLATE NOCASE""", (FAVORITES,), commit=False).fetchall()
    return rows


def collection_id(name, create=False):
    r = _exec("SELECT id FROM collections WHERE name=?", (name,), commit=False).fetchone()
    if r:
        return r[0]
    if not create:
        return None
    cur = _exec("INSERT INTO collections (name, created) VALUES (?, ?)", (name, time.time()))
    return cur.lastrowid


def favorites_id():
    return collection_id(FAVORITES, create=True)


def collection_name(cid):
    r = _exec("SELECT name FROM collections WHERE id=?", (cid,), commit=False).fetchone()
    return r[0] if r else ""


def display_name(cid):
    from .i18n import tr
    n = collection_name(cid)
    return tr("Preferiti") if n == FAVORITES else n


def rename_collection(cid, name):
    _exec("UPDATE collections SET name=? WHERE id=?", (name, cid))


def delete_collection(cid):
    with _lock:
        c = _conn()
        c.execute("DELETE FROM coll_items WHERE coll=?", (cid,))
        c.execute("DELETE FROM collections WHERE id=?", (cid,))
        c.commit()


def add_to_collection(cid, paths):
    with _lock:
        c = _conn()
        pos = c.execute("SELECT COALESCE(MAX(pos), 0) FROM coll_items WHERE coll=?", (cid,)).fetchone()[0]
        n = 0
        for p in paths:
            pos += 1
            cur = c.execute("INSERT OR IGNORE INTO coll_items (coll, key, path, pos) VALUES (?, ?, ?, ?)",
                            (cid, key(p), p, pos))
            n += cur.rowcount
        c.commit()
    return n


def remove_from_collection(cid, paths):
    with _lock:
        c = _conn()
        for p in paths:
            c.execute("DELETE FROM coll_items WHERE coll=? AND key=?", (cid, key(p)))
        c.commit()


def collection_items(cid):
    """Percorsi della raccolta nell'ordine di inserimento (solo quelli che esistono ancora)."""
    from .archive import stat_any
    out = []
    for (p,) in _exec("SELECT path FROM coll_items WHERE coll=? ORDER BY pos", (cid,), commit=False):
        try:
            stat_any(p)
            out.append(p)
        except OSError:
            pass
    return out


def in_collection(cid, path):
    return _exec("SELECT 1 FROM coll_items WHERE coll=? AND key=?", (cid, key(path)),
                 commit=False).fetchone() is not None


def favorites_among(paths):
    """Insieme dei percorsi (fra quelli dati) che sono nei Preferiti."""
    fid = favorites_id()
    keys = {key(p): p for p in paths}
    out, ks = set(), list(keys)
    with _lock:
        c = _conn()
        for i in range(0, len(ks), 500):
            chunk = ks[i:i + 500]
            q = "SELECT key FROM coll_items WHERE coll=? AND key IN (%s)" % ",".join("?" * len(chunk))
            out |= {keys[k] for (k,) in c.execute(q, [fid] + chunk)}
    return out


def is_favorite(path):
    return in_collection(favorites_id(), path)


def toggle_favorite(paths):
    """Aggiunge ai Preferiti; se c'erano già tutti, li toglie. Ritorna True se aggiunti."""
    fid = favorites_id()
    if paths and all(in_collection(fid, p) for p in paths):
        remove_from_collection(fid, paths)
        return False
    add_to_collection(fid, paths)
    return True


# ------------------------------------------------------- ultima pagina letta
def set_last_page(archive, member, page, pages):
    _exec("INSERT OR REPLACE INTO reading (archive, member, page, pages, updated) VALUES (?, ?, ?, ?, ?)",
          (key(archive), member, page, pages, time.time()))


def last_page(archive):
    """(membro, pagina, pagine) oppure None."""
    r = _exec("SELECT member, page, pages FROM reading WHERE archive=?", (key(archive),),
              commit=False).fetchone()
    return tuple(r) if r else None


def clear_last_page(archive):
    _exec("DELETE FROM reading WHERE archive=?", (key(archive),))
