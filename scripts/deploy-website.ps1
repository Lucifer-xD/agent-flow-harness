# Deploy the AFH website to the VPS (https://agenflowharness.com, proxied by Cloudflare).
#
#   powershell -ExecutionPolicy Bypass -File scripts/deploy-website.ps1
#
# Packs website/ (pages, SDKs, downloads/ with the installer and latest.yml, plus the installer's
# .blockmap from desktop/dist), unpacks it into /var/www/afh, keeps only the current installer,
# and installs deploy/afh-website.nginx as its own nginx site — reloaded only if `nginx -t` passes.
# Uses this computer's SSH key for user@your-server.

$ErrorActionPreference = "Continue"  # ssh/tar write progress to stderr; exit codes are checked instead
$root = Split-Path -Parent $PSScriptRoot
$hostname = "user@your-server"
$ssh = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
$site = "/var/www/afh"

$website = Join-Path $root "website"
$downloads = Join-Path $website "downloads"
$installer = Get-ChildItem $downloads -Filter "AFH-Setup-*.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
if (-not $installer) { throw "No installer in website/downloads - build a release first" }
$map = Join-Path $root ("desktop\dist\" + $installer.Name + ".blockmap")
if (Test-Path $map) { Copy-Item $map $downloads -Force }  # lets the updater fetch only what changed

$tmp = Join-Path $env:TEMP "afh-website.tgz"
Write-Host ("==> Packing website ({0}, {1:N0} MB installer)" -f $installer.Name, ($installer.Length / 1MB))
# The pages link styles and scripts under /v/<stamp>/ (nginx serves the same files there), so each
# deploy gets new addresses and nobody sees new pages with yesterday's cached CSS. The rewrite
# happens on a staged copy of the pages; the repo keeps plain /styles.css links.
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$stage = Join-Path $env:TEMP "afh-website-pages"
Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $stage | Out-Null
foreach ($page in Get-ChildItem $website -Filter "*.html" | Where-Object { -not $_.Name.StartsWith("lab") }) {  # lab*.html: local test pages only
  $html = [IO.File]::ReadAllText($page.FullName)
  $html = $html -replace '(href|src)="/((?:[\w-]+/)*[\w-]+\.(?:css|js))(?:\?v=\w+)?"', ('$1="/v/' + $stamp + '/$2"')
  # module imports (import "/js/page.js", and the imports inside the modules) follow the same stamp
  $html = $html -replace '"imports": \{', ('"imports": {' + "`n      ""/js/"": ""/v/$stamp/js/"",")
  [IO.File]::WriteAllText((Join-Path $stage $page.Name), $html, (New-Object Text.UTF8Encoding $false))
}
$entries = @(Get-ChildItem $website -Name | Where-Object { $_ -ne "README.md" -and -not $_.StartsWith(".") -and -not $_.EndsWith(".html") })
$pages = @(Get-ChildItem $stage -Name)
# Windows tar: Git's GNU tar reads "C:" as a remote host
& (Join-Path $env:SystemRoot "System32\tar.exe") -czf $tmp -C $website @entries -C $stage @pages
if ($LASTEXITCODE -ne 0) { throw "tar failed" }
Remove-Item $stage -Recurse -Force

Write-Host "==> Uploading"
scp @ssh -q $tmp (Join-Path $root "deploy\afh-website.nginx") "${hostname}:/tmp/"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }

Write-Host "==> Installing on the VPS"
$remote = @"
set -e
sudo mkdir -p $site.new
sudo tar -xzf /tmp/afh-website.tgz -C $site.new
sudo chown -R www-data:www-data $site.new
sudo find $site.new -type d -exec chmod 755 {} +
sudo find $site.new -type f -exec chmod 644 {} +
if [ -d $site ]; then sudo mv $site $site.old; fi
sudo mv $site.new $site
sudo rm -rf $site.old /tmp/afh-website.tgz
sudo install -m 644 /tmp/afh-website.nginx /etc/nginx/sites-available/afh-website
rm -f /tmp/afh-website.nginx
sudo ln -sf /etc/nginx/sites-available/afh-website /etc/nginx/sites-enabled/afh-website
if sudo nginx -t 2>/tmp/afh-nginx-test; then
  sudo systemctl reload nginx
  echo "nginx reloaded"
else
  cat /tmp/afh-nginx-test
  sudo rm -f /etc/nginx/sites-enabled/afh-website
  echo "nginx config test failed - site disabled, other sites untouched" >&2
  exit 1
fi
ls -la $site/downloads
"@
# Sent as a file, not piped: PowerShell's pipe would prepend a byte-order mark and CR line ends.
$script = Join-Path $env:TEMP "afh-install.sh"
[IO.File]::WriteAllText($script, ($remote -replace "`r", ""), (New-Object Text.UTF8Encoding $false))
scp @ssh -q $script "${hostname}:/tmp/afh-install.sh"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }
ssh @ssh $hostname 'bash /tmp/afh-install.sh; s=$?; rm -f /tmp/afh-install.sh; exit $s'
if ($LASTEXITCODE -ne 0) { throw "remote install failed" }
Remove-Item $script -ErrorAction SilentlyContinue
Remove-Item $tmp -ErrorAction SilentlyContinue
Write-Host "Done: https://agenflowharness.com" -ForegroundColor Green
