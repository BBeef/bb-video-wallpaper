@echo off

cd /d "%~dp0"

echo [1/3] Check the virtual environment...

if not exist ".venv" (
    echo .venv not found. Creating virtual environment...

    python -m venv .venv
    .venv\Scripts\pip.exe install -r requirements.txt
)

echo.
echo [2/3] Building with PyInstaller...

.venv\Scripts\pyinstaller.exe --noconfirm --onedir --noconsole --uac-admin ^
 --icon=icon/bb-video-wallpaper.ico ^
 --name="BB Video Wallpaper" ^
 --add-data "icon;icon" ^
 bb-video-wallpaper.py

if errorlevel 1 (
    echo PyInstaller failed.
    pause
    exit /b 1
)

echo.
echo [3/3] Copying VLC files...

xcopy /E /I /Y "VLC-lite" "dist\BB Video Wallpaper\VLC"
copy /Y "libvlc.dll" "dist\BB Video Wallpaper\libvlc.dll"

echo.
echo Build completed.
pause