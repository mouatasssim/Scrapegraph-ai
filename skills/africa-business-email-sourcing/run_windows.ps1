param(
    [Parameter(Mandatory=$false)]
    [string]$Targets = "skills\africa-business-email-sourcing\targets_africa_business_maroc.csv",

    [Parameter(Mandatory=$false)]
    [string]$Out = "outputs\africa_business_emails.csv",

    [Parameter(Mandatory=$false)]
    [string]$JsonOut = "outputs\africa_business_emails.json",

    [Parameter(Mandatory=$false)]
    [int]$Workers = 4,

    [Parameter(Mandatory=$false)]
    [int]$MaxPages = 60,

    [Parameter(Mandatory=$false)]
    [int]$MaxDepth = 3,

    [switch]$RenderJs
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
Set-Location $RepoRoot

$Python = ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run skills\africa-business-email-sourcing\bootstrap_windows.ps1 first."
}

$ArgsList = @(
    "skills\africa-business-email-sourcing\scripts\email_sourcing.py",
    "--targets", $Targets,
    "--out", $Out,
    "--json-out", $JsonOut,
    "--workers", $Workers,
    "--max-pages", $MaxPages,
    "--max-depth", $MaxDepth
)

if ($RenderJs) {
    $ArgsList += "--render-js"
}

& $Python @ArgsList
