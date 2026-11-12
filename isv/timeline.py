"""Calendario: le foto di una cartella (e sottocartelle) raggruppate per anno, mese e
giorno, secondo la data dello scatto (EXIF) o, in mancanza, la data del file.
Scegliendo un giorno, un mese o un anno le foto compaiono nel browser.
"""
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from . import exifutil
from .i18n import tr
from .search import walk_media
from .utils import is_video

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
          "settembre", "ottobre", "novembre", "dicembre"]


def month_name(m):
    return tr(MONTHS[m - 1]).capitalize()


def scan(progress, root, sub):
    files = walk_media(root, sub, lambda i, n, t: progress(0, 0, tr("Elenco dei file…") + "\n" + t))
    out = []
    for i, (p, _s, mt) in enumerate(files):
        if progress(i, len(files), tr("Lettura date: {name}", name=os.path.basename(p))):
            raise InterruptedError
        d = None if is_video(p) else exifutil.read(p)["date"]
        out.append((d or mt, p))
    out.sort()
    return out


class CalendarWindow(QDialog):
    def __init__(self, root, settings, show_cb, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.root, self.settings, self.show_cb = root, settings, show_cb
        self.setWindowTitle(tr("Calendario – {folder}", folder=os.path.basename(root) or root))
        self.ck_sub = QCheckBox(tr("Includi sottocartelle"))
        self.ck_sub.setChecked(settings.value("calendar/sub", True, type=bool))
        b_scan = QPushButton(tr("Aggiorna"))
        b_scan.clicked.connect(self.rescan)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Data"), tr("Foto")])
        self.tree.setColumnWidth(0, 260)
        self.tree.itemClicked.connect(self._pick)
        self.tree.itemActivated.connect(self._pick)
        self.info = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.ck_sub)
        top.addStretch()
        top.addWidget(b_scan)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.tree)
        lay.addWidget(self.info)
        self.resize(420, 620)
        self.items = []

    def rescan(self):
        from .worker import run_with_progress
        self.settings.setValue("calendar/sub", self.ck_sub.isChecked())
        res = run_with_progress(self, tr("Lettura delle date…"), scan, self.root, self.ck_sub.isChecked())
        if res is None:
            return False
        self.items = res
        self._fill()
        return True

    def _fill(self):
        self.tree.clear()
        years = {}
        for ts, p in self.items:
            t = time.localtime(ts)
            years.setdefault(t.tm_year, {}).setdefault(t.tm_mon, {}).setdefault(t.tm_mday, []).append(p)
        for y in sorted(years, reverse=True):
            months = years[y]
            yi = QTreeWidgetItem(self.tree, [str(y), str(sum(len(d) for m in months.values() for d in m.values()))])
            yi.setData(0, Qt.ItemDataRole.UserRole, [p for m in months.values() for d in m.values() for p in d])
            for m in sorted(months, reverse=True):
                days = months[m]
                mi = QTreeWidgetItem(yi, [month_name(m), str(sum(len(d) for d in days.values()))])
                mi.setData(0, Qt.ItemDataRole.UserRole, [p for d in days.values() for p in d])
                for d in sorted(days, reverse=True):
                    di = QTreeWidgetItem(mi, [f"{d} {month_name(m).lower()} {y}", str(len(days[d]))])
                    di.setData(0, Qt.ItemDataRole.UserRole, days[d])
        if self.tree.topLevelItemCount():
            self.tree.topLevelItem(0).setExpanded(True)
        self.info.setText(tr("{n} foto in {y} anni", n=len(self.items), y=len(years)))

    def _pick(self, it, _col=0):
        paths = it.data(0, Qt.ItemDataRole.UserRole) or []
        if paths and self.show_cb:
            label = it.text(0)
            if it.parent() is not None and it.parent().parent() is None:
                label = f"{it.text(0)} {it.parent().text(0)}"
            self.show_cb(tr("Calendario: {when}", when=label) + f" ({len(paths)})", paths)
