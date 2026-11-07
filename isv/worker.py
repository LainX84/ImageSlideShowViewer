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
