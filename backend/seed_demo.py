"""Explicitly prepare the public jury demo accounts without resetting accounts."""

from __future__ import annotations

import os
import sqlite3
import sys

from .auth import AuthService
from .database import Database
from .service import ServiceError


DEMO_ACCOUNTS = (
    {
        "role": "student",
        "name": "Student One",
        "team_name": "Orbit Team",
        "email": "student1@sana.test",
        "password": "8iuyHVIQp8S7d01Jx-yJk75y",
    },
    {
        "role": "student",
        "name": "Student Two",
        "team_name": "Nova Team",
        "email": "student2@sana.test",
        "password": "7-KKiO2p8DgKMFq-HaULZ_eC",
    },
    {
        "role": "business",
        "name": "Business Owner",
        "organization_name": "Sana Demo Business",
        "email": "business@sana.test",
        "password": "Qwqp42cT9g0X-v-om3A1WQRJ",
    },
)


def seed_demo(database: Database) -> None:
    """Create missing accounts; verify existing credentials without changing them."""
    database.initialize()
    auth = AuthService(database)
    for account in DEMO_ACCOUNTS:
        email = account["email"]
        try:
            session, token = auth.register(account)
            action = "Created"
        except ServiceError as error:
            if error.code != "email_already_registered":
                raise
            try:
                session, token = auth.login(account)
            except ServiceError as login_error:
                raise RuntimeError(
                    f"{email}: existing credentials do not match the demo credentials. "
                    "No password or account reset was performed."
                ) from login_error
            action = "Verified"
        auth.logout(token)
        if session["user"]["role"] != account["role"]:
            raise RuntimeError(
                f"{email}: existing account has a different role. "
                "No password or account reset was performed."
            )
        print(f"{action}: {email}")


def main() -> int:
    database = Database(os.getenv("MARKETPLACE_DB_PATH", "data/marketplace.sqlite3"))
    try:
        seed_demo(database)
    except (ServiceError, RuntimeError, sqlite3.Error, OSError) as error:
        print(f"Demo setup failed: {error}", file=sys.stderr)
        return 1
    print("Demo accounts are ready. No demo sessions were left signed in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
