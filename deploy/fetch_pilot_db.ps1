# Download a consistent snapshot of the live pilot database for the dashboard.
#   powershell -File deploy\fetch_pilot_db.ps1 -Key "path\to\private.key" -Server <server ip or host>
param(
  [Parameter(Mandatory = $true)][string]$Key,
  [Parameter(Mandatory = $true)][string]$Server,
  [string]$User = "ubuntu"
)
$dest = Join-Path $PSScriptRoot "..\data\pilot"
New-Item -ItemType Directory -Force $dest | Out-Null
# SQLite online backup via the project's own script (keeps 14 copies on the server); copy the newest one.
$remote = "sudo -u remem sh -c 'cd /opt/remem && ./venv/bin/python -m backend.backup_db --keep 14' >/dev/null; sudo sh -c 'ls -t /opt/remem/backups/* | head -1 | xargs -I{} cp {} /tmp/remem_snapshot.db'; sudo chmod 644 /tmp/remem_snapshot.db"
ssh -i $Key "$User@$Server" $remote
scp -i $Key "${User}@${Server}:/tmp/remem_snapshot.db" (Join-Path $dest "remem_live.db")
ssh -i $Key "$User@$Server" "rm -f /tmp/remem_snapshot.db" 2>$null
if (-not (Test-Path (Join-Path $dest "remem_live.db"))) { throw "Download failed" }
Write-Host "Saved $dest\remem_live.db"
