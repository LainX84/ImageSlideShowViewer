"""Modalità salvaschermo: dopo un certo tempo senza usare mouse e tastiera parte uno
slideshow casuale a schermo intero della cartella scelta; si chiude toccando il mouse
o un tasto. Funziona mentre il programma è aperto (anche ridotto a icona).

Il tempo di inattività si legge dal sistema (Windows, macOS, Linux con X11); dove non
è possibile si conta solo l'uso del programma.
"""
import ctypes
import sys
import time

from PySide6.QtCore import QEvent, QObject, QTimer


def system_idle_seconds():
    """Secondi dall'ultimo uso di mouse / tastiera nel sistema, oppure None."""
    try:
        if sys.platform == "win32":
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            li = LASTINPUTINFO()
            li.cbSize = ctypes.sizeof(li)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
                return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0
        elif sys.platform == "darwin":
            q = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            f = q.CGEventSourceSecondsSinceLastEventType
            f.restype = ctypes.c_double
            f.argtypes = [ctypes.c_int, ctypes.c_uint32]
            return float(f(1, 0xFFFFFFFF))
        else:
            import ctypes.util
            x11 = ctypes.cdll.LoadLibrary(ctypes.util.find_library("X11") or "libX11.so.6")
            xss = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Xss") or "libXss.so.1")

            class XScreenSaverInfo(ctypes.Structure):
                _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                            ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong),
                            ("eventMask", ctypes.c_ulong)]
            x11.XOpenDisplay.restype = ctypes.c_void_p
            dpy = x11.XOpenDisplay(None)
            if not dpy:
                return None
            xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
            info = xss.XScreenSaverAllocInfo()
            x11.XDefaultRootWindow.restype = ctypes.c_ulong
            root = x11.XDefaultRootWindow(ctypes.c_void_p(dpy))
            xss.XScreenSaverQueryInfo(ctypes.c_void_p(dpy), root, info)
            idle = info.contents.idle / 1000.0
            x11.XFree(info)
            x11.XCloseDisplay(ctypes.c_void_p(dpy))
            return idle
    except Exception:  # noqa: BLE001
        return None
    return None


class IdleMonitor(QObject):
    """Chiama start_cb() dopo `minutes` minuti di inattività (se attivo nelle opzioni)."""

    def __init__(self, app, settings, start_cb):
        super().__init__(app)
        self.settings, self.start_cb = settings, start_cb
        self.last_app_input = time.monotonic()
        self.fired = False
        app.installEventFilter(self)
        self.timer = QTimer(self, interval=10_000)
        self.timer.timeout.connect(self._check)
        self.timer.start()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress,
                         QEvent.Type.Wheel):
            self.last_app_input = time.monotonic()
        return False

    def _check(self):
        s = self.settings
        if not s.value("screensaver/enabled", False, type=bool):
            self.fired = False
            return
        limit = max(1, s.value("screensaver/minutes", 10, type=int)) * 60
        idle = system_idle_seconds()
        if idle is None:
            idle = time.monotonic() - self.last_app_input
        if idle < limit:
            self.fired = False
            return
        if not self.fired:
            self.fired = True
            self.start_cb()
