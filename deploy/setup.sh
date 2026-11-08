#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 22.04/24.04 server. Run as a sudo-capable user from the folder that holds remem.zip.
#   bash setup.sh 203-0-113-7.sslip.io
set -euo pipefail
HOST="${1:?usage: bash setup.sh <hostname, e.g. 203-0-113-7.sslip.io>}"

sudo apt-get update -y
sudo apt-get install -y python3-venv unzip debian-keyring debian-archive-keyring apt-transport-https curl ufw
# Caddy (automatic HTTPS)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt-get update -y && sudo apt-get install -y caddy

sudo useradd --system --create-home --home-dir /opt/remem --shell /usr/sbin/nologin remem 2>/dev/null || true
sudo unzip -o remem.zip -d /opt/remem
sudo python3 -m venv /opt/remem/venv
sudo /opt/remem/venv/bin/pip install --upgrade pip
sudo /opt/remem/venv/bin/pip install -r /opt/remem/requirements-server.txt
sudo mkdir -p /opt/remem/data/pilot /opt/remem/backups
[ -f .env ] && sudo cp .env /opt/remem/.env
if [ ! -f /opt/remem/.env ]; then
  echo "Create /opt/remem/.env now (GEMINI_API_KEY=...), then re-run: sudo systemctl restart remem"
fi
sudo chown -R remem:remem /opt/remem
[ -f /opt/remem/.env ] && sudo chmod 600 /opt/remem/.env

sudo cp /opt/remem/deploy/remem.service /etc/systemd/system/remem.service
sudo cat /opt/remem/deploy/Caddyfile | sed "s/YOUR-HOST-NAME/${HOST}/" | sudo tee /etc/caddy/Caddyfile >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now remem
sudo systemctl restart caddy

# nightly database backup (keeps 14 copies)
( { sudo -u remem crontab -l 2>/dev/null || true; } | grep -v backup_db || true;  echo "15 3 * * * cd /opt/remem && /opt/remem/venv/bin/python -m backend.backup_db --keep 14" ) | sudo -u remem crontab -

# Oracle Cloud Ubuntu images ship iptables rules that reject 80/443; let ufw manage the host firewall instead
# (the cloud security list in the Oracle console is still the outer firewall - open 80/443 there).
if [ -f /etc/iptables/rules.v4 ]; then
  sudo iptables -P INPUT ACCEPT; sudo iptables -F INPUT
  sudo netfilter-persistent save 2>/dev/null || true
fi
# firewall: SSH + web only
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw --force enable
echo "Done. Open https://${HOST}/  (give Caddy ~1 minute to get its certificate)"
