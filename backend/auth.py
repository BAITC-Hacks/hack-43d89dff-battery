"""Password accounts and opaque server-side sessions using the standard library."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .database import Database
from .service import (
    AuthPrincipal,
    ServiceError,
    _business_view,
    _dump,
    _id,
    _optional_text,
    _required_text,
    _string_list,
    _team_view,
    _token_hash,
    _token_matches,
)


PASSWORD_ITERATIONS = 600_000
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
_DUMMY_HASH = f"pbkdf2_sha256${PASSWORD_ITERATIONS}${'00' * 32}${'00' * 32}"


def csrf_token(raw_token: str) -> str:
    """Expose a CSRF proof without exposing the HttpOnly session credential."""
    return hashlib.sha256(b"marketplace-csrf-v1\x00" + raw_token.encode("utf-8")).hexdigest()


def csrf_matches(raw_token: str | None, supplied: str | None) -> bool:
    if not _usable_token(raw_token) or not isinstance(supplied, str):
        return False
    # Reject non-ASCII header values before compare_digest's string overload.
    return len(supplied) == 64 and supplied.isascii() and hmac.compare_digest(
        csrf_token(raw_token), supplied
    )


class AuthService:
    """Create role-linked accounts and resolve sessions to internal principals.

    Only register/login return a raw session token, separately from the safe
    JSON response so the HTTP layer can place it in an HttpOnly cookie.
    """

    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        _require_payload(payload)
        role = payload.get("role")
        if not isinstance(role, str) or role not in {"business", "student"}:
            raise ServiceError(422, "validation_error", "Choose a business or student account.")
        name = _required_text(payload, "name", maximum=160)
        email = _account_email(payload.get("email"))
        password = _password(payload.get("password"))
        profile_name = _optional_text(
            payload.get("organization_name" if role == "business" else "team_name"),
            maximum=160,
        ) or name
        description = _optional_text(payload.get("description"), maximum=2000)
        contact_name = _optional_text(payload.get("contact_name"), maximum=160) or name
        contact_email = _account_email(payload["contact_email"]) if payload.get("contact_email") else email
        skills = _string_list(payload.get("skills", []), "skills", maximum_items=30)
        # Validate encodability before SQLite or password hashing sees user data.
        for value in (name, profile_name, description, contact_name, *skills):
            _valid_unicode(value)
        legacy_id, legacy_token = _legacy_claim(payload)
        password_hash = _hash_password(password)
        account_id = _id("account")
        raw_token = secrets.token_urlsafe(32)
        now = int(time.time())
        try:
            with self.database.transaction() as connection:
                self._cleanup_sessions(connection, now)
                if connection.execute("SELECT 1 FROM accounts WHERE email = ?", (email,)).fetchone():
                    raise ServiceError(409, "email_already_registered", "An account with this email already exists.")
                if legacy_id:
                    profile_id = self._claim_profile(connection, role, legacy_id, legacy_token)
                else:
                    profile_id = _id("biz" if role == "business" else "team")
                    # These hashes satisfy the legacy schema but have no issued
                    # credential. Account-backed profiles reject legacy tokens.
                    owner_hash = _token_hash(secrets.token_urlsafe(32))
                    if role == "business":
                        connection.execute(
                            """INSERT INTO businesses
                            (id, name, description, contact_name, contact_email, owner_token_hash)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                            (profile_id, profile_name, description, contact_name, contact_email, owner_hash),
                        )
                    else:
                        connection.execute(
                            """INSERT INTO teams
                            (id, name, description, skills_json, contact_email, owner_token_hash)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                            (profile_id, profile_name, description, _dump(skills), contact_email, owner_hash),
                        )
                connection.execute(
                    """INSERT INTO accounts
                    (id, name, email, password_hash, role, business_id, team_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        account_id, name, email, password_hash, role,
                        profile_id if role == "business" else None,
                        profile_id if role == "student" else None,
                    ),
                )
                self._insert_session(connection, account_id, raw_token, now)
                result = self._session_view(connection, raw_token, now)
        except sqlite3.IntegrityError as error:
            # BEGIN IMMEDIATE serializes claims and the explicit checks above.
            # This remains a safe fallback for uniqueness failures.
            if "accounts.email" in str(error):
                raise ServiceError(409, "email_already_registered", "An account with this email already exists.") from error
            if "accounts.business_id" in str(error) or "accounts.team_id" in str(error):
                raise ServiceError(409, "profile_already_claimed", "This profile already belongs to an account.") from error
            raise
        return result, raw_token

    def login(self, payload: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
        _require_payload(payload)
        try:
            email = _account_email(payload.get("email"))
            password = _password(payload.get("password"))
        except ServiceError:
            # Use the same error for malformed and incorrect credentials.
            raise _invalid_credentials() from None
        with self.database.read() as connection:
            account = connection.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
        verified = _verify_password(password, account["password_hash"] if account else _DUMMY_HASH)
        if not account or not verified:
            raise _invalid_credentials()
        raw_token = secrets.token_urlsafe(32)
        now = int(time.time())
        with self.database.transaction() as connection:
            self._cleanup_sessions(connection, now)
            self._insert_session(connection, account["id"], raw_token, now)
            result = self._session_view(connection, raw_token, now)
        return result, raw_token

    def session(self, raw_token: str | None) -> dict[str, Any]:
        if not _usable_token(raw_token):
            return _anonymous_session()
        now = int(time.time())
        with self.database.transaction() as connection:
            self._cleanup_sessions(connection, now)
            return self._session_view(connection, raw_token, now)

    def authenticate(self, raw_token: str | None) -> AuthPrincipal | None:
        if not _usable_token(raw_token):
            return None
        with self.database.read() as connection:
            row = connection.execute(
                """SELECT accounts.id, accounts.role, accounts.business_id, accounts.team_id
                FROM sessions JOIN accounts ON accounts.id = sessions.account_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
                (_token_hash(raw_token), int(time.time())),
            ).fetchone()
        if not row:
            return None
        return AuthPrincipal(row["id"], row["role"], row["business_id"], row["team_id"])

    def logout(self, raw_token: str | None) -> None:
        with self.database.transaction() as connection:
            self._cleanup_sessions(connection, int(time.time()))
            if _usable_token(raw_token):
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(raw_token),))

    @staticmethod
    def _claim_profile(
        connection: sqlite3.Connection, role: str, profile_id: str, legacy_token: str
    ) -> str:
        table, column = ("businesses", "business_id") if role == "business" else ("teams", "team_id")
        profile = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (profile_id,)).fetchone()
        if not profile:
            raise ServiceError(403, "invalid_legacy_credentials", "The saved profile could not be verified.")
        if connection.execute(f"SELECT 1 FROM accounts WHERE {column} = ?", (profile_id,)).fetchone():
            raise ServiceError(409, "profile_already_claimed", "This profile already belongs to an account.")
        if not _token_matches(legacy_token, profile["owner_token_hash"]):
            raise ServiceError(403, "invalid_legacy_credentials", "The saved profile could not be verified.")
        connection.execute(
            f"UPDATE {table} SET owner_token_hash = ? WHERE id = ?",
            (_token_hash(secrets.token_urlsafe(32)), profile_id),
        )
        return profile_id

    @staticmethod
    def _insert_session(connection: sqlite3.Connection, account_id: str, raw_token: str, now: int) -> None:
        connection.execute(
            "INSERT INTO sessions (token_hash, account_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (_token_hash(raw_token), account_id, now, now + SESSION_TTL_SECONDS),
        )

    @staticmethod
    def _cleanup_sessions(connection: sqlite3.Connection, now: int) -> None:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))

    @staticmethod
    def _session_view(connection: sqlite3.Connection, raw_token: str, now: int) -> dict[str, Any]:
        row = connection.execute(
            """SELECT accounts.*, sessions.expires_at FROM sessions
            JOIN accounts ON accounts.id = sessions.account_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (_token_hash(raw_token), now),
        ).fetchone()
        if not row:
            return _anonymous_session()
        if row["role"] == "business":
            profile = _business_view(connection.execute(
                "SELECT * FROM businesses WHERE id = ?", (row["business_id"],)
            ).fetchone())
        else:
            profile = _team_view(connection.execute(
                "SELECT * FROM teams WHERE id = ?", (row["team_id"],)
            ).fetchone())
        return {
            "user": {key: row[key] for key in ("id", "name", "email", "role")},
            "profile": profile,
            "csrf_token": csrf_token(raw_token),
            "expires_at": datetime.fromtimestamp(row["expires_at"], timezone.utc).isoformat().replace("+00:00", "Z"),
        }


def _anonymous_session() -> dict[str, Any]:
    return {"user": None, "profile": None, "csrf_token": None, "expires_at": None}


def _require_payload(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        raise ServiceError(422, "validation_error", "A JSON object is required.")


def _account_email(value: Any) -> str:
    if not isinstance(value, str):
        raise ServiceError(422, "validation_error", "A valid email address is required.")
    email = value.strip().casefold()
    _valid_unicode(email)
    if (
        not 3 <= len(email) <= 320
        or email.count("@") != 1
        or email.startswith("@")
        or email.endswith("@")
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in email)
    ):
        raise ServiceError(422, "validation_error", "A valid email address is required.")
    return email


def _password(value: Any) -> str:
    if not isinstance(value, str) or not 15 <= len(value) <= 128:
        raise ServiceError(422, "validation_error", "Use a password between 15 and 128 characters.")
    _valid_unicode(value)
    return value


def _valid_unicode(value: str | None) -> None:
    if value is None:
        return
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ServiceError(422, "validation_error", "Text contains an invalid Unicode character.") from None


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(32)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, expected_text = stored.split("$")
        iterations = int(iterations_text)
        salt, expected = bytes.fromhex(salt_text), bytes.fromhex(expected_text)
        if algorithm != "pbkdf2_sha256" or not PASSWORD_ITERATIONS <= iterations <= 2_000_000:
            return False
        if len(salt) != 32 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


def _legacy_claim(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    profile_id = payload.get("legacy_profile_id")
    token = payload.get("legacy_owner_token")
    if profile_id is None and token is None:
        return None, None
    if not isinstance(profile_id, str) or not 1 <= len(profile_id) <= 80 or not _usable_token(token):
        raise ServiceError(422, "validation_error", "The saved profile ID and token are both required.")
    _valid_unicode(profile_id)
    return profile_id, token


def _usable_token(token: Any) -> bool:
    return isinstance(token, str) and 20 <= len(token) <= 256 and token.isascii()


def _invalid_credentials() -> ServiceError:
    return ServiceError(401, "invalid_credentials", "The email or password is incorrect.")
