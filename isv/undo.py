"""Eliminazione rapida e smistamento annullabili (Ctrl+Z).

Il Cestino di Windows non permette di ripristinare un file in modo affidabile da un
programma, quindi un file "eliminato" viene prima spostato in una cartella nascosta
".isv-cestino" accanto a lui (stesso disco: istantaneo). Da lì Ctrl+Z lo rimette al
suo posto; alla chiusura del visualizzatore / del programma (o quando gli annullamenti
in sospeso sono troppi) i file passano davvero nel Cestino del sistema.

Le operazioni annullabili sono anche "sposta in" e "copia in" (smistamento con i tasti
1-9, comandi del browser).
"""
import os
import shutil
import sys

from .utils import unique_path

STAGE = ".isv-cestino"
MAX_PENDING = 200


class Op:
    def __init__(self, kind, src, dst, index=None):
        self.kind = kind        # "delete" | "move" | "copy"
        self.src = src          # dove stava il file
        self.dst = dst          # dove si trova adesso (cartella di appoggio / destinazione)
        self.index = index      # posizione nell'elenco del visualizzatore (per rimetterlo lì)


class UndoManager:
    def __init__(self):
        self.ops = []

    # ---------------------------------------------------------------- azioni
    def delete(self, path, index=None):
        """Sposta path nella cartella di appoggio. Ritorna True se riuscito."""
        folder = os.path.dirname(path)
        stage = os.path.join(folder, STAGE)
        try:
            os.makedirs(stage, exist_ok=True)
            _hide(stage)
            dst = unique_path(os.path.join(stage, os.path.basename(path)))
            os.replace(path, dst)
        except OSError:
            # cartella di sola lettura o simile: direttamente nel Cestino (non annullabile)
            from .batch import move_to_trash
            return move_to_trash(path)
        self.ops.append(Op("delete", path, dst, index))
        self._trim()
        return True

    def move(self, path, dest_folder, index=None):
        os.makedirs(dest_folder, exist_ok=True)
        dst = unique_path(os.path.join(dest_folder, os.path.basename(path)))
        shutil.move(path, dst)
        from . import library
        library.move_path(path, dst)
        self.ops.append(Op("move", path, dst, index))
        return dst

    def copy(self, path, dest_folder, data=None):
        os.makedirs(dest_folder, exist_ok=True)
        name = os.path.basename(path.split("|")[-1])
        dst = unique_path(os.path.join(dest_folder, name))
        if data is not None:            # immagine dentro un archivio
            with open(dst, "wb") as f:
                f.write(data)
        else:
            shutil.copy2(path, dst)
        self.ops.append(Op("copy", path, dst))
        return dst

    # --------------------------------------------------------------- annulla
    def can_undo(self):
        return bool(self.ops)

    def last_kind(self):
        return self.ops[-1].kind if self.ops else None

    def undo(self):
        """Annulla l'ultima operazione. Ritorna l'Op annullata (src = file ripristinato)
        oppure None. Solleva OSError se non si può."""
        if not self.ops:
            return None
        op = self.ops.pop()
        if op.kind in ("delete", "move"):
            target = op.src if not os.path.exists(op.src) else unique_path(op.src)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.move(op.dst, target)
            op.src = target
            if op.kind == "move":
                from . import library
                library.move_path(op.dst, target)
            _cleanup(os.path.dirname(op.dst)) if op.kind == "delete" else None
        elif op.kind == "copy":
            from .batch import move_to_trash
            if os.path.exists(op.dst) and not move_to_trash(op.dst):
                os.remove(op.dst)
        return op

    # ------------------------------------------------------ svuotamento
    def flush(self):
        """I file eliminati in sospeso passano nel Cestino del sistema."""
        from .batch import move_to_trash
        keep = []
        stages = set()
        for op in self.ops:
            if op.kind == "delete":
                stages.add(os.path.dirname(op.dst))
                if os.path.exists(op.dst) and not move_to_trash(op.dst):
                    keep.append(op)
            # "move" e "copy" non hanno nulla in sospeso
        self.ops = keep
        for s in stages:
            _cleanup(s)

    def _trim(self):
        pending = [o for o in self.ops if o.kind == "delete"]
        if len(pending) > MAX_PENDING:
            from .batch import move_to_trash
            old = pending[0]
            if move_to_trash(old.dst):
                self.ops.remove(old)
                _cleanup(os.path.dirname(old.dst))


def flush_leftovers(folder):
    """File rimasti in una cartella di appoggio (programma chiuso male): nel Cestino."""
    stage = os.path.join(folder, STAGE)
    if not os.path.isdir(stage) or any(os.path.dirname(o.dst) == stage for o in manager.ops):
        return
    from .batch import move_to_trash
    for n in os.listdir(stage):
        move_to_trash(os.path.join(stage, n))
    _cleanup(stage)


def _cleanup(stage):
    try:
        if os.path.basename(stage) == STAGE and not os.listdir(stage):
            os.rmdir(stage)
    except OSError:
        pass


def _hide(path):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:  # noqa: BLE001
            pass


manager = UndoManager()
