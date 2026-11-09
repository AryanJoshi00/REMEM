"""Download a backup of the live database from the server (run by hand or from Windows Task Scheduler).

    python -m eval_dashboard.pull_backup

Reads REMEM_SERVER_URL, REMEM_ADMIN_USER and REMEM_ADMIN_PASSWORD from the environment or from .env.
Saves data/pilot/remem_live.db and a dated copy in data/pilot/backups/.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from eval_dashboard.server import Server, ServerError

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    load_dotenv(ROOT / ".env")
    url, user, pw = os.getenv("REMEM_SERVER_URL"), os.getenv("REMEM_ADMIN_USER", "aryan"), os.getenv("REMEM_ADMIN_PASSWORD")
    if not url or not pw:
        print("Set REMEM_SERVER_URL and REMEM_ADMIN_PASSWORD in .env first.", file=sys.stderr)
        return 2
    try:
        srv = Server(url)
        srv.login(user, pw)
        dated = srv.download_snapshot(ROOT / "data" / "pilot" / "remem_live.db", keep_dated=30)
    except (ServerError, OSError) as e:
        print("Backup failed:", e, file=sys.stderr)
        return 1
    print("Saved", dated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
