import tempfile
import unittest
from pathlib import Path

from backend.database import Database
from backend.service import MarketplaceService, ServiceError


class MarketplaceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = MarketplaceService(
            Database(Path(self.temp_dir.name) / "marketplace.sqlite3"), ai_mode="offline"
        )
        self.service.initialize()
        self.business = self.service.create_business(
            {"name": "Acme", "contact_name": "Aida", "contact_email": "aida@acme.test"}
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_manual_marketplace_flow(self):
        task = self.service.create_task(
            {
                "business_id": self.business["id"],
                "initial_draft": "Our support team manually triages customer requests.",
            },
            self.business["owner_token"],
        )
        self.assertEqual(task["status"], "awaiting_answers")
        self.assertGreaterEqual(len(task["clarifying_questions"]), 3)

        task = self.service.submit_answers(
            task["id"],
            {
                "task_summary": "Build a support-ticket prioritization prototype.",
                "answers": [
                    "Anonymized tickets in a secure folder",
                    "A web prototype",
                    "80% accuracy, verified against a labelled test set",
                    "Manual triage delays urgent tickets for support agents and managers",
                    "No personal data; four-week scope; Aida, Support Lead, via weekly video calls",
                ],
            },
            self.business["owner_token"],
        )
        self.assertEqual(task["status"], "card_ready")

        task = self.service.update_card(
            task["id"],
            {
                "available_data": {
                    "sources": ["12 months of ticket exports"],
                    "access_conditions": "Anonymized secure folder",
                },
                "business_contact": {"name": "Aida", "role": "Support Lead", "email": "aida@acme.test"},
                "interaction_format": {"channel": "Video", "frequency": "Weekly"},
                "tags": ["support", "triage"],
                "industry": "SaaS",
            },
            self.business["owner_token"],
        )
        confirmed = self.service.confirm_task(task["id"], self.business["owner_token"])
        published = self.service.publish_task(task["id"], self.business["owner_token"])
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(published["status"], "published")
        self.assertGreater(published["evaluation"]["score"], 0)

        catalog = self.service.catalog(tags=["support"], industry="SaaS")
        self.assertEqual(catalog["total"], 1)
        self.assertEqual(catalog["items"][0]["id"], task["id"])

        team = self.service.create_team(
            {"name": "Orbit", "contact_email": "orbit@example.test", "skills": ["Python"]}
        )
        proposal = self.service.create_proposal(
            task["id"],
            {"team_id": team["id"], "message": "We can help.", "approach": "Prototype and test."},
            team["owner_token"],
        )
        decided = self.service.decide_proposal(
            proposal["id"], "accepted", self.business["owner_token"]
        )
        self.assertEqual(decided["status"], "accepted")

    def test_publish_requires_confirmation_and_tokens_are_enforced(self):
        task = self.service.create_task(
            {"business_id": self.business["id"], "initial_draft": "Improve our customer support process."},
            self.business["owner_token"],
        )
        with self.assertRaises(ServiceError) as forbidden:
            self.service.submit_answers(task["id"], {"answers": ["a", "b", "c"]}, "wrong-token")
        self.assertEqual(forbidden.exception.status, 403)

        with self.assertRaises(ServiceError) as unconfirmed:
            self.service.publish_task(task["id"], self.business["owner_token"])
        self.assertEqual(unconfirmed.exception.code, "confirmation_required")
