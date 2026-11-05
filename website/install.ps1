# Installs AFH's terminal app on Windows, for this user only (no admin):
#
#   irm https://agentflowharness.com/install.ps1 | iex
#
# It downloads the newest release from GitHub, checks its SHA-256, unpacks it to %USERPROFILE%\.afh\cli
# and puts `afh` on your PATH. `afh uninstall` undoes this; your threads, settings and keys stay.

function Install-Afh {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'  # the progress bar makes Windows PowerShell's downloads crawl
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $base = if ($env:AFH_DOWNLOAD_BASE) { $env:AFH_DOWNLOAD_BASE } else { 'https://github.com/Lucifer-xD/agent-flow-harness/releases/latest/download' }
    $home_ = if ($env:AFH_HOME) { $env:AFH_HOME } else { Join-Path $HOME '.afh' }
    $asset = 'afh-windows-x64.zip'
    $versions = Join-Path $home_ 'cli\versions'
    $staging = Join-Path $versions ".new-$PID"
    $temp = Join-Path ([IO.Path]::GetTempPath()) "afh-install-$PID"

    New-Item -ItemType Directory -Force $temp, $versions | Out-Null
    try {
        Write-Host 'Downloading AFH...'
        $zip = Join-Path $temp $asset
        $sums = Join-Path $temp 'afh-checksums.txt'
        Invoke-WebRequest "$base/$asset" -OutFile $zip -UseBasicParsing
        Invoke-WebRequest "$base/afh-checksums.txt" -OutFile $sums -UseBasicParsing

        $line = Get-Content $sums | Where-Object { $_ -match [regex]::Escape($asset) } | Select-Object -First 1
        if (-not $line) { throw "No checksum for $asset" }
        $want = ($line -split '\s+')[0].ToLower()
        $got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
        if ($want -ne $got) { throw 'The download did not match its checksum, so nothing was installed.' }

        Write-Host 'Unpacking...'
        if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
        Expand-Archive $zip -DestinationPath $staging
        $version = (& (Join-Path $staging 'afh\afh.exe') --version) -replace '^afh\s+', ''
        if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'The downloaded program did not start. Antivirus software can block new programs: check its quarantine.' }

        $target = Join-Path $versions $version
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Move-Item $staging $target

        $bin = Join-Path $home_ 'bin'
        New-Item -ItemType Directory -Force $bin | Out-Null
        $exe = Join-Path $target 'afh\afh.exe'
        [IO.File]::WriteAllText((Join-Path $bin 'afh.cmd'), "@echo off`r`n`"$exe`" %*`r`n", (New-Object Text.UTF8Encoding $false))

        # the raw value: going through [Environment] would turn every %VARIABLE% in it into a fixed path
        $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
        $path = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
        if (-not (($path -split ';') -contains $bin)) {
            $kind = if ($path) { $key.GetValueKind('Path') } else { 'ExpandString' }
            $key.SetValue('Path', (($path.TrimEnd(';'), $bin | Where-Object { $_ }) -join ';'), $kind)
            [Environment]::SetEnvironmentVariable('AFH_PATH_CHANGED', $null, 'User')  # tells open programs the PATH changed
        }
        $key.Close()
        if (-not (($env:Path -split ';') -contains $bin)) { $env:Path = "$env:Path;$bin" }

        Write-Host ''
        Write-Host "AFH $version is installed." -ForegroundColor Green
        Write-Host 'Go to a project folder and type: afh'
        Write-Host 'If this window says afh is not recognized, open a new terminal.'
    }
    catch {
        Write-Host "AFH wasn't installed: $($_.Exception.Message)" -ForegroundColor Red
        if (Test-Path $staging) { Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue }
    }
    finally {
        Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    }
}

Install-Afh
