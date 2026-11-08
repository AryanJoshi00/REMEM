"""Consistent SQLite backup (safe while the server is running). Keeps the newest N copies in backups/.

  python -m backend.backup_db            # one backup now
  python -m backend.backup_db --keep 14
Schedule it daily with Windows Task Scheduler (see README) when the pilot runs on your own PC.
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

from backend import config


def backup(dest_dir: Path | None = None, keep: int = 14) -> Path:
    dest_dir = dest_dir or config.ROOT / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"remem_{datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(out)
    try:
        src.backup(dst)               # online, consistent copy
    finally:
        dst.close(); src.close()
    for old in sorted(dest_dir.glob("remem_*.db"))[:-keep]:
        old.unlink()
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=14)
    print("Backup written:", backup(keep=ap.parse_args().keep))
