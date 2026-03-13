Param(
    [string]$PythonExe = ".venv/Scripts/python.exe"
)

$ErrorActionPreference = "Stop"

if (!(Test-Path $PythonExe)) {
    throw "Python executable not found: $PythonExe"
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -e .
& $PythonExe -m pip install pyinstaller

& $PythonExe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name auto-volume-ducker `
    --icon NONE `
    --hidden-import pystray `
    --hidden-import pystray._win32 `
    --hidden-import PIL.Image `
    --hidden-import PIL.ImageDraw `
    --collect-submodules pystray `
    --onedir `
    main.py

Write-Host "Build done. EXE folder: dist/auto-volume-ducker"
Write-Host "Put config.json next to dist/auto-volume-ducker/auto-volume-ducker.exe"
