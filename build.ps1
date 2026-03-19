$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

Write-Host "=== Installing Python build dependencies ==="
pip install pyinstaller

Write-Host "=== Installing frontend dependencies ==="
Set-Location frontend
npm install

Write-Host "=== Building React frontend ==="
npm run build
Set-Location $scriptDir

Write-Host "=== Packaging with PyInstaller ==="
pyinstaller --clean --noconfirm cursor-view.spec

Write-Host ""
Write-Host "=== Build complete ==="
Write-Host "Executable: dist\cursor-view.exe"
