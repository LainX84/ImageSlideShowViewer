#!/bin/sh
# Crea il programma per macOS (dist/Image SlideShow Viewer.app) o Linux (dist/ImageSlideShowViewer/).
set -e
cd "$(dirname "$0")"
python3 -m pip install --upgrade -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --clean packaging/ImageSlideShowViewer.spec
rm -rf build
echo
echo "Fatto: guarda nella cartella dist/"
