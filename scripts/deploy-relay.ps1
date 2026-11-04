# Deploy the AFH relay (accounts and remote access for the phone apps) to the VPS.
#
#   powershell -ExecutionPolicy Bypass -File scripts/deploy-relay.ps1
#
# Copies relay/ to /opt/afh-relay, keeps its own venv there, runs it as the afh-relay system user
# under systemd (deploy/afh-relay.service, 127.0.0.1:8840) and checks it answers. The accounts
# database lives in /var/lib/afh-relay and is never touched by a deploy. nginx routes to it from
# the agentflowharness.com site (deploy/afh-website.nginx, installed by deploy-website.ps1).
# Who may open /admin is set on the server, in /etc/afh-relay.env, and a deploy leaves it alone.

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$serverFile = Join-Path $root "deploy\server.local"
$hostname = if ($env:AFH_SERVER) { $env:AFH_SERVER } elseif (Test-Path $serverFile) { (Get-Content $serverFile -Raw).Trim() } else { throw "Set AFH_SERVER, or put user@host in deploy\server.local" }
$ssh = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")

$tmp = Join-Path $env:TEMP "afh-relay.tgz"
Write-Host "==> Packing relay"
& (Join-Path $env:SystemRoot "System32\tar.exe") -czf $tmp --exclude "__pycache__" -C (Join-Path $root "relay") app.py analytics.py requirements.txt static
if ($LASTEXITCODE -ne 0) { throw "tar failed" }

Write-Host "==> Uploading"
scp @ssh -q $tmp (Join-Path $root "deploy\afh-relay.service") "${hostname}:/tmp/"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }

$remote = @"
set -e
id afh-relay >/dev/null 2>&1 || sudo useradd --system --home /var/lib/afh-relay --shell /usr/sbin/nologin afh-relay
sudo mkdir -p /opt/afh-relay /var/lib/afh-relay
sudo chown afh-relay:afh-relay /var/lib/afh-relay
sudo chmod 700 /var/lib/afh-relay
sudo rm -rf /opt/afh-relay/static
sudo tar -xzf /tmp/afh-relay.tgz -C /opt/afh-relay
rm -f /tmp/afh-relay.tgz
if [ ! -x /opt/afh-relay/venv/bin/uvicorn ]; then sudo python3 -m venv /opt/afh-relay/venv; fi
sudo /opt/afh-relay/venv/bin/pip install --quiet --disable-pip-version-check -r /opt/afh-relay/requirements.txt
sudo chown -R root:root /opt/afh-relay
sudo find /opt/afh-relay -path /opt/afh-relay/venv -prune -o -type f -exec chmod 644 {} +
if [ ! -f /etc/afh-relay.env ]; then
  sudo sed -n 's/^Environment=AFH_ADMINS=/AFH_ADMINS=/p' /etc/systemd/system/afh-relay.service 2>/dev/null | sudo tee /etc/afh-relay.env >/dev/null
  sudo chmod 600 /etc/afh-relay.env
fi
sudo test -s /etc/afh-relay.env || echo 'warning: /etc/afh-relay.env is empty, so nobody can open /admin'
sudo install -m 644 /tmp/afh-relay.service /etc/systemd/system/afh-relay.service
rm -f /tmp/afh-relay.service
sudo systemctl daemon-reload
sudo systemctl enable afh-relay >/dev/null 2>&1
sudo systemctl restart afh-relay
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS http://127.0.0.1:8840/relay/api/health; then echo; echo "relay running"; exit 0; fi
  sleep 1
done
sudo journalctl -u afh-relay -n 30 --no-pager
exit 1
"@
$script = Join-Path $env:TEMP "afh-relay-install.sh"
[IO.File]::WriteAllText($script, ($remote -replace "`r", ""), (New-Object Text.UTF8Encoding $false))
scp @ssh -q $script "${hostname}:/tmp/afh-relay-install.sh"
if ($LASTEXITCODE -ne 0) { throw "scp failed" }
ssh @ssh $hostname 'bash /tmp/afh-relay-install.sh; s=$?; rm -f /tmp/afh-relay-install.sh; exit $s'
if ($LASTEXITCODE -ne 0) { throw "remote install failed" }
Remove-Item $script, $tmp -ErrorAction SilentlyContinue
Write-Host "Done: https://agentflowharness.com/m/" -ForegroundColor Green
