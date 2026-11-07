"""Raccoglie in un solo processo i file selezionati in Esplora risorse.

Con più file selezionati, Esplora risorse lancia il comando del menu contestuale una
volta per ogni file. Il primo processo diventa il "collettore": apre un canale locale,
riceve per qualche istante i percorsi dagli altri processi (che poi si chiudono) e
alla fine apre un'unica finestra con tutti i file.
"""
import getpass
import os
import time

from PySide6.QtCore import QByteArray, QDir, QElapsedTimer, QEventLoop, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from . import APP_ID

QUIET_MS = 500      # fine raccolta dopo questo tempo senza nuovi file
MAX_WAIT_MS = 8000  # in ogni caso non si aspetta oltre


def _names(action):
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    safe = "".join(c for c in user if c.isalnum()) or "user"
    base = f"{APP_ID}-{safe}-{action}"
    return base, os.path.join(QDir.tempPath(), base + ".lock")


def _send(server_name, paths, timeout_ms=1500):
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if not sock.waitForConnected(timeout_ms):
        return False
    data = ("\n".join(paths) + "\n").encode("utf-8")
    if sock.write(QByteArray(data)) != len(data):
        return False
    sock.flush()
    while sock.bytesToWrite() > 0:
        if not sock.waitForBytesWritten(timeout_ms):
            return False
    ok = True
    sock.disconnectFromServer()
    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        sock.waitForDisconnected(timeout_ms)
    return ok


def collect_paths(action, paths):
    """Ritorna l'elenco completo dei percorsi se questo processo è il collettore,
    oppure None se i percorsi sono stati consegnati a un altro processo."""
    server_name, lock_path = _names(action)
    lock = QLockFile(lock_path)
    lock.setStaleLockTime(15000)
    deadline = time.monotonic() + 4.0
    while not lock.tryLock(0):
        if _send(server_name, paths, 300):
            return None
        if time.monotonic() > deadline:
            return list(paths)   # qualcosa non va: si procede da soli
        time.sleep(0.05)

    collected = list(paths)
    server = QLocalServer()
    QLocalServer.removeServer(server_name)
    if not server.listen(server_name):
        lock.unlock()
        return collected

    loop = QEventLoop()
    quiet = QTimer(singleShot=True, interval=QUIET_MS)
    quiet.timeout.connect(loop.quit)
    total = QElapsedTimer()
    total.start()
    hard = QTimer(singleShot=True, interval=MAX_WAIT_MS)
    hard.timeout.connect(loop.quit)

    def on_conn():
        while server.hasPendingConnections():
            c = server.nextPendingConnection()
            buf = bytearray()

            def read(c=c, buf=buf):
                buf.extend(bytes(c.readAll()))

            def done(c=c, buf=buf):
                buf.extend(bytes(c.readAll()))
                collected.extend(l for l in buf.decode("utf-8", "replace").splitlines() if l)
                c.deleteLater()
                quiet.start()

            c.readyRead.connect(read)
            c.disconnected.connect(done)
        quiet.start()

    server.newConnection.connect(on_conn)
    quiet.start()
    hard.start()
    loop.exec()
    server.close()
    lock.unlock()
    # toglie i doppioni mantenendo l'ordine
    seen, out = set(), []
    for p in collected:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out
