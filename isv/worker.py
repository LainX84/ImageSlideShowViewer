"""Esecuzione in background con consegna dei risultati sul thread dell'interfaccia.

Usa un ThreadPoolExecutor + una coda letta da un QTimer: più affidabile dei
segnali emessi da QRunnable in PySide6.
"""
import queue
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, QTimer


class BgWorker(QObject):
    def __init__(self, threads=2, parent=None):
        super().__init__(parent)
        self._ex = ThreadPoolExecutor(max_workers=threads)
        self._q = queue.Queue()
        self._pending = 0
        self._timer = QTimer(self, interval=15)
        self._timer.timeout.connect(self._drain)
        self._gen = 0

    def submit(self, fn, callback, *args):
        """Esegue fn(*args) in background, poi callback(risultato) nel thread GUI."""
        gen = self._gen
        self._pending += 1
        if not self._timer.isActive():
            self._timer.start()

        def task():
            if gen != self._gen:
                self._q.put(None)
                return
            try:
                res = fn(*args)
            except Exception as e:  # noqa: BLE001
                res = e
            self._q.put((gen, callback, res))

        self._ex.submit(task)

    def cancel_pending(self):
        """I lavori in coda non ancora iniziati vengono scartati."""
        self._gen += 1

    def _drain(self):
        for _ in range(64):
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            self._pending -= 1
            if item is None:
                continue
            gen, cb, res = item
            if gen == self._gen:
                cb(res)
        if self._pending <= 0:
            self._pending = 0
            self._timer.stop()

    def shutdown(self):
        self._gen += 1
        self._ex.shutdown(wait=False, cancel_futures=True)


def run_with_progress(parent, title, fn, *args):
    """Esegue fn(progress, *args) in un thread mostrando una barra di avanzamento.

    progress(i, n, testo) aggiorna la barra e ritorna True se l'utente ha annullato.
    Ritorna il risultato di fn, oppure None se annullato. Le eccezioni vengono rilanciate."""
    import threading
    import time
    from PySide6.QtCore import QEventLoop, Qt as _Qt
    from PySide6.QtWidgets import QApplication, QProgressDialog
    from .i18n import tr
    state = {"i": 0, "n": 0, "text": "", "cancel": False, "done": False, "res": None, "err": None}

    def progress(i, n, text=""):
        state["i"], state["n"], state["text"] = i, n, text
        return state["cancel"]

    def run():
        try:
            state["res"] = fn(progress, *args)
        except BaseException as e:  # noqa: BLE001
            state["err"] = e
        state["done"] = True

    dlg = QProgressDialog(title, tr("Annulla"), 0, 0, parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(_Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(400)
    dlg.setMinimumWidth(460)
    t = threading.Thread(target=run, daemon=True)
    t.start()
    while not state["done"]:
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        if dlg.wasCanceled():
            state["cancel"] = True
        n = state["n"]
        if n:
            dlg.setMaximum(n)
            dlg.setValue(min(state["i"], n))
        if state["text"]:
            dlg.setLabelText(state["text"])
        time.sleep(0.02)
    dlg.reset()
    dlg.close()
    if state["err"] is not None and not isinstance(state["err"], InterruptedError):
        raise state["err"]
    return None if state["cancel"] else state["res"]
