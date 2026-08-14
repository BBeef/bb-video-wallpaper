@echo off

cd /d "%~dp0"

echo [1/4] Check the virtual environment...

if not exist ".venv" (
    echo .venv not found. Creating virtual environment...

    python -m venv .venv
    .venv\Scripts\pip.exe install -r requirements.txt
)

echo.
echo [2/4] Building with PyInstaller...

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
echo [3/4] Copying VLC files...

xcopy /E /I /Y "VLC-lite" "dist\BB Video Wallpaper\VLC"
copy /Y "VLC-lite\libvlc.dll" "dist\BB Video Wallpaper\libvlc.dll"

echo.
echo [4/4] Cleaning up build files...

timeout /t 2 /nobreak >nul

if exist "build" (
    rmdir /S /Q "build"
)

if exist "BB Video Wallpaper.spec" (
    del /Q "BB Video Wallpaper.spec"
)

echo.
echo Build completed.
pause