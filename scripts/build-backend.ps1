# Builds the AFH Python backend into a self-contained one-folder app with PyInstaller:
#   desktop\backend-dist\afh-backend\afh-backend.exe --headless
# electron-builder then copies that folder into the installer as resources\backend (see
# desktop\package.json -> build.extraResources).
#
# Usage (from anywhere, Windows PowerShell 5.1 or newer):
#   powershell -ExecutionPolicy Bypass -File scripts\build-backend.ps1
#
# Requires the repo's .venv (created by AFH.bat or `python -m venv .venv`) with
# requirements.txt installed. PyInstaller is installed into that venv if it is missing.

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$DistPath = Join-Path $Root 'desktop\backend-dist'
$WorkPath = Join-Path $Root 'desktop\backend-build'
$Entry = Join-Path $Root 'run.py'
$WebDir = Join-Path $Root 'web'

if (-not (Test-Path $Python)) {
    throw "Python venv not found at $Python. Create it first: python -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt"
}
if (-not (Test-Path $WebDir)) {
    throw "web\ folder not found at $WebDir"
}

Write-Host "==> Using $Python"
# (no 2>$null here: PowerShell 5.1 turns native stderr into a terminating error under -ErrorAction Stop)
& $Python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "==> PyInstaller not found in the venv; installing..."
    & $Python -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }
}
& $Python -m PyInstaller --version
if ($LASTEXITCODE -ne 0) { throw "PyInstaller is not runnable" }

if (Test-Path (Join-Path $DistPath 'afh-backend')) {
    Write-Host "==> Removing previous build at $DistPath\afh-backend"
    Remove-Item -Recurse -Force (Join-Path $DistPath 'afh-backend')
}

# WEB_DIR in afh\api.py is Path(__file__).resolve().parent.parent / "web". Inside the frozen
# app afh\api.py lives (virtually) at <_internal>\afh\api.py, so that resolves to
# <_internal>\web, which is exactly where "--add-data web;web" puts the UI. No source change needed.
$PyArgs = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--clean',
    '--onedir',
    '--console',
    '--name', 'afh-backend',
    '--distpath', $DistPath,
    '--workpath', $WorkPath,
    '--specpath', $WorkPath,
    '--paths', $Root,
    '--add-data', "$WebDir;web",
    '--add-data', "$Root/afh/engine/data;afh/engine/data",
    # our own package + the MCP SDK (2.x: mcp, mcp_types, httpx2 are separate distributions)
    '--collect-submodules', 'afh',
    '--collect-submodules', 'mcp.client',
    '--collect-submodules', 'mcp.shared',
    '--collect-submodules', 'mcp_types',
    '--collect-submodules', 'httpx2',
    '--collect-submodules', 'httpx',
    '--collect-submodules', 'websockets',  # the browser tool imports it lazily
    '--copy-metadata', 'mcp',
    # uvicorn picks its implementation modules by string at runtime
    '--hidden-import', 'uvicorn.logging',
    '--hidden-import', 'uvicorn.loops.auto',
    '--hidden-import', 'uvicorn.loops.asyncio',
    '--hidden-import', 'uvicorn.protocols.http.auto',
    '--hidden-import', 'uvicorn.protocols.http.h11_impl',
    '--hidden-import', 'uvicorn.protocols.http.httptools_impl',
    '--hidden-import', 'uvicorn.protocols.websockets.auto',
    '--hidden-import', 'uvicorn.protocols.websockets.websockets_impl',
    '--hidden-import', 'uvicorn.protocols.websockets.wsproto_impl',
    '--hidden-import', 'uvicorn.lifespan.on',
    '--hidden-import', 'uvicorn.lifespan.off',
    '--hidden-import', 'anyio._backends._asyncio',
    '--hidden-import', 'fastapi',
    '--hidden-import', 'pydantic',
    '--hidden-import', 'zstandard',
    '--hidden-import', 'qrcode',
    # the desktop shell is Electron now; never pull pywebview or Tk into the exe
    '--exclude-module', 'webview',
    '--exclude-module', 'tkinter',
    '--exclude-module', '_tkinter',
    $Entry
)

Write-Host "==> Building afh-backend (this takes a minute or two)..."
& $Python @PyArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)" }

$Exe = Join-Path $DistPath 'afh-backend\afh-backend.exe'
$Web = Join-Path $DistPath 'afh-backend\_internal\web\index.html'
if (-not (Test-Path $Exe)) { throw "Build finished but $Exe is missing" }
if (-not (Test-Path $Web)) { throw "Build finished but the UI was not bundled ($Web is missing)" }

$SizeMB = [math]::Round(((Get-ChildItem -Recurse (Join-Path $DistPath 'afh-backend') | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host ""
Write-Host "==> Backend built: $Exe ($SizeMB MB)"
Write-Host "    Smoke test:  `$env:AFH_HOME='C:\temp\afh-test'; & '$Exe' --headless"
