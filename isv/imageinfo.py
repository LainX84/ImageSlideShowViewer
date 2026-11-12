"""Finestra "Informazioni immagine": dati del file, dell'immagine ed EXIF.

I dati EXIF si leggono con Pillow (facoltativa): se manca, la finestra mostra comunque
file e immagine e propone di installarla.
"""
import io
import os
import subprocess
import sys
import time

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import APP_NAME
from .archive import image_reader, is_virtual, read_bytes, stat_any
from .i18n import num, tr
from .utils import human_size

WIN = sys.platform == "win32"


# ----------------------------------------------------------------- lettura EXIF
def _pillow():
    try:
        import importlib
        importlib.invalidate_caches()   # Pillow potrebbe essere appena stata installata
        from PIL import ExifTags, Image
        return Image, ExifTags
    except ImportError:
        return None, None


def _ratio(v):
    try:
        return float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        try:
            a, b = v
            return a / b if b else None
        except (TypeError, ValueError):
            return None


def _text(v):
    if isinstance(v, bytes):
        v = v.split(b"\0", 1)[0].decode("utf-8", "replace")
    return str(v).strip().strip("\0").strip()


def _exposure(v):
    t = _ratio(v)
    if not t:
        return None
    if t >= 1:
        return f"{num(round(t, 1))} s"
    return f"1/{round(1 / t)} s"


def _gps_deg(vals, ref):
    try:
        d, m, s = (_ratio(x) for x in vals)
        deg = d + m / 60 + s / 3600
    except (TypeError, ValueError):
        return None
    return -deg if ref in ("S", "W") else deg


ORIENT = {1: "Normale", 2: "Specchiata in orizzontale", 3: "Ruotata di 180°",
          4: "Specchiata in verticale", 5: "Specchiata e ruotata di 90° a sinistra",
          6: "Ruotata di 90° a destra", 7: "Specchiata e ruotata di 90° a destra",
          8: "Ruotata di 90° a sinistra"}
PROGRAM = {0: "Non definito", 1: "Manuale", 2: "Automatico", 3: "Priorità di diaframma",
           4: "Priorità di tempi", 5: "Creativo", 6: "Azione", 7: "Ritratto", 8: "Paesaggio"}
METERING = {0: "Sconosciuta", 1: "Media", 2: "Media ponderata al centro", 3: "Spot",
            4: "Multi-spot", 5: "Matrix / valutativa", 6: "Parziale"}


def read_exif(path):
    """Restituisce (principali, gps, tutti, extra) oppure None se Pillow non c'è.
    principali/gps: liste di (etichetta, valore); tutti: (nome tag, valore) grezzi;
    extra: info dal formato (DPI, profilo colore, testo PNG...)."""
    Image, ExifTags = _pillow()
    if Image is None:
        return None
    main, gps, raw, extra = [], [], [], []
    try:
        from .codecs import _init_pillow, is_raw, is_video
        if is_video(path) or is_raw(path):
            return main, gps, raw, extra
        _init_pillow()
        src = io.BytesIO(read_bytes(path)) if is_virtual(path) else path
        with Image.open(src) as im:
            extra.append((tr("Modalità colore"), im.mode))
            dpi = im.info.get("dpi")
            if dpi and _ratio(dpi[0]):
                extra.append(("DPI", f"{round(_ratio(dpi[0]))} × {round(_ratio(dpi[1]))}"))
            if im.info.get("icc_profile"):
                extra.append((tr("Profilo colore"), tr("incorporato")))
            for k in ("Title", "Description", "Comment", "Author", "Software", "parameters", "comment"):
                v = im.info.get(k)
                if isinstance(v, (str, bytes)) and _text(v):
                    extra.append((k, _text(v)[:500]))
            exif = im.getexif()
            if not exif:
                return main, gps, raw, extra
            sub = dict(exif)
            try:
                sub.update(exif.get_ifd(0x8769))      # Exif IFD (dati di scatto)
            except Exception:  # noqa: BLE001
                pass
            try:
                g = exif.get_ifd(0x8825)              # GPS
            except Exception:  # noqa: BLE001
                g = {}
    except Exception:  # noqa: BLE001
        return main, gps, raw, extra

    names = ExifTags.TAGS
    for k, v in sorted(sub.items()):
        if k in (0x8769, 0x8825, 0xA005, 0x927C, 0x9286, 0x02BC, 0x8773):  # puntatori, MakerNote, XMP...
            continue
        if isinstance(v, bytes) and len(v) > 64:
            continue
        raw.append((names.get(k, f"0x{k:04X}"), _text(v) if not isinstance(v, tuple) else
                    ", ".join(_text(x) for x in v)))
    t = {names.get(k, k): v for k, v in sub.items()}

    def add(label, value):
        if value not in (None, "", "0"):
            main.append((label, value))

    make, model = _text(t.get("Make", "")), _text(t.get("Model", ""))
    add(tr("Fotocamera"), model if model.lower().startswith(make.lower()) else f"{make} {model}".strip())
    add(tr("Obiettivo"), _text(t.get("LensModel", "")) or _text(t.get("LensMake", "")))
    taken = _text(t.get("DateTimeOriginal", "")) or _text(t.get("DateTime", ""))
    if taken:
        try:
            taken = time.strftime(tr("%d/%m/%Y %H:%M:%S"), time.strptime(taken[:19], "%Y:%m:%d %H:%M:%S"))
        except ValueError:
            pass
    add(tr("Data dello scatto"), taken)
    add(tr("Tempo di esposizione"), _exposure(t.get("ExposureTime")))
    f = _ratio(t.get("FNumber"))
    add(tr("Diaframma"), f"f/{num(round(f, 1))}" if f else None)
    iso = t.get("ISOSpeedRatings") or t.get("PhotographicSensitivity")
    if isinstance(iso, tuple):
        iso = iso[0] if iso else None
    add("ISO", str(iso) if iso else None)
    fl = _ratio(t.get("FocalLength"))
    fl35 = t.get("FocalLengthIn35mmFilm")
    if fl:
        add(tr("Lunghezza focale"), f"{num(round(fl, 1))} mm" + (tr(" (equiv. {n} mm)", n=fl35) if fl35 else ""))
    bias = _ratio(t.get("ExposureBiasValue"))
    if bias:
        add(tr("Compensazione esposizione"), f"{'+' if bias > 0 else ''}{num(round(bias, 2))} EV")
    if "ExposureProgram" in t:
        add(tr("Programma"), tr(PROGRAM.get(t["ExposureProgram"], str(t["ExposureProgram"]))))
    if "MeteringMode" in t:
        add(tr("Misurazione"), tr(METERING.get(t["MeteringMode"], str(t["MeteringMode"]))))
    if "Flash" in t:
        try:
            add(tr("Flash"), tr("Scattato") if int(t["Flash"]) & 1 else tr("Non scattato"))
        except (TypeError, ValueError):
            pass
    if "WhiteBalance" in t:
        add(tr("Bilanciamento del bianco"), tr("Manuale") if t["WhiteBalance"] == 1 else tr("Automatico"))
    if "Orientation" in t and t["Orientation"] != 1:
        add(tr("Orientamento"), tr(ORIENT.get(t["Orientation"], str(t["Orientation"]))))
    add(tr("Programma usato"), _text(t.get("Software", "")))
    add(tr("Autore"), _text(t.get("Artist", "")))
    add("Copyright", _text(t.get("Copyright", "")))
    add(tr("Descrizione"), _text(t.get("ImageDescription", "")))

    if g:
        gn = ExifTags.GPSTAGS
        gt = {gn.get(k, k): v for k, v in g.items()}
        lat = _gps_deg(gt.get("GPSLatitude"), _text(gt.get("GPSLatitudeRef", "")))
        lon = _gps_deg(gt.get("GPSLongitude"), _text(gt.get("GPSLongitudeRef", "")))
        if lat is not None and lon is not None:
            gps.append((tr("Latitudine"), f"{lat:.6f}"))
            gps.append((tr("Longitudine"), f"{lon:.6f}"))
            alt = _ratio(gt.get("GPSAltitude"))
            if alt is not None:
                below = gt.get("GPSAltitudeRef") in (1, b"\x01")
                gps.append((tr("Altitudine"), f"{'-' if below else ''}{num(round(alt))} m"))
        for k, v in sorted(gt.items(), key=lambda kv: str(kv[0])):
            raw.append((f"GPS {k}", ", ".join(_text(x) for x in v) if isinstance(v, tuple) else _text(v)))
    return main, gps, raw, extra


# ----------------------------------------------------------------- finestra
class ImageInfoDialog(QDialog):
    def __init__(self, parent, path, image=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(tr("Informazioni immagine") + " – " + os.path.basename(path.split("|")[-1]))
        self.resize(760, 620)
        lay = QHBoxLayout(self)

        # anteprima
        left = QVBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(QSize(220, 220))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left.addWidget(self.preview)
        left.addStretch(1)
        lay.addLayout(left)

        right = QVBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Proprietà"), tr("Valore")])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 210)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        right.addWidget(self.tree, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.rejected.connect(self.reject)
        b = self.buttons.addButton(tr("Copia"), QDialogButtonBox.ButtonRole.ActionRole)
        b.clicked.connect(self.copy)
        self.b_map = self.buttons.addButton(tr("Mostra sulla mappa"), QDialogButtonBox.ButtonRole.ActionRole)
        self.b_map.hide()
        if WIN and not is_virtual(path):
            b = self.buttons.addButton(tr("Proprietà di Windows…"), QDialogButtonBox.ButtonRole.ActionRole)
            b.clicked.connect(self.windows_properties)
        self.b_pillow = None
        right.addWidget(self.buttons)
        lay.addLayout(right, 1)

        self._fill(image)

    # ------------------------------------------------------------ contenuto
    def _section(self, title, rows, expanded=True):
        if not rows:
            return None
        top = QTreeWidgetItem(self.tree, [title])
        f = top.font(0)
        f.setBold(True)
        top.setFont(0, f)
        top.setFirstColumnSpanned(True)
        for k, v in rows:
            it = QTreeWidgetItem(top, [k, str(v)])
            it.setToolTip(1, str(v))
        top.setExpanded(expanded)
        return top

    def _fill(self, image):
        path = self.path
        name = path.split("|")[-1]
        # --- file
        rows = [(tr("Nome"), os.path.basename(name))]
        if is_virtual(path):
            rows.append((tr("Archivio"), path.split("|", 1)[0]))
            rows.append((tr("Percorso nell'archivio"), path.split("|", 1)[1]))
        else:
            rows.append((tr("Cartella"), os.path.dirname(path)))
        try:
            mt, sz = stat_any(path)
            rows.append((tr("Dimensione"), f"{human_size(sz)}  ({sz:,} byte)".replace(",", ".")))
            rows.append((tr("Ultima modifica"), time.strftime(tr("%d/%m/%Y %H:%M:%S"), time.localtime(mt))))
            if not is_virtual(path):
                ct = os.path.getctime(path)
                rows.append((tr("Creato"), time.strftime(tr("%d/%m/%Y %H:%M:%S"), time.localtime(ct))))
        except OSError:
            pass
        self._section(tr("File"), rows)

        # --- immagine
        from . import codecs
        fmt = codecs.format_label(path)
        frames = 0
        if not codecs.is_video(path) and fmt in ("GIF", "WEBP"):
            r, keep = image_reader(path)
            frames = r.imageCount() if r.supportsAnimation() else 0
            del keep
        size = codecs.read_size(path) if not codecs.is_video(path) else QSize()
        rows = [(tr("Formato"), fmt + (" (RAW: " + tr("anteprima incorporata") + ")" if codecs.is_raw(path) else ""))]
        if size.isValid():
            w, h = size.width(), size.height()
            rows.append((tr("Dimensioni"), f"{w} × {h} px"))
            mp = w * h / 1e6
            rows.append((tr("Megapixel"), num(round(mp, 1 if mp >= 1 else 2))))
        if frames > 1:
            rows.append((tr("Fotogrammi (animazione)"), str(frames)))
        if image is None or image.isNull():
            image = codecs.read_qimage(path, 440)[0] if not codecs.is_video(path) else None
        else:
            rows.append((tr("Profondità colore"), f"{image.depth()} bit"))
        if image is not None and not image.isNull():
            pm = QPixmap.fromImage(image).scaled(self.preview.size() * self.devicePixelRatioF(),
                                                 Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)
            pm.setDevicePixelRatio(self.devicePixelRatioF())
            self.preview.setPixmap(pm)
        from . import library
        r_, lb_ = library.get(path)
        if r_ or lb_ or library.is_favorite(path):
            rows.append((tr("Valutazione"), ("★" * r_ + "☆" * (5 - r_)) if r_ else "—"))
            if lb_:
                rows.append((tr("Etichetta"), library.label_name(lb_)))
            if library.is_favorite(path):
                rows.append((tr("Preferiti"), "♥"))

        ex = read_exif(path)
        if ex is None:
            self._section(tr("Immagine"), rows)
            top = self._section(tr("EXIF"), [(tr("Non disponibili"),
                                             tr("serve la libreria Pillow per leggere i dati EXIF"))])
            self.b_pillow = self.buttons.addButton(tr("Installa Pillow"), QDialogButtonBox.ButtonRole.ActionRole)
            self.b_pillow.clicked.connect(self.install_pillow)
            return
        main, gps, raw, extra = ex
        self._section(tr("Immagine"), rows + extra)
        if main or gps:
            self._section(tr("Scatto (EXIF)"), main)
            if gps:
                self._section(tr("Posizione GPS"), gps)
                lat, lon = gps[0][1], gps[1][1]
                self.b_map.show()
                self.b_map.clicked.connect(lambda: QDesktopServices.openUrl(
                    QUrl(f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}")))
        else:
            it = QTreeWidgetItem(self.tree, [tr("Questa immagine non contiene dati EXIF.")])
            it.setFirstColumnSpanned(True)
            f = it.font(0)
            f.setItalic(True)
            it.setFont(0, f)
        if raw:
            self._section(tr("Tutti i tag EXIF ({n})", n=len(raw)), raw, expanded=False)

    # -------------------------------------------------------------- azioni
    def copy(self):
        sel = self.tree.selectedItems()
        lines = []

        def walk(item, depth):
            if item.childCount():
                lines.append(("" if not lines else "\n") + item.text(0))
                for i in range(item.childCount()):
                    walk(item.child(i), depth + 1)
            elif item.text(1):
                lines.append(f"{item.text(0)}: {item.text(1)}")
            else:
                lines.append(item.text(0))

        if sel and any(not i.childCount() for i in sel):
            lines = [f"{i.text(0)}: {i.text(1)}" for i in sel if i.text(1)]
        else:
            for i in range(self.tree.topLevelItemCount()):
                walk(self.tree.topLevelItem(i), 0)
        QGuiApplication.clipboard().setText("\n".join(lines))

    def windows_properties(self):
        try:
            import ctypes
            ctypes.windll.shell32.SHObjectProperties(None, 0x2, os.path.normpath(self.path), None)
        except Exception:  # noqa: BLE001
            pass

    def install_pillow(self):
        if getattr(sys, "frozen", False):
            return
        exe = sys.executable
        if exe.lower().endswith("pythonw.exe"):
            exe = exe[:-len("pythonw.exe")] + "python.exe"
        self.b_pillow.setEnabled(False)
        self.b_pillow.setText(tr("Installazione…"))
        self.setCursor(Qt.CursorShape.WaitCursor)
        QGuiApplication.processEvents()
        r = subprocess.run([exe, "-m", "pip", "install", "Pillow"], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.unsetCursor()
        if r.returncode != 0:
            QMessageBox.warning(self, APP_NAME, tr("Installazione non riuscita:") + "\n\n"
                                + (r.stderr or r.stdout)[-1200:])
            self.b_pillow.setEnabled(True)
            self.b_pillow.setText(tr("Installa Pillow"))
            return
        self.b_pillow.hide()
        self.tree.clear()
        self._fill(None)


def show_image_info(parent, path, image=None):
    ImageInfoDialog(parent, path, image).exec()
