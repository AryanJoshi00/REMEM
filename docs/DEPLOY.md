# Deploying the REMEM pilot server (one small always-on Linux server)

Why a server and not a serverless/free-sleeping host: the pilot data lives in one SQLite file, which needs a **persistent disk** and an always-on process (see spec §19.2). Any small Ubuntu VPS works: a ~$4-6/month VPS from a mainstream provider, or an Oracle Cloud "Always Free" VM. **Oracle warning:** Always Free VMs can be reclaimed when they look idle (CPU/network under 20% for 7 days, per Oracle's docs), which a lightly used app will; a paid VPS does not have this problem. You create the account and enter payment details yourself.

## 0. Oracle Cloud Always Free: specific steps and risks
1. Sign up at cloud.oracle.com (card needed for verification). Pick the **home region** carefully; it cannot be changed.
2. Create a compute instance, image **Ubuntu 22.04/24.04**. Prefer the **VM.Standard.E2.1.Micro (AMD, 1 GB)** shape marked Always Free: enough for this app. The ARM `A1.Flex` shape often shows "Out of host capacity".
3. In the console, open **Networking > your VCN > Security List** and add ingress rules for TCP **80** and **443** (source 0.0.0.0/0). `setup.sh` handles the on-host firewall.
4. Add your SSH public key when creating the instance. Default login user is `ubuntu`.
5. **Idle-reclamation risk.** Oracle's documentation says idle Always Free instances may be reclaimed (7-day 95th-percentile CPU under 20%, and network under 20%). A small app will look idle. Mitigation to check on Oracle's current pages: upgrade the tenancy to **Pay As You Go** (you stay at zero cost while inside Always Free limits) and confirm whether upgraded accounts are exempt. Whatever you choose, keep the nightly backups and copy them to your PC every few days; if the VM is reclaimed you can redeploy in about 20 minutes and restore the newest backup into `/opt/remem/data/pilot/remem.db`.
6. Optional: a free uptime monitor (e.g. UptimeRobot) pinging `/api/health` tells you quickly if the server disappears.

## 1. Create the server
- Ubuntu 22.04 or 24.04, 1 GB RAM is enough. Use an **SSH key**, not a password.
- Allow inbound ports 22, 80, 443 (provider firewall/security list).
- Note the public IPv4 address, e.g. `203.0.113.7`. Your free HTTPS name is `203-0-113-7.sslip.io` (dots become dashes). You can use your own domain instead.

## 2. Package and upload (from your PC, in the repo folder, after committing)
```powershell
git archive -o remem.zip HEAD
scp remem.zip ubuntu@203.0.113.7:~/
scp .env ubuntu@203.0.113.7:~/remem.env
```
`.env` holds your Gemini key; it travels over SSH only and is never committed.

## 3. Install (on the server)
```bash
ssh ubuntu@203.0.113.7
unzip -o remem.zip deploy/setup.sh -d ~ && bash ~/deploy/setup.sh 203-0-113-7.sslip.io
sudo mv ~/remem.env /opt/remem/.env && sudo chown remem:remem /opt/remem/.env && sudo chmod 600 /opt/remem/.env
sudo systemctl restart remem
```
Check: `https://203-0-113-7.sslip.io/api/health` returns `{"status":"ok"}`.

## 4. Create accounts (on the server)
```bash
cd /opt/remem
sudo -u remem /opt/remem/venv/bin/python -m backend.admin_create_user create demo --role demo
sudo -u remem /opt/remem/venv/bin/python -m backend.admin_create_user create p01
```
Passwords are printed once; hand them out privately. Up to 10 student accounts.

## 5. Operate
- Logs: `sudo journalctl -u remem -f`
- Update the app: upload a new `remem.zip`, unzip over `/opt/remem`, `sudo systemctl restart remem` (the database in `data/pilot/` is untouched).
- Backups: nightly in `/opt/remem/backups` (14 kept). Copy the newest to your PC regularly: `scp ubuntu@203.0.113.7:/opt/remem/backups/remem_*.db .`
- Open the final test for the delayed-test day: `sudo sqlite3 /opt/remem/data/pilot/remem.db "INSERT OR REPLACE INTO settings VALUES ('final_test_open','1')"`

## Security checklist
SSH key login only; firewall allows 22/80/443 only (setup script enables `ufw`); `.env` mode 600; no secrets in the repo; HTTPS only; pilot data and backups never committed.
