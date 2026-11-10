"""Talks to the live REMEM server with an admin login: data snapshot, reset, final-test switch.

`http` is any object with requests-style get/post (the real `requests` module, or a test client with base_url="").
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


class ServerError(Exception):
    pass


class Server:
    def __init__(self, base_url: str, http=None, timeout: float = 30.0):
        if http is None:
            import requests
            http = requests
        base = base_url.rstrip("/")
        if base:                                                       # an empty address is used only by the tests (relative URLs)
            u = urlparse(base)
            if u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("Use an https:// address: the admin password must not travel unencrypted.")
        self.base, self.http, self.timeout, self.token = base, http, timeout, None

    def _h(self):
        return {"Authorization": "Bearer " + self.token} if self.token else {}

    def _check(self, r):
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise ServerError(str(detail))
        return r

    def login(self, username: str, password: str) -> None:
        r = self._check(self.http.post(self.base + "/api/auth/login", json={"username": username, "password": password}, timeout=self.timeout))
        data = r.json()
        if data.get("role") != "admin":
            raise ServerError("This account is not an admin account.")
        self.token = data["token"]

    def accounts(self) -> list[dict]:
        return self._check(self.http.get(self.base + "/api/admin/accounts", headers=self._h(), timeout=self.timeout)).json()["accounts"]

    def final_open(self) -> bool:
        return self._check(self.http.get(self.base + "/api/admin/final-test", headers=self._h(), timeout=self.timeout)).json()["open"]

    def set_final(self, open_: bool) -> bool:
        return self._check(self.http.post(self.base + "/api/admin/final-test", json={"open": open_}, headers=self._h(), timeout=self.timeout)).json()["open"]

    def reset(self, usernames: list[str], clear_consent: bool = False) -> dict:
        body = {"confirm": "RESET", "usernames": usernames, "clear_consent": clear_consent}
        return self._check(self.http.post(self.base + "/api/admin/reset", json=body, headers=self._h(), timeout=self.timeout)).json()

    def download_snapshot(self, live_path: Path, keep_dated: int = 0) -> Path:
        """Save a consistent copy of the database as `live_path`. With keep_dated > 0 also keep that many dated copies in `backups/`."""
        r = self._check(self.http.get(self.base + "/api/admin/snapshot", headers=self._h(), timeout=self.timeout))
        live_path = Path(live_path)
        live_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = live_path.with_suffix(".part")
        tmp.write_bytes(r.content)
        dated = live_path
        if keep_dated > 0:
            dated_dir = live_path.parent / "backups"
            dated_dir.mkdir(exist_ok=True)
            dated = dated_dir / f"remem_{datetime.now():%Y%m%d_%H%M%S}.db"
            shutil.copyfile(tmp, dated)
            for old in sorted(dated_dir.glob("remem_*.db"))[:-keep_dated]:
                old.unlink()
        tmp.replace(live_path)
        return dated
