"""Finestra "Informazioni su"."""
import platform

import PySide6
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout

from . import APP_NAME, AUTHOR, GITHUB_URL, LICENSE, REPO_URL, __version__
from .i18n import tr


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Informazioni su {app}", app=APP_NAME))
        icon = QLabel()
        ic = QApplication.windowIcon()
        if not ic.isNull():
            icon.setPixmap(ic.pixmap(64, 64))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        text = QLabel(
            f"<h2 style='margin-bottom:0'>{APP_NAME}</h2>"
            f"<p style='margin-top:2px'><b>{tr('Versione')} {__version__}</b></p>"
            f"<p>{tr('Visualizzatore di immagini e slideshow in stile ACDSee, con browser a miniature, archivi CBZ/ZIP e operazioni in blocco.')}</p>"
            f"<p>{tr('Autore')}: <b>{AUTHOR}</b><br>"
            f"GitHub: <a href='{GITHUB_URL}'>{GITHUB_URL}</a><br>"
            f"{tr('Progetto')}: <a href='{REPO_URL}'>{REPO_URL}</a><br>"
            f"{tr('Licenza')}: {LICENSE}</p>"
            f"<p style='color:gray'>Python {platform.python_version()} · "
            f"PySide6 {PySide6.__version__} · Qt {qVersion()} · {platform.system()} {platform.release()}</p>")
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setOpenExternalLinks(True)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        row = QHBoxLayout()
        row.addWidget(icon)
        row.addWidget(text, 1)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(bb)
        self.setMinimumWidth(460)
