"""Comandi sui file usati dai menu contestuali (browser e visualizzatore):
appunti di Windows (taglia / copia / incolla), copia percorso, apri con, sfondo del
desktop, proprietà, stampa, rinomina singola, nuova cartella."""
import os
import subprocess
import sys

from PySide6.QtCore import QByteArray, QMimeData, QSizeF, QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QPainter
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from . import APP_ID, APP_NAME
from .archive import image_reader, is_virtual, stat_any
from .i18n import tr
from .utils import human_size

WIN = sys.platform == "win32"
# formato con cui Esplora risorse distingue "Taglia" da "Copia"
DROP_EFFECT = 'application/x-qt-windows-mime;value="Preferred DropEffect"'
DROPEFFECT_COPY, DROPEFFECT_MOVE = 5, 2


# ------------------------------------------------------------------ appunti
def clipboard_set(paths, cut=False):
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    md.setText("\r\n".join(paths))
    eff = DROPEFFECT_MOVE if cut else DROPEFFECT_COPY
    data = QByteArray(eff.to_bytes(4, "little"))
    md.setData(DROP_EFFECT, data)
    md.setData("application/x-isv-cut", QByteArray(b"1" if cut else b"0"))
    QApplication.clipboard().setMimeData(md)


def clipboard_get():
    """(percorsi, taglia?) dei file negli appunti, anche se copiati da Esplora risorse."""
    md = QApplication.clipboard().mimeData()
    if md is None or not md.hasUrls():
        return [], False
    paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
    paths = [os.path.normpath(p) for p in paths if p and os.path.exists(p)]
    cut = False
    if md.hasFormat(DROP_EFFECT):
        raw = bytes(md.data(DROP_EFFECT))
        if len(raw) >= 4:
            cut = bool(int.from_bytes(raw[:4], "little") & DROPEFFECT_MOVE) and \
                not int.from_bytes(raw[:4], "little") & 1
    elif md.hasFormat("application/x-isv-cut"):
        cut = bytes(md.data("application/x-isv-cut")) == b"1"
    return paths, cut


def clipboard_has_files():
    return bool(clipboard_get()[0])


def copy_as_path(paths):
    QApplication.clipboard().setText("\r\n".join(f'"{p}"' for p in paths))


def copy_image(img):
    if img is not None and not img.isNull():
        QApplication.clipboard().setImage(img)


# ---------------------------------------------------------------- apri con
def open_default(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def open_with(path):
    """Finestra di Windows "Apri con…"."""
    if WIN:
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", os.path.normpath(path)])
    else:
        open_default(path)


def edit_with_paint(path):
    if WIN:
        subprocess.Popen(["mspaint.exe", os.path.normpath(path)])
    else:
        open_default(path)


# ------------------------------------------------------------------ immagini
def read_image(path):
    r, keep = image_reader(path)
    r.setAutoTransform(True)
    img = r.read()
    del keep
    return img


def set_wallpaper(parent, path):
    if not WIN:
        QMessageBox.information(parent, APP_NAME, tr("Disponibile solo su Windows."))
        return False
    img = read_image(path)
    if img.isNull():
        QMessageBox.warning(parent, APP_NAME, tr("Impossibile aprire\n{name}\n\n{err}",
                                                 name=os.path.basename(path), err=""))
        return False
    # Windows accetta bene solo JPEG/BMP: si salva una copia nella cartella dei dati
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    os.makedirs(base, exist_ok=True)
    dst = os.path.join(base, "wallpaper.jpg")
    if not img.convertToFormat(QImage.Format.Format_RGB32).save(dst, "JPG", 95):
        return False
    import ctypes
    ok = ctypes.windll.user32.SystemParametersInfoW(20, 0, dst, 0x01 | 0x02)  # SPI_SETDESKWALLPAPER
    if not ok:
        QMessageBox.warning(parent, APP_NAME, tr("Impossibile impostare lo sfondo del desktop."))
    return bool(ok)


def show_properties(parent, path, image=None):
    """Proprietà di Windows (come Alt+Invio in Esplora risorse); per le immagini dentro
    un archivio, o fuori da Windows, una finestra con le informazioni principali."""
    if WIN and not is_virtual(path):
        try:
            import ctypes
            if ctypes.windll.shell32.SHObjectProperties(None, 0x2, os.path.normpath(path), None):
                return
        except Exception:  # noqa: BLE001
            pass
    import time
    lines = [f"<b>{os.path.basename(path.split('|')[-1])}</b>", path.replace("|", " › ")]
    try:
        mt, sz = stat_any(path)
        lines.append(tr("Dimensione") + f": {human_size(sz)}")
        lines.append(tr("Data") + ": " + time.strftime(tr("%d/%m/%Y %H:%M"), time.localtime(mt)))
    except OSError:
        pass
    if image is None and not os.path.isdir(path):
        r, keep = image_reader(path)
        s = r.size()
        if s.isValid():
            lines.append(f"{s.width()} × {s.height()} px")
        del keep
    elif image is not None and not image.isNull():
        lines.append(f"{image.width()} × {image.height()} px")
    QMessageBox.information(parent, tr("Proprietà"), "<br>".join(lines))


def print_images(parent, paths):
    try:
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    except ImportError:
        QMessageBox.warning(parent, APP_NAME, tr("Stampa non disponibile."))
        return
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dlg = QPrintDialog(printer, parent)
    dlg.setWindowTitle(tr("Stampa – {n} immagini", n=len(paths)))
    if dlg.exec() != QPrintDialog.DialogCode.Accepted:
        return
    p = QPainter()
    if not p.begin(printer):
        QMessageBox.warning(parent, APP_NAME, tr("Impossibile avviare la stampa."))
        return
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        first = True
        for path in paths:
            img = read_image(path)
            if img.isNull():
                continue
            if not first:
                printer.newPage()
            first = False
            page = printer.pageRect(QPrinter.Unit.DevicePixel)
            sz = QSizeF(img.size())
            sz.scale(page.size(), Qt.AspectRatioMode.KeepAspectRatio)
            x = (page.width() - sz.width()) / 2
            y = (page.height() - sz.height()) / 2
            from PySide6.QtCore import QRectF
            p.drawImage(QRectF(x, y, sz.width(), sz.height()), img)
    finally:
        p.end()
        QApplication.restoreOverrideCursor()


# --------------------------------------------------------- rinomina / cartelle
def rename_single(parent, path):
    """Rinomina un solo file o cartella; ritorna il nuovo percorso o None."""
    from .rename import invalid_reason
    folder, name = os.path.split(path)
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(tr("Rinomina"))
    dlg.setLabelText(tr("Nuovo nome:"))
    dlg.setTextValue(name)
    dlg.resize(460, dlg.sizeHint().height())
    # seleziona solo il nome, senza l'estensione, come Esplora risorse
    from PySide6.QtWidgets import QLineEdit
    QApplication.processEvents()
    ed = dlg.findChild(QLineEdit)
    if ed is not None and not os.path.isdir(path):
        stem = os.path.splitext(name)[0]
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: ed.setSelection(0, len(stem)))
    while True:
        if dlg.exec() != QInputDialog.DialogCode.Accepted:
            return None
        new = dlg.textValue().strip()
        if not new or new == name:
            return None
        why = invalid_reason(new)
        dst = os.path.join(folder, new)
        if why:
            from .batch import status_text
            from .rename import INVALID
            QMessageBox.warning(parent, tr("Rinomina"), status_text(INVALID, why))
            continue
        if os.path.exists(dst) and os.path.normcase(dst) != os.path.normcase(path):
            QMessageBox.warning(parent, tr("Rinomina"), tr("Esiste già un elemento con questo nome."))
            continue
        try:
            if os.path.normcase(dst) == os.path.normcase(path):   # solo maiuscole/minuscole
                tmp = path + "." + APP_ID + "tmp"
                os.rename(path, tmp)
                os.rename(tmp, dst)
            else:
                os.rename(path, dst)
            return dst
        except OSError as e:
            QMessageBox.warning(parent, tr("Rinomina"), f"{name}: {e.strerror or e}")
            return None


def new_folder(parent, folder):
    name, ok = QInputDialog.getText(parent, tr("Nuova cartella"), tr("Nome della nuova cartella:"),
                                    text=tr("Nuova cartella"))
    name = name.strip()
    if not ok or not name:
        return None
    from .rename import invalid_reason
    if invalid_reason(name):
        QMessageBox.warning(parent, tr("Nuova cartella"), tr("nome non valido"))
        return None
    from .utils import unique_path
    dst = unique_path(os.path.join(folder, name))
    try:
        os.makedirs(dst)
        return dst
    except OSError as e:
        QMessageBox.warning(parent, tr("Nuova cartella"), f"{e.strerror or e}")
        return None
