# Rebuilds the AFH desktop app and reinstalls it over the existing per-user install so an
# update can be tested end to end on this machine.
#
#   1. scripts\build-backend.ps1       (PyInstaller -> desktop\backend-dist\afh-backend)
#   2. npm run dist (in desktop\)      (electron-builder -> desktop\dist\AFH-Setup-<version>.exe)
#   3. Close the running app: "Agent Flow Harness" (Electron), afh-backend.exe and any
#      opencode.exe that was spawned by afh-backend. An unrelated `opencode serve --service`
#      process is left alone.
#   4. Run the installer silently (/S). electron-builder's NSIS installer keeps the previous
#      install directory and shortcuts. If the existing install is per-machine (HKLM /
#      Program Files) the installer is run elevated with /allusers, so expect one UAC prompt.
#   5. Locate the installed exe (HKCU then HKLM uninstall registry -> InstallLocation or the
#      UninstallString's folder, falling back to %LOCALAPPDATA%\Programs\Agent Flow Harness and
#      %ProgramFiles%\Agent Flow Harness) and print its path and version.
#
# Usage (Windows PowerShell 5.1 or newer, from anywhere):
#   powershell -ExecutionPolicy Bypass -File scripts\update-installed.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\update-installed.ps1 -Launch      # start the app afterwards
#   powershell -ExecutionPolicy Bypass -File scripts\update-installed.ps1 -SkipBuild   # reuse an existing installer
#
# Requires everything scripts\build-backend.ps1 and `npm run dist` need (.venv, node_modules).

[CmdletBinding()]
param(
    # Start the freshly installed app when done.
    [switch]$Launch,
    # Skip steps 1-2 and install whatever desktop\dist\AFH-Setup-<version>.exe already exists.
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$DesktopDir = Join-Path $Root 'desktop'
$BuildBackend = Join-Path $Root 'scripts\build-backend.ps1'
$PackageJson = Join-Path $DesktopDir 'package.json'
$AppName = 'Agent Flow Harness'
$AppExeName = "$AppName.exe"

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# ---- version -----------------------------------------------------------------------------------

if (-not (Test-Path $PackageJson)) { Fail "desktop\package.json not found at $PackageJson" }
$Version = (Get-Content $PackageJson -Raw | ConvertFrom-Json).version
if (-not $Version) { Fail "Could not read 'version' from $PackageJson" }
$Installer = Join-Path $DesktopDir "dist\AFH-Setup-$Version.exe"
Write-Host "AFH desktop version $Version (repo: $Root)"

# ---- 1 + 2: build -------------------------------------------------------------------------------

if ($SkipBuild) {
    Step "Skipping build (-SkipBuild)"
} else {
    if (-not (Test-Path $BuildBackend)) { Fail "build script not found: $BuildBackend" }
    Step "Building backend: $BuildBackend"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $BuildBackend
    if ($LASTEXITCODE -ne 0) { Fail "scripts\build-backend.ps1 failed (exit code $LASTEXITCODE). Fix the backend build before installing." }

    Step "Building installer: npm run dist (in $DesktopDir)"
    Push-Location $DesktopDir
    try {
        & npm run dist
        $npmExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($npmExit -ne 0) { Fail "npm run dist failed (exit code $npmExit). Fix the Electron build before installing." }
}

if (-not (Test-Path $Installer)) {
    Fail "Installer not found: $Installer`nCheck desktop\dist\ and desktop\package.json 'version'."
}
$installerSize = [math]::Round((Get-Item $Installer).Length / 1MB, 1)
Write-Host "Installer: $Installer ($installerSize MB)"

# ---- 3: close the running app -------------------------------------------------------------------

function Get-AfhProcesses {
    # Returns the Win32_Process rows that belong to a running AFH instance, in kill order:
    # Electron first (it tears down its own backend tree on exit), then backend, then opencode.
    $all = @(Get-CimInstance Win32_Process)
    $byPid = @{}
    foreach ($p in $all) { $byPid[[int]$p.ProcessId] = $p }

    $electron = @($all | Where-Object {
        $_.Name -ine 'afh-backend.exe' -and $_.Name -ine 'opencode.exe' -and (
            $_.Name -ieq $AppExeName -or
            ($_.ExecutablePath -and $_.ExecutablePath -like "*$AppName*")
        )
    })
    $backend = @($all | Where-Object { $_.Name -ieq 'afh-backend.exe' })
    $backendPids = @($backend | ForEach-Object { [int]$_.ProcessId })

    # opencode.exe whose parent chain reaches afh-backend.exe. `opencode serve --service` is a
    # standalone service that AFH did not start; never touch it.
    $opencode = @($all | Where-Object { $_.Name -ieq 'opencode.exe' } | Where-Object {
        $cmd = [string]$_.CommandLine
        if ($cmd -match '\bserve\b' -and $cmd -match '--service\b') { return $false }
        $seen = @{}
        $cur = $_
        while ($cur -and -not $seen.ContainsKey([int]$cur.ProcessId)) {
            $seen[[int]$cur.ProcessId] = $true
            $parentId = [int]$cur.ParentProcessId
            if ($backendPids -contains $parentId) { return $true }
            if ($parentId -le 0 -or -not $byPid.ContainsKey($parentId)) { return $false }
            $cur = $byPid[$parentId]
        }
        return $false
    })

    return [pscustomobject]@{ Electron = $electron; Backend = $backend; Opencode = $opencode }
}

function Stop-ProcessRows($rows, $force) {
    foreach ($row in $rows) {
        $procId = [int]$row.ProcessId
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if (-not $proc) { continue }
        if ($force) {
            Write-Host "    killing  $($row.Name) (pid $procId)"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        } else {
            # Only the Electron main process owns a window; renderer/GPU helpers carry --type=.
            if ([string]$row.CommandLine -match '--type=') { continue }
            Write-Host "    closing  $($row.Name) (pid $procId)"
            # WM_CLOSE to the Electron window: lets main.js save window state and kill its backend.
            # (no 2>&1: under -ErrorAction Stop, PS 5.1 turns redirected native stderr into a terminating error)
            & taskkill.exe /PID $procId | Out-Null
        }
    }
}

Step "Closing running app (if any)"
$found = Get-AfhProcesses
$total = $found.Electron.Count + $found.Backend.Count + $found.Opencode.Count
if ($total -eq 0) {
    Write-Host "    nothing running"
} else {
    # Graceful close of the Electron window(s) first; it kills its own backend tree on quit.
    Stop-ProcessRows $found.Electron $false
    $deadline = (Get-Date).AddSeconds(8)
    do {
        Start-Sleep -Milliseconds 300
        $found = Get-AfhProcesses
        $total = $found.Electron.Count + $found.Backend.Count + $found.Opencode.Count
    } while ($total -gt 0 -and (Get-Date) -lt $deadline)

    if ($total -gt 0) {
        # Whatever is left gets killed hard, opencode first so the backend cannot respawn it.
        Stop-ProcessRows $found.Opencode $true
        Stop-ProcessRows $found.Backend $true
        Stop-ProcessRows $found.Electron $true
        Start-Sleep -Seconds 1
    }
    $found = Get-AfhProcesses
    $total = $found.Electron.Count + $found.Backend.Count + $found.Opencode.Count
    if ($total -gt 0) { Fail "Could not stop all AFH processes; close the app manually and retry." }
    Write-Host "    app closed"
}

# ---- registry lookup (used before and after the install) ---------------------------------------

function Find-InstalledApp {
    # electron-builder's NSIS writes DisplayName "<productName> <version>" and often leaves
    # InstallLocation empty, so match by prefix and fall back to the UninstallString's folder.
    # HKCU = per-user install (the default), HKLM = the user picked "all users" in the installer.
    $hives = @(
        @{ Path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall'; PerMachine = $false },
        @{ Path = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall'; PerMachine = $true },
        @{ Path = 'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'; PerMachine = $true }
    )
    foreach ($hive in $hives) {
        $keys = @(Get-ChildItem $hive.Path -ErrorAction SilentlyContinue)
        foreach ($key in $keys) {
            $props = Get-ItemProperty $key.PSPath -ErrorAction SilentlyContinue
            if (-not $props) { continue }
            $name = [string]$props.DisplayName
            if ($name -ne $AppName -and $name -notlike "$AppName *") { continue }
            $dir = [string]$props.InstallLocation
            if (-not $dir -and $props.UninstallString -match '^"?([^"]+)"?') {
                $dir = Split-Path -Parent $Matches[1]
            }
            if (-not $dir) { continue }
            return [pscustomobject]@{
                Exe = Join-Path $dir $AppExeName
                DisplayVersion = [string]$props.DisplayVersion
                PerMachine = $hive.PerMachine
                Source = "registry $($hive.Path.Split(':')[0]) ($($key.PSChildName))"
            }
        }
    }
    foreach ($candidate in @(
        (Join-Path $env:LOCALAPPDATA "Programs\$AppName\$AppExeName"),
        (Join-Path $env:ProgramFiles "$AppName\$AppExeName")
    )) {
        if (Test-Path $candidate) {
            return [pscustomobject]@{
                Exe = $candidate
                DisplayVersion = $null
                PerMachine = ($candidate -like "$env:ProgramFiles*")
                Source = 'default install location'
            }
        }
    }
    return [pscustomobject]@{
        Exe = Join-Path $env:LOCALAPPDATA "Programs\$AppName\$AppExeName"
        DisplayVersion = $null
        PerMachine = $false
        Source = 'default install location (not found)'
    }
}

# ---- 4: install silently ------------------------------------------------------------------------

$previous = Find-InstalledApp
$installArgs = @('/S')
if ($previous.PerMachine) {
    # Existing install is per-machine (Program Files). The silent installer must run elevated and
    # be told explicitly to keep that mode; expect one UAC prompt.
    $installArgs += '/allusers'
    Step "Installing silently (per-machine, elevated): $Installer $($installArgs -join ' ')"
    $proc = Start-Process -FilePath $Installer -ArgumentList $installArgs -Verb RunAs -Wait -PassThru
} else {
    Step "Installing silently: $Installer $($installArgs -join ' ')"
    $proc = Start-Process -FilePath $Installer -ArgumentList $installArgs -Wait -PassThru
}
if ($proc.ExitCode -ne 0) { Fail "Installer exited with code $($proc.ExitCode)" }

# ---- 5: locate the installed exe ---------------------------------------------------------------

Step "Locating installed app"
$installed = Find-InstalledApp
if (-not (Test-Path $installed.Exe)) {
    Fail "Installed exe not found at $($installed.Exe) ($($installed.Source))"
}
$fileVersion = (Get-Item $installed.Exe).VersionInfo.ProductVersion
if (-not $fileVersion) { $fileVersion = (Get-Item $installed.Exe).VersionInfo.FileVersion }
Write-Host "Installed exe : $($installed.Exe)"
Write-Host "Found via     : $($installed.Source)"
if ($installed.DisplayVersion) { Write-Host "Registry ver  : $($installed.DisplayVersion)" }
Write-Host "File version  : $fileVersion"
Write-Host "Built version : $Version"

if ($Launch) {
    Step "Launching $AppName"
    Start-Process -FilePath $installed.Exe -WorkingDirectory (Split-Path -Parent $installed.Exe)
}

Write-Host "Done." -ForegroundColor Green
