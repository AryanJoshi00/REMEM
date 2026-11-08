"""Owner-only account management (spec 17.3). Prints a generated password ONCE; it is never stored in plain text.

Examples (run from the repo root, venv active):
  python -m backend.admin_create_user create p01              # student (max 10)
  python -m backend.admin_create_user create demo --role demo
  python -m backend.admin_create_user reset p01
  python -m backend.admin_create_user disable p01
  python -m backend.admin_create_user list
"""
from __future__ import annotations

import argparse
import secrets
import string

from backend import auth, db


def gen_password(n: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["create", "reset", "disable", "enable", "list"])
    ap.add_argument("username", nargs="?")
    ap.add_argument("--role", default="student", choices=["student", "demo", "admin"])
    ap.add_argument("--password", help="set a chosen password for reset (pilot convenience)")
    a = ap.parse_args()
    db.init_db()
    with db.session() as conn:
        if a.action == "list":
            for r in conn.execute("SELECT username, role, active, consent_at IS NOT NULL AS consented FROM users ORDER BY user_id"):
                print(f"{r['username']:<10} {r['role']:<8} active={r['active']} consented={r['consented']}")
            return
        if not a.username:
            ap.error("username required")
        if a.action == "create":
            pw = gen_password()
            auth.create_user(conn, a.username, pw, a.role)
            print(f"Created {a.role} '{a.username}'. Password (shown once): {pw}")
        elif a.action == "reset":
            pw = a.password or gen_password()
            h, salt = auth.hash_password(pw)
            n = conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE username=?", (h, salt, a.username)).rowcount
            print(f"New password for '{a.username}' (shown once): {pw}" if n else "No such user")
        else:
            conn.execute("UPDATE users SET active=? WHERE username=?", (1 if a.action == "enable" else 0, a.username))
            print(f"{a.action}d '{a.username}'")


if __name__ == "__main__":
    main()
