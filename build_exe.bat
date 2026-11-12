@echo off
rem Crea dist\ImageSlideShowViewer\ImageSlideShowViewer.exe con PyInstaller.
cd /d "%~dp0"
echo Installazione / aggiornamento delle librerie e di PyInstaller...
python -m pip install --upgrade -r requirements.txt pyinstaller || (pause & exit /b 1)
python -m PyInstaller --noconfirm --clean packaging\ImageSlideShowViewer.spec || (pause & exit /b 1)
rem "build" contiene solo file temporanei
rmdir /s /q build 2>nul
echo.
echo Fatto! Il programma e' in:  dist\ImageSlideShowViewer\ImageSlideShowViewer.exe
echo Sposta tutta la cartella dist\ImageSlideShowViewer (non solo l'.exe) dove preferisci.
explorer "dist\ImageSlideShowViewer"
pause
