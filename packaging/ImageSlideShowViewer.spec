# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: un'unica configurazione per Windows, macOS e Linux.
#   pyinstaller --noconfirm --clean packaging/ImageSlideShowViewer.spec
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
NAME = "ImageSlideShowViewer"

hidden = ["PySide6.QtMultimedia", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPrintSupport",
          "PySide6.QtNetwork", "sqlite3"]
datas = [(os.path.join(ROOT, "isv", "icon.ico"), "isv")]
binaries = []
for pkg in ("pillow_heif", "pillow_jxl", "rawpy", "py7zr", "rarfile", "numpy", "certifi"):
    try:
        __import__(pkg)
    except ImportError:
        print(f"[spec] {pkg} non installato: il formato relativo non sarà incluso")
        continue
    hidden.append(pkg)
    try:
        binaries += collect_dynamic_libs(pkg)
        datas += collect_data_files(pkg)
    except Exception as e:  # noqa: BLE001
        print(f"[spec] {pkg}: {e}")

a = Analysis(
    [os.path.join(ROOT, "image_slideshow_viewer.pyw")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    # le librerie NVIDIA non si includono: il programma le scarica se trova una scheda NVIDIA
    excludes=["tkinter", "nvidia", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick3D", "PySide6.QtCharts", "PySide6.QtDataVisualization"],
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "win32":
    icon = os.path.join(ROOT, "isv", "icon.ico")
else:
    icon = os.path.join(ROOT, "docs", "icon.png")   # convertita in .icns su macOS (serve Pillow)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    icon=icon,
    upx=False,
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME, upx=False)

if sys.platform == "darwin":
    sys.path.insert(0, ROOT)
    from isv import __version__
    app = BUNDLE(
        coll,
        name="Image SlideShow Viewer.app",
        icon=icon,
        bundle_identifier="io.github.lainx84.imageslideshowviewer",
        version=__version__,
        info_plist={
            "CFBundleName": "Image SlideShow Viewer",
            "CFBundleDisplayName": "Image SlideShow Viewer",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.photography",
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "Image",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["public.image", "public.movie", "public.zip-archive",
                                       "com.rarlab.rar-archive", "org.7-zip.7-zip-archive"],
            }],
        },
    )
