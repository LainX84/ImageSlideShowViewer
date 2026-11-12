"""Modello e disegno delle miniature, con cache su disco."""
import hashlib
import os
import time
from collections import OrderedDict

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QRect, QRectF, QSize, QStandardPaths, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import anim, codecs
from .archive import is_archive, stat_any
from .i18n import tr
from .utils import find_cover, human_size
from .worker import BgWorker

THUMB_PX = 240
VIDEO_PENDING = "video"
MEM_CACHE = 1500


def cache_dir():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    d = os.path.join(base or os.path.expanduser("~/.cache/ImageSlideShowViewer"), "miniature")
    os.makedirs(d, exist_ok=True)
    return d


CACHE_MAX_MB = 3000    # oltre questa dimensione la cache su disco viene sfoltita
CACHE_KEEP_MB = 2500   # ... fino a questa, togliendo le miniature usate meno di recente


def trim_cache(cdir, max_mb=CACHE_MAX_MB, keep_mb=CACHE_KEEP_MB):
    """Tiene sotto controllo la cache delle miniature (eseguita in background all'avvio)."""
    files, total = [], 0
    for root, _dirs, names in os.walk(cdir):
        for n in names:
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append((st.st_atime, st.st_size, p))
            total += st.st_size
    if total <= max_mb * 1024 * 1024:
        return 0
    files.sort()  # le più vecchie prima
    removed = 0
    for _at, size, p in files:
        if total <= keep_mb * 1024 * 1024:
            break
        try:
            os.remove(p)
            total -= size
            removed += 1
        except OSError:
            pass
    return removed


def _cache_key(path, mtime, size):
    return hashlib.sha1(f"{path}|{mtime}|{size}|{THUMB_PX}".encode("utf-8", "surrogatepass")).hexdigest()


def store_thumbnail(img, path, mtime, size, cdir):
    """Salva nella cache su disco una miniatura ottenuta altrove (fotogramma di un video)."""
    key = _cache_key(path, mtime, size)
    sub = os.path.join(cdir, key[:2])
    if img.width() > THUMB_PX or img.height() > THUMB_PX:
        img = img.scaled(THUMB_PX, THUMB_PX, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    try:
        os.makedirs(sub, exist_ok=True)
        img.save(os.path.join(sub, key + ".jpg"), "JPG", 85)
    except OSError:
        pass
    return img


def make_thumbnail(path, mtime, size, cdir):
    key = _cache_key(path, mtime, size)
    sub = os.path.join(cdir, key[:2])
    for ext in (".jpg", ".png"):
        cp = os.path.join(sub, key + ext)
        if os.path.exists(cp):
            img = QImage(cp)
            if not img.isNull():
                try:
                    os.utime(cp)  # segna come usata di recente (per la pulizia)
                except OSError:
                    pass
                return img
    if codecs.is_video(path):
        return VIDEO_PENDING        # il fotogramma lo estrae video.VideoThumbnailer
    img, _err = codecs.read_qimage(path, THUMB_PX)
    if img.isNull():
        return img
    if img.width() > THUMB_PX or img.height() > THUMB_PX:
        img = img.scaled(THUMB_PX, THUMB_PX, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    try:
        os.makedirs(sub, exist_ok=True)
        if img.hasAlphaChannel():
            img.save(os.path.join(sub, key + ".png"), "PNG")
        else:
            img.save(os.path.join(sub, key + ".jpg"), "JPG", 85)
    except OSError:
        pass
    return img


def _placeholder(broken=False):
    pm = QPixmap(THUMB_PX, THUMB_PX)
    pm.fill(Qt.GlobalColor.transparent)
    if broken:
        p = QPainter(pm)
        p.setPen(QPen(QColor(150, 80, 80), 6))
        m = THUMB_PX // 3
        p.drawLine(m, m, THUMB_PX - m, THUMB_PX - m)
        p.drawLine(THUMB_PX - m, m, m, THUMB_PX - m)
        p.end()
    return QIcon(pm)


class ThumbModel(QAbstractListModel):
    PathRole = Qt.ItemDataRole.UserRole + 1
    IsDirRole = Qt.ItemDataRole.UserRole + 2
    MetaRole = Qt.ItemDataRole.UserRole + 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.rows = {}
        self.icons = OrderedDict()
        self.requested = set()
        self.failed = set()
        self.cdir = cache_dir()
        self.worker = BgWorker(max(2, min(6, (os.cpu_count() or 4) - 1)), self)
        import threading
        threading.Thread(target=trim_cache, args=(self.cdir,), daemon=True).start()
        self.placeholder = _placeholder()
        self.broken = _placeholder(True)
        self.live = None        # (percorso, QIcon): fotogramma corrente della GIF/WebP selezionata
        self.meta = {}          # percorso -> (stelle, etichetta)
        self.favs = set()
        self.videos = None      # VideoThumbnailer, creato al primo video

    @staticmethod
    def _key(it):
        return f"{it.path}|{it.mtime}"

    def set_items(self, items):
        self.worker.cancel_pending()
        self.beginResetModel()
        self.items = list(items)
        self.rows = {it.path: i for i, it in enumerate(self.items)}
        self.requested.clear()
        self.failed.clear()
        self.live = None
        if self.videos is not None:
            self.videos.clear()
        files = [it.path for it in self.items if not it.is_dir]
        try:
            from . import library
            self.meta = library.get_many(files)
            self.favs = library.favorites_among(files)
        except Exception:  # noqa: BLE001 - database non disponibile
            self.meta, self.favs = {}, set()
        self.endResetModel()

    def refresh_meta(self, paths):
        from . import library
        self.meta.update({p: library.get(p) for p in paths})
        fav = library.favorites_among(paths)
        for p in paths:
            (self.favs.add if p in fav else self.favs.discard)(p)
            row = self.rows.get(p)
            if row is not None:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [self.MetaRole])

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        it = self.items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return it.name
        if role == Qt.ItemDataRole.DecorationRole:
            if self.live is not None and self.live[0] == it.path:
                return self.live[1]
            k = self._key(it)
            icon = self.icons.get(k)
            if icon is not None:
                self.icons.move_to_end(k)
                return icon
            if it.path in self.failed:
                return self.placeholder if it.is_dir else self.broken
            if it.path not in self.requested:
                self.requested.add(it.path)
                self.worker.submit(self._make, self._done, it)
            return self.placeholder
        if role == self.IsDirRole:
            return it.is_dir
        if role == self.MetaRole:
            r, lb = self.meta.get(it.path, (0, 0))
            return (r, lb, it.path in self.favs, not it.is_dir and codecs.is_video(it.path))
        if role == Qt.ItemDataRole.ToolTipRole and it.is_dir:
            kind = tr("Archivio") if is_archive(it.name) else tr("Cartella")
            return f"{it.name}\n{kind} – " + tr("doppio clic per aprirla, F5 per lo slideshow")
        if role == Qt.ItemDataRole.ToolTipRole:
            d = time.strftime(tr("%d/%m/%Y %H:%M"), time.localtime(it.mtime))
            return f"{it.name}\n{human_size(it.size)}\n{d}"
        if role == self.PathRole:
            return it.path
        return None

    def _make(self, it):
        try:
            if it.is_dir:
                cover = find_cover(it.path)
                if not cover:
                    return it.path, QImage()
                mt, size = stat_any(cover)
                img = make_thumbnail(cover, mt, size, self.cdir)
            else:
                img = make_thumbnail(it.path, it.mtime, it.size, self.cdir)
        except Exception:  # noqa: BLE001 - file sparito, permessi, ecc.
            img = QImage()
        return it.path, img

    def _done(self, res):
        if isinstance(res, Exception):
            return
        path, img = res
        row = self.rows.get(path)
        if row is None:
            return
        it = self.items[row]
        if isinstance(img, str):        # video: il fotogramma si estrae nel thread principale
            if self.videos is None:
                from .video import VideoThumbnailer
                self.videos = VideoThumbnailer(self)
                self.videos.done.connect(self._video_done)
            self.videos.request(path)
            return
        if img.isNull():
            self.failed.add(path)
        else:
            self.icons[self._key(it)] = QIcon(QPixmap.fromImage(img))
            while len(self.icons) > MEM_CACHE:
                old, _ = self.icons.popitem(last=False)
                self.requested.discard(old.rsplit("|", 1)[0])
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def _video_done(self, path, img):
        row = self.rows.get(path)
        if row is None:
            return
        it = self.items[row]
        if img.isNull():
            self.failed.add(path)
        else:
            img = store_thumbnail(img, it.path, it.mtime, it.size, self.cdir)
            self.icons[self._key(it)] = QIcon(QPixmap.fromImage(img))
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def set_live(self, path, icon):
        """Mostra icon al posto della miniatura di path (None = torna alla miniatura)."""
        old = self.live[0] if self.live else None
        self.live = (path, icon) if path and icon is not None else None
        for p in {old, path}:
            row = self.rows.get(p) if p else None
            if row is not None:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def path(self, row):
        return self.items[row].path

    def is_dir(self, row):
        return self.items[row].is_dir

    def counts(self):
        d = sum(1 for i in self.items if i.is_dir)
        return d, len(self.items) - d

    def total_size(self, rows=None):
        if rows is None:
            return sum(i.size for i in self.items)
        return sum(self.items[r].size for r in rows)


class ThumbDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        s = option.decorationSize.width()
        return QSize(s + 14, s + option.fontMetrics.height() + 18)

    def paint(self, p, option, index):
        p.save()
        r = option.rect.adjusted(2, 2, -2, -2)
        sel = bool(option.state & QStyle.StateFlag.State_Selected)
        hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if sel:
            p.setPen(QPen(option.palette.highlight().color(), 2))
            c = QColor(option.palette.highlight().color())
            c.setAlpha(90)
            p.setBrush(c)
            p.drawRoundedRect(r, 6, 6)
        elif hov:
            p.setPen(Qt.PenStyle.NoPen)
            c = QColor(option.palette.text().color())
            c.setAlpha(22)
            p.setBrush(c)
            p.drawRoundedRect(r, 6, 6)
        s = option.decorationSize.width()
        icon_rect = QRect(r.x() + (r.width() - s) // 2, r.y() + 5, s, s)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if index.data(ThumbModel.IsDirRole):
            self._paint_folder(p, icon_rect, icon,
                               is_archive(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        elif isinstance(icon, QIcon):
            icon.paint(p, icon_rect, Qt.AlignmentFlag.AlignCenter)
            self._paint_badges(p, icon_rect, index.data(ThumbModel.MetaRole))
        fm = option.fontMetrics
        text_rect = QRect(r.x() + 4, icon_rect.bottom() + 5, r.width() - 8, fm.height())
        name = fm.elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "",
                             Qt.TextElideMode.ElideMiddle, text_rect.width())
        p.setPen(option.palette.highlightedText().color() if sel else option.palette.text().color())
        p.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, name)
        p.restore()

    @staticmethod
    def _paint_badges(p, r, meta):
        """Stelle, etichetta colorata, Preferiti e simbolo dei video sulla miniatura."""
        if not meta:
            return
        rating, label, fav, video = meta
        from PySide6.QtGui import QFont, QPainterPath
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if label:
            from .library import label_color
            path = QPainterPath()
            path.addRoundedRect(QRectF(r.x() + 4, r.y() + 4, 14, 14), 7, 7)
            p.fillPath(path, QColor(label_color(label)))
            p.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
            p.drawPath(path)
        f = QFont(p.font())
        f.setPointSize(max(7, r.width() // 18))
        p.setFont(f)
        if fav:
            p.setPen(QColor(0, 0, 0, 160))
            p.drawText(QRect(r.right() - 25, r.y() + 3, 22, 20), Qt.AlignmentFlag.AlignCenter, "♥")
            p.setPen(QColor(235, 70, 90))
            p.drawText(QRect(r.right() - 26, r.y() + 2, 22, 20), Qt.AlignmentFlag.AlignCenter, "♥")
        if rating:
            txt = "★" * rating
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(txt) + 8
            box = QRectF(r.x() + 3, r.bottom() - fm.height() - 4, w, fm.height() + 2)
            path = QPainterPath()
            path.addRoundedRect(box, 4, 4)
            p.fillPath(path, QColor(0, 0, 0, 150))
            p.setPen(QColor(255, 205, 60))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, txt)
        if video:
            c = r.center()
            path = QPainterPath()
            path.addEllipse(QRectF(c.x() - 18, c.y() - 18, 36, 36))
            p.fillPath(path, QColor(0, 0, 0, 140))
            tri = QPainterPath()
            tri.moveTo(c.x() - 6, c.y() - 10)
            tri.lineTo(c.x() + 11, c.y())
            tri.lineTo(c.x() - 6, c.y() + 10)
            tri.closeSubpath()
            p.fillPath(tri, QColor(255, 255, 255, 230))

    @staticmethod
    def _paint_folder(p, r, icon, archive=False):
        """Cartella disegnata con l'anteprima della prima immagine dentro."""
        w, h = r.width(), r.height()
        tab = QRectF(r.x() + w * 0.04, r.y() + h * 0.10, w * 0.40, h * 0.14)
        body = QRectF(r.x() + w * 0.02, r.y() + h * 0.16, w * 0.96, h * 0.74)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(70, 120, 190) if archive else QColor(196, 148, 48))
        p.drawRoundedRect(tab, 4, 4)
        p.setBrush(QColor(98, 150, 220) if archive else QColor(232, 184, 72))
        p.drawRoundedRect(body, 6, 6)
        if isinstance(icon, QIcon):
            inner = body.adjusted(w * 0.06, h * 0.07, -w * 0.06, -h * 0.07).toRect()
            icon.paint(p, inner, Qt.AlignmentFlag.AlignCenter)


class ThumbAnimator(QObject):
    """Anima nel browser la miniatura della GIF / WebP selezionata."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.worker = BgWorker(1, self)
        self.movie = None
        self.path = None

    def play(self, path):
        if path == self.path:
            return
        self.stop()
        self.path = path
        if not path or not anim.maybe_animated(path):
            return
        self.worker.cancel_pending()
        # contare i fotogrammi di una GIF grande può richiedere un attimo: in background
        self.worker.submit(lambda p=path: (p, anim.probe(p)), self._probed)

    def _probed(self, res):
        if isinstance(res, Exception):
            return
        path, size = res
        if path != self.path or size is None:
            return
        m = anim.make_movie(path, self)
        if m is None:
            return
        small = anim.fit_size(size, THUMB_PX)
        if small.isValid():
            m.setScaledSize(small)      # i fotogrammi si decodificano già piccoli
        m.frameChanged.connect(self._frame)
        self.movie = m
        m.start()

    def _frame(self, _n):
        if self.movie is None:
            return
        img = self.movie.currentImage()
        if not img.isNull():
            self.model.set_live(self.path, QIcon(QPixmap.fromImage(img)))

    def stop(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        if self.path is not None:
            self.model.set_live(None, None)
        self.path = None
