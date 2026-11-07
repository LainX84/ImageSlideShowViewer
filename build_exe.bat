@echo off
rem Builds dist\ImageSlideShowViewer\ImageSlideShowViewer.exe with PyInstaller.
cd /d "%~dp0"
echo Installing / updating PySide6 and PyInstaller...
python -m pip install --upgrade -r requirements.txt pyinstaller || (pause & exit /b 1)
python -m PyInstaller --noconfirm --clean --windowed ^
  --name ImageSlideShowViewer ^
  --icon isv\icon.ico ^
  --add-data "isv\icon.ico;isv" ^
  image_slideshow_viewer.pyw || (pause & exit /b 1)
rem "build" only holds temporary files: remove it to avoid confusion.
rmdir /s /q build 2>nul
del /q ImageSlideShowViewer.spec 2>nul
echo.
echo Done! The program is in:  dist\ImageSlideShowViewer\ImageSlideShowViewer.exe
echo Move the whole dist\ImageSlideShowViewer folder (not just the .exe) wherever you like.
explorer "dist\ImageSlideShowViewer"
pause
