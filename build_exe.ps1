# build_exe.ps1 — Build a Windows executable using PyInstaller
# Usage: Open PowerShell, activate your venv, then run:
#   .\build_exe.ps1

param(
    [string]$Name = 'cbz_to_epub',
    [switch]$OneFile = $true
)

Write-Host "Preparing build for $Name"

# Ensure pyinstaller is installed in the active environment
Write-Host "Installing/ensuring PyInstaller is available..."
python -m pip install --upgrade pip
python -m pip install pyinstaller --quiet

# Prepare add-data arguments (Windows format: "source;dest")
$addData = @(
    "scene;scene",
    "assets;assets",
    "ui;ui",
    "README.md;."
)

# Build the --add-data options string
$addDataArgs = $addData | ForEach-Object { "--add-data `"$_`"" } | Out-String
$addDataArgs = $addDataArgs -replace "\r?\n"," "

# Choose single-file or onedir
if ($OneFile) {
    $oneFileFlag = "--onefile --noconsole"
} else {
    $oneFileFlag = "--noconsole"
}

# Windows PyInstaller command
$cmd = "pyinstaller --noconfirm --clean $oneFileFlag $addDataArgs --name $Name main.py"
Write-Host "Running: $cmd"

# Execute
iex $cmd

Write-Host "Build finished. Check the 'dist' folder for the output executable or folder."
Write-Host "Notes: Calibre (ebook-convert) is NOT bundled and must be installed on target machines."