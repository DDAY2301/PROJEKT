"""Create or reset a local Project Visibility test user safely.

Usage:
    .\.venv\Scripts\python.exe .\api\create_test_user.py --email maj@klemec.org

The password is entered interactively and never written to source control.
"""

from __future__ import annotations

import argparse
import getpass
import sqlite3
import uuid
from pathlib import Path

import bcrypt

DB_PATH = Path("api/data/agent.db")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local Project Visibility test user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--reset", action="store_true", help="Reset the password if the user already exists")
    args = parser.parse_args()

    email = args.email.strip().lower()
    if "@" not in email:
        raise SystemExit("Invalid email address")

    password = getpass.getpass("Password (minimum 8 characters): ")
    if len(password) < 8:
        raise SystemExit("Password must contain at least 8 characters")
    confirm = getpass.getpass("Repeat password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match")

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash BLOB NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        row = con.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        if row:
            if not args.reset:
                print(f"User {email} already exists. Re-run with --reset to change the password.")
                return 0
            con.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, row["id"]))
            con.commit()
            print(f"Password reset for {email}.")
            return 0

        from datetime import datetime, timezone

        con.execute(
            "INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)",
            (str(uuid.uuid4()), email, hashed, datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
        print(f"Created local test user: {email}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
