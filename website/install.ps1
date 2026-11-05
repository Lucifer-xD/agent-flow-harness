# Installs AFH's terminal app on Windows, for this user only (no admin):
#
#   irm https://agentflowharness.com/install.ps1 | iex
#
# It downloads the newest release from GitHub, checks its SHA-256, unpacks it to %USERPROFILE%\.afh\cli
# and puts `afh` on your PATH. `afh uninstall` undoes this; your threads, settings and keys stay.
#
# Only .NET calls do the work: Windows' default execution policy stops script modules from loading,
# and Expand-Archive and Get-FileHash live in those. It also keeps PowerShell's progress box away.

function Install-Afh {
    $base = if ($env:AFH_DOWNLOAD_BASE) { $env:AFH_DOWNLOAD_BASE } else { 'https://github.com/Lucifer-xD/agent-flow-harness/releases/latest/download' }
    $root = if ($env:AFH_HOME) { $env:AFH_HOME } else { [IO.Path]::Combine($HOME, '.afh') }

    # The work runs beside the animation. progress: 0 to 1 while downloading, then phase says unpack.
    $state = [hashtable]::Synchronized(@{ progress = 0.0; phase = 'download'; version = ''; failed = '' })
    $work = {
        param($state, $base, $root)
        $ErrorActionPreference = 'Stop'
        $asset = 'afh-windows-x64.zip'
        $temp = [IO.Path]::Combine([IO.Path]::GetTempPath(), "afh-install-$PID")
        $versions = [IO.Path]::Combine($root, 'cli', 'versions')
        $staging = [IO.Path]::Combine($versions, ".new-$PID")

        function Get-Url($url, $path, $share) {
            $response = ([Net.WebRequest]::Create($url)).GetResponse()
            $in = $response.GetResponseStream()
            $out = [IO.File]::Create($path)
            try {
                $buffer = New-Object byte[] 262144
                $total = $response.ContentLength
                $got = 0
                while (($n = $in.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $out.Write($buffer, 0, $n)
                    $got += $n
                    if ($share -and $total -gt 0) { $state.progress = $share * $got / $total }
                }
            }
            finally { $out.Close(); $in.Close(); $response.Close() }
        }

        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            [void][IO.Directory]::CreateDirectory($temp)
            [void][IO.Directory]::CreateDirectory($versions)
            $zip = [IO.Path]::Combine($temp, $asset)
            $sums = [IO.Path]::Combine($temp, 'afh-checksums.txt')
            Get-Url "$base/afh-checksums.txt" $sums 0
            Get-Url "$base/$asset" $zip 0.8
            $state.phase = 'unpack'

            $want = ''
            foreach ($line in [IO.File]::ReadAllLines($sums)) {
                if ($line.Contains($asset)) { $want = ($line -split '\s+')[0].ToLower(); break }
            }
            if (-not $want) { throw "No checksum for $asset" }
            $file = [IO.File]::OpenRead($zip)
            try { $hash = [Security.Cryptography.SHA256]::Create().ComputeHash($file) } finally { $file.Close() }
            if ([BitConverter]::ToString($hash).Replace('-', '').ToLower() -ne $want) { throw 'The download did not match its checksum, so nothing was installed.' }

            [void][Reflection.Assembly]::LoadWithPartialName('System.IO.Compression.FileSystem')
            if ([IO.Directory]::Exists($staging)) { [IO.Directory]::Delete($staging, $true) }
            [IO.Compression.ZipFile]::ExtractToDirectory($zip, $staging)
            $said = & ([IO.Path]::Combine($staging, 'afh', 'afh.exe')) --version
            $version = ("$said" -replace '^afh\s+', '').Trim()
            if ($LASTEXITCODE -ne 0 -or -not $version) { throw 'The downloaded program did not start. Antivirus software can block new programs: check its quarantine.' }

            $target = [IO.Path]::Combine($versions, $version)
            if ([IO.Directory]::Exists($target)) { [IO.Directory]::Delete($target, $true) }
            [IO.Directory]::Move($staging, $target)

            $bin = [IO.Path]::Combine($root, 'bin')
            [void][IO.Directory]::CreateDirectory($bin)
            $exe = [IO.Path]::Combine($target, 'afh', 'afh.exe')
            [IO.File]::WriteAllText([IO.Path]::Combine($bin, 'afh.cmd'), "@echo off`r`n`"$exe`" %*`r`n", (New-Object Text.UTF8Encoding $false))

            # the raw value: going through [Environment] would turn every %VARIABLE% in it into a fixed path
            $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
            $path = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
            if (-not (($path -split ';') -contains $bin)) {
                $kind = if ($path) { $key.GetValueKind('Path') } else { 'ExpandString' }
                $joined = if ($path) { $path.TrimEnd(';') + ';' + $bin } else { $bin }
                $key.SetValue('Path', $joined, $kind)
                [Environment]::SetEnvironmentVariable('AFH_PATH_CHANGED', $null, 'User')  # tells open programs the PATH changed
            }
            $key.Close()
            if (-not (($env:Path -split ';') -contains $bin)) { $env:Path = "$env:Path;$bin" }
            $state.version = $version
        }
        catch {
            $state.failed = $_.Exception.Message
        }
        finally {
            foreach ($folder in @($temp, $staging)) {
                try { if ([IO.Directory]::Exists($folder)) { [IO.Directory]::Delete($folder, $true) } } catch { }
            }
        }
    }

    # The logo, as on the app's start screen. Letters stand in for the block characters so this file
    # stays plain ASCII however it reaches PowerShell.
    $logo = foreach ($row in ' #####7 #######7##7  ##7', '##r==##7##r====J##|  ##|', '#######|#####7  #######|', '##r==##|##r==J  ##r==##|', '##|  ##|##|     ##|  ##|', 'L=J  L=JL=J     L=J  L=J') {
        $row.Replace('#', [string][char]0x2588).Replace('r', [string][char]0x2554).Replace('7', [string][char]0x2557).Replace('L', [string][char]0x255A).Replace('J', [string][char]0x255D).Replace('=', [string][char]0x2550).Replace('|', [string][char]0x2551)
    }
    $width = 24
    $esc = [string][char]27
    $dim = "$esc[38;2;120;114;108m"
    $reset = "$esc[0m"
    $color = New-Object string[] $width
    $shine = New-Object string[] $width
    for ($c = 0; $c -lt $width; $c++) {  # the brand: amber, orange, pink
        $t = $c / ($width - 1)
        if ($t -lt 0.5) { $u = $t * 2; $r = 245 + 10 * $u; $g = 166 - 60 * $u; $b = 35 + 7 * $u }
        else { $u = ($t - 0.5) * 2; $r = 255; $g = 106 - 45 * $u; $b = 42 + 71 * $u }
        $color[$c] = "$esc[38;2;$([int]$r);$([int]$g);$([int]$b)m"
        $shine[$c] = "$esc[38;2;$([int](($r + 510) / 3));$([int](($g + 510) / 3));$([int](($b + 510) / 3))m"
    }

    function Show-Frame($fill, $tick, $status, $first) {
        $text = New-Object Text.StringBuilder
        if (-not $first) { [void]$text.Append("$esc[7A`r") }
        $edge = $fill * $width
        $sweep = ($tick % 44) - 10
        foreach ($row in $logo) {
            [void]$text.Append("  ")
            for ($c = 0; $c -lt $width; $c++) {
                if ($row[$c] -ne ' ') {
                    if ($c -ge $edge) { [void]$text.Append($dim) }
                    elseif ([Math]::Abs($c - $sweep) -le 1) { [void]$text.Append($shine[$c]) }
                    else { [void]$text.Append($color[$c]) }
                }
                [void]$text.Append($row[$c])
            }
            [void]$text.Append("$esc[K`r`n")
        }
        [void]$text.Append("$reset$esc[K`r`n  $status$esc[K")
        [Console]::Out.Write($text.ToString())
    }

    $animate = (-not [Console]::IsOutputRedirected) -and $Host.UI.SupportsVirtualTerminal
    $encoding = [Console]::OutputEncoding
    $job = [powershell]::Create().AddScript($work.ToString()).AddArgument($state).AddArgument($base).AddArgument($root)
    try {
        if ($animate) {
            [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false
            [Console]::CursorVisible = $false
            [Console]::Out.Write("`r`n")
        }
        else { [Console]::WriteLine('Installing AFH...') }

        $running = $job.BeginInvoke()
        $shown = 0.0
        $tick = 0
        while (-not $running.IsCompleted) {
            if ($animate) {
                if ($state.phase -eq 'unpack') { $shown += (0.97 - $shown) * 0.02 }
                else { $shown += ($state.progress - $shown) * 0.25 }
                Show-Frame $shown $tick "Installing AFH  $([int]($shown * 100))%" ($tick -eq 0)
                $tick++
            }
            [Threading.Thread]::Sleep(70)
        }

        if ($state.failed) {
            if ($animate) { Show-Frame $shown $tick "$esc[31mAFH wasn't installed: $($state.failed)$reset" ($tick -eq 0); [Console]::Out.Write("`r`n") }
            else { [Console]::WriteLine("AFH wasn't installed: $($state.failed)") }
            return
        }
        if ($animate) {
            Show-Frame 1 44 "$esc[32mAFH $($state.version) is ready.$reset" ($tick -eq 0)
            [Console]::Out.Write("`r`n`r`n  Go to a project folder and type: afh`r`n  $($dim)If this window says afh is not recognized, open a new terminal.$reset`r`n`r`n")
        }
        else {
            [Console]::WriteLine("AFH $($state.version) is installed.")
            [Console]::WriteLine('Go to a project folder and type: afh')
            [Console]::WriteLine('If this window says afh is not recognized, open a new terminal.')
        }
    }
    finally {
        if ($animate) {
            [Console]::Out.Write($reset)
            [Console]::CursorVisible = $true
            [Console]::OutputEncoding = $encoding
        }
        if ($running -and -not $running.IsCompleted) { [void]$job.BeginStop($null, $null) }
    }
}

Install-Afh
