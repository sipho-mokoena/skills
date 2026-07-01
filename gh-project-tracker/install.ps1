param(
    [string]$Dir = "$env:USERPROFILE\.agents\skills\gh-project-tracker"
)

# gh-project-tracker installer — copies skill files to ~/.agents/skills/
# Usage: .\install.ps1 [-Dir <path>]

Write-Host "Checking prerequisites..." -ForegroundColor Cyan

$gh = Get-Command "gh" -ErrorAction SilentlyContinue
if (-not $gh) {
    Write-Host "ERROR: 'gh' CLI not found. Install from https://cli.github.com/" -ForegroundColor Red
    exit 1
}

$uv = Get-Command "uv" -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "ERROR: 'uv' not found. Install from https://docs.astral.sh/uv/" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Copy-Item -Force "$ScriptDir\SKILL.md" "$Dir\"
Copy-Item -Force "$ScriptDir\project.py" "$Dir\"

Write-Host "Installed gh-project-tracker skill to:" -ForegroundColor Green
Write-Host "  $Dir" -ForegroundColor Green
Write-Host ""
Write-Host "Install via npx (Vercel skills ecosystem):" -ForegroundColor Cyan
Write-Host "  npx skills add sipho-mokoena/skills --skill gh-project-tracker" -ForegroundColor Cyan
