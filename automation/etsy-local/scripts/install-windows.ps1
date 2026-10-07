
$ErrorActionPreference='Stop'
Write-Host "Installing CYZOR Etsy local automation..."
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  Write-Host "Node.js is required. Install Node 22 LTS, then rerun this script."
  exit 1
}
Set-Location $PSScriptRoot\..
npm install
npx playwright install chromium
Write-Host ""
Write-Host "Installed."
Write-Host "First run: npm run run -- tasks\example.json"
Write-Host "A Chrome window will open. Sign in to Etsy once and complete 2FA/CAPTCHA manually if Etsy asks."
