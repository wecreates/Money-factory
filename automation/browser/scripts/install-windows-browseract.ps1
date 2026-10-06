$ErrorActionPreference = 'Stop'
Write-Host 'CYZOR BrowserAct setup'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host 'Installing uv...'
  irm https://astral.sh/uv/install.ps1 | iex
  $env:Path = "$HOME\.local\bin;$env:Path"
}
uv tool install browser-act-cli --python 3.12
browser-act --version
Write-Host 'BrowserAct installed. You can now use the same CYZOR task files locally.'
