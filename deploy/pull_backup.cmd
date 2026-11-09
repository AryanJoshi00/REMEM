@echo off
rem Daily backup of the live database to this computer (see README). Needs REMEM_SERVER_URL and REMEM_ADMIN_PASSWORD in .env
cd /d "%~dp0.."
venv\Scripts\python.exe -m eval_dashboard.pull_backup
