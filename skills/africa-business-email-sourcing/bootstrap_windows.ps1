$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $RepoRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating Python 3.12 virtual environment..."
    py -3.12 -m venv .venv
}

$Python = ".venv\Scripts\python.exe"

& $Python -m pip install --upgrade pip
& $Python -m pip install -e .
& $Python -m pip install -r "skills\africa-business-email-sourcing\requirements.txt"
& $Python -m playwright install chromium

Write-Host ""
Write-Host "AFRICA BUSINESS email sourcing stack is ready."
Write-Host "Next: edit targets.example.csv or provide your own targets CSV, then run run_windows.ps1."
