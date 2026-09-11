# Buduje Ciach.exe (jednoplikowy, bez konsoli) i kopiuje go do folderu projektu.
# Uruchom:  powershell -ExecutionPolicy Bypass -File .\build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\venv\Scripts\python.exe")) {
    Write-Host "Tworzę venv..."
    python -m venv venv
}
$py = ".\venv\Scripts\python.exe"

Write-Host "Instaluję zależności..."
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt

# ffmpeg / ffprobe: kopiuj obok skryptu, jeśli jeszcze ich tu nie ma
foreach ($tool in @("ffmpeg", "ffprobe")) {
    if (-not (Test-Path ".\$tool.exe")) {
        $cmd = Get-Command $tool -ErrorAction SilentlyContinue
        if ($null -eq $cmd) { throw "Nie znaleziono $tool w PATH. Zainstaluj: winget install Gyan.FFmpeg" }
        Write-Host "Kopiuję $($cmd.Source)"
        Copy-Item $cmd.Source ".\$tool.exe"
    }
}

Write-Host "Generuję ikonę..."
& $py make_icon.py

Write-Host "Buduję exe (PyInstaller)..."
if (Test-Path ".\build") { Remove-Item -Recurse -Force ".\build" }
if (Test-Path ".\dist") { Remove-Item -Recurse -Force ".\dist" }
& $py -m PyInstaller --noconfirm --clean --onefile --noconsole `
    --name Ciach --icon icon.ico `
    --add-data "ui;ui" `
    --add-binary "ffmpeg.exe;." `
    --add-binary "ffprobe.exe;." `
    ciach.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller zakończył się błędem" }

Copy-Item ".\dist\Ciach.exe" ".\Ciach.exe" -Force
$mb = [math]::Round((Get-Item ".\Ciach.exe").Length / 1MB)
Write-Host "Gotowe: $PSScriptRoot\Ciach.exe ($mb MB)"
