"""Account, session, ownership, and upgrade regressions without external services."""

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.auth import AuthService, csrf_matches, csrf_token
from backend.database import Database, MIGRATIONS
from backend.service import MarketplaceService, ServiceError


PASSWORD = "A long local test passphrase!"


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "accounts.sqlite3")
        self.database.initialize()
        self.auth = AuthService(self.database)
        self.marketplace = MarketplaceService(self.database, ai_mode="offline")

    def tearDown(self):
        self.temp_dir.cleanup()

    def register(self, role="business", email="aida@example.test", **extra):
        return self.auth.register({
            "role": role, "name": "Aida", "email": email, "password": PASSWORD,
            "organization_name": "Acme", "team_name": "Orbit", **extra,
        })

    def assert_error(self, status, action):
        with self.assertRaises(ServiceError) as raised:
            action()
        self.assertEqual(raised.exception.status, status)
        return raised.exception

    def test_individual_accounts_have_correct_profiles_and_safe_session_views(self):
        business, business_token = self.register()
        student, student_token = self.register("student", "student@example.test")
        self.assertEqual(business["user"]["role"], "business")
        self.assertEqual(business["profile"]["name"], "Acme")
        self.assertEqual(student["user"]["name"], "Aida")
        self.assertEqual(student["user"]["role"], "student")
        self.assertEqual(student["profile"]["name"], "Orbit")
        self.assertNotEqual(student["user"]["id"], student["profile"]["id"])
        for session, token in [(business, business_token), (student, student_token)]:
            view = json.dumps(session)
            for secret in [PASSWORD, token, "password_hash", "owner_token", "token_hash"]:
                self.assertNotIn(secret, view)
            self.assertEqual(self.auth.session(token), session)
            self.assertTrue(csrf_matches(token, session["csrf_token"]))
            self.assertFalse(csrf_matches(token, "wrong"))
            self.assertNotEqual(csrf_token(token), token)

    def test_passwords_are_salted_and_raw_sessions_are_not_persisted(self):
        first, first_token = self.register()
        _, second_token = self.register("student", "second@example.test")
        with self.database.read() as connection:
            accounts = connection.execute("SELECT password_hash FROM accounts").fetchall()
            sessions = connection.execute("SELECT token_hash FROM sessions").fetchall()
        self.assertEqual(len(accounts), 2)
        self.assertNotEqual(accounts[0][0], accounts[1][0])
        self.assertTrue(all(PASSWORD not in row[0] for row in accounts))
        self.assertEqual({row[0] for row in sessions}, {
            hashlib.sha256(first_token.encode()).hexdigest(),
            hashlib.sha256(second_token.encode()).hexdigest(),
        })
        logged_in, token = self.auth.login({"email": " AIDA@EXAMPLE.TEST ", "password": PASSWORD})
        self.assertEqual(logged_in["user"]["id"], first["user"]["id"])
        self.assertNotEqual(token, first_token)

    def test_duplicate_email_is_normalized_and_registration_is_atomic(self):
        self.register()
        self.assert_error(409, lambda: self.register("student", " AIDA@EXAMPLE.TEST "))
        with self.database.read() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM teams").fetchone()[0], 0)

    def test_registration_validation_and_generic_login_errors(self):
        for extra in [{"role": "admin"}, {"email": "invalid"}, {"password": "short"},
                      {"password": "x" * 129}, {"name": ""}]:
            with self.subTest(extra=list(extra)):
                self.assert_error(422, lambda: self.register(**extra))
        self.register()
        wrong = self.assert_error(401, lambda: self.auth.login({"email": "aida@example.test", "password": "incorrect password"}))
        absent = self.assert_error(401, lambda: self.auth.login({"email": "absent@example.test", "password": "incorrect password"}))
        self.assertEqual((wrong.code, wrong.message), (absent.code, absent.message))

    def test_session_expiry_and_logout_revoke_access(self):
        _, token = self.register()
        self.assertIsNotNone(self.auth.authenticate(token))
        with self.database.transaction() as connection:
            connection.execute("UPDATE sessions SET created_at = 0, expires_at = 1")
        self.assertIsNone(self.auth.authenticate(token))
        self.assertIsNone(self.auth.session(token)["user"])
        _, token = self.auth.login({"email": "aida@example.test", "password": PASSWORD})
        self.auth.logout(token)
        self.assertIsNone(self.auth.authenticate(token))
        self.assertIsNone(self.auth.session(token)["profile"])
        self.assertIsNone(self.auth.session("unrecognized")["csrf_token"])

    def test_businesses_cannot_access_other_accounts_or_student_actions(self):
        owner, token = self.register()
        other, other_token = self.register(email="other@example.test")
        student, student_token = self.register("student", "student@example.test")
        principal = self.auth.authenticate(token)
        task = self.marketplace.create_task({"business_id": owner["profile"]["id"], "initial_draft": "Improve support triage."}, principal)
        other_principal = self.auth.authenticate(other_token)
        student_principal = self.auth.authenticate(student_token)
        self.assertEqual(self.marketplace.get_task(task["id"], principal)["initial_draft"], "Improve support triage.")
        for outsider in [None, other_principal, student_principal]:
            self.assert_error(404, lambda: self.marketplace.get_task(task["id"], outsider))
            self.assert_error(403, lambda: self.marketplace.list_business_tasks(owner["profile"]["id"], outsider))
        self.assert_error(403, lambda: self.marketplace.create_task({"business_id": other["profile"]["id"], "initial_draft": "Foreign draft"}, principal))
        self.assert_error(403, lambda: self.marketplace.list_team_proposals(student["profile"]["id"], principal))
        self.assertEqual(self.marketplace.list_team_proposals(student["profile"]["id"], student_principal), [])

    def test_students_cannot_read_another_team(self):
        first, first_token = self.register("student", "first@example.test")
        second, second_token = self.register("student", "second@example.test")
        self.assertNotEqual(first["profile"]["id"], second["profile"]["id"])
        self.assert_error(403, lambda: self.marketplace.list_team_proposals(second["profile"]["id"], self.auth.authenticate(first_token)))
        self.assertEqual(self.marketplace.list_team_proposals(second["profile"]["id"], self.auth.authenticate(second_token)), [])

    def test_legacy_claim_requires_proof_preserves_work_and_revokes_old_token(self):
        legacy = self.marketplace.create_business({"name": "Existing company"})
        task = self.marketplace.create_task({"business_id": legacy["id"], "initial_draft": "Existing private draft"}, legacy["owner_token"])
        self.assert_error(403, lambda: self.register(legacy_profile_id=legacy["id"], legacy_owner_token="wrong" * 8))
        session, token = self.register(legacy_profile_id=legacy["id"], legacy_owner_token=legacy["owner_token"])
        self.assertEqual(session["profile"]["id"], legacy["id"])
        self.assertEqual(self.marketplace.list_business_tasks(legacy["id"], self.auth.authenticate(token))[0]["id"], task["id"])
        self.assert_error(403, lambda: self.marketplace.list_business_tasks(legacy["id"], legacy["owner_token"]))
        with self.assertRaises(ServiceError):
            self.register(email="attacker@example.test", legacy_profile_id=legacy["id"], legacy_owner_token=legacy["owner_token"])

    def test_legacy_team_claim_keeps_identity_and_cannot_change_role(self):
        legacy = self.marketplace.create_team({"name": "Existing team", "contact_email": "old@example.test"})
        proof = {"legacy_profile_id": legacy["id"], "legacy_owner_token": legacy["owner_token"]}
        self.assert_error(403, lambda: self.register("business", **proof))
        session, token = self.register("student", **proof)
        self.assertEqual(session["profile"]["id"], legacy["id"])
        self.assertEqual(session["profile"]["name"], "Existing team")
        self.assertEqual(self.marketplace.list_team_proposals(legacy["id"], self.auth.authenticate(token)), [])
        self.assert_error(403, lambda: self.marketplace.list_team_proposals(legacy["id"], legacy["owner_token"]))


class LegacyDatabaseMigrationTests(unittest.TestCase):
    def test_newer_database_is_rejected_without_schema_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "future.sqlite3")
            with database.transaction() as connection:
                connection.execute("CREATE TABLE future_data(value TEXT)")
                connection.execute("PRAGMA user_version = 2")
            with self.assertRaises(RuntimeError):
                database.initialize()
            with database.read() as connection:
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                self.assertEqual([row[0] for row in tables], ["future_data"])
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_failed_migration_rolls_back_and_can_be_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "rollback.sqlite3")
            with database.transaction() as connection:
                connection.execute("CREATE TABLE existing_data(value TEXT)")
                connection.execute("INSERT INTO existing_data VALUES ('preserved')")
            broken = {1: (*MIGRATIONS[1], "INSERT INTO missing_table VALUES (1)")}
            with patch("backend.database.MIGRATIONS", broken):
                with self.assertRaises(sqlite3.OperationalError):
                    database.initialize()
            with database.read() as connection:
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                self.assertEqual([row[0] for row in tables], ["existing_data"])
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT value FROM existing_data").fetchone()[0], "preserved")
            database.initialize()
            with database.read() as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_upgrade_preserves_legacy_records_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript((Path(__file__).parent / "fixtures" / "legacy_schema.sql").read_text())
            connection.execute("INSERT INTO businesses(id,name,owner_token_hash) VALUES('biz_legacy','Legacy company','old-hash')")
            connection.execute("INSERT INTO teams(id,name,contact_email,owner_token_hash) VALUES('team_legacy','Legacy team','old@example.test','old-hash')")
            connection.execute("INSERT INTO tasks(id,business_id,initial_draft,questions_json,status) VALUES('task_legacy','biz_legacy','Preserved draft','[]','published')")
            connection.execute("INSERT INTO proposals(id,task_id,team_id,message,approach,status) VALUES('proposal_legacy','task_legacy','team_legacy','Preserved proposal','Prototype','accepted')")
            connection.commit()
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
            connection.close()
            database = Database(path)
            database.initialize()
            database.initialize()
            with database.read() as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT initial_draft FROM tasks").fetchone()[0], "Preserved draft")
                self.assertEqual(connection.execute("SELECT message,status FROM proposals").fetchone()[:], ("Preserved proposal", "accepted"))
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 0)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
