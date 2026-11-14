"""The student account cap: 15 by default (10 for the study plus 5 spares); demo and admin accounts do not count."""
import pytest

from backend import auth, config, db


def test_student_cap_is_fifteen_and_ignores_demo_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "cap.db")
    db.init_db()
    assert config.MAX_STUDENT_ACCOUNTS == 15
    with db.session() as conn:
        auth.create_user(conn, "demo", "demo-pass-1", "demo")
        for i in range(1, 16):
            auth.create_user(conn, f"user{i:02d}", "pw-for-test-1", "student")
        with pytest.raises(ValueError, match="cap"):
            auth.create_user(conn, "user16", "pw-for-test-1", "student")
