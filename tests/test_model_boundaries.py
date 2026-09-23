import tempfile
import unittest
from pathlib import Path

from backend.database import Database
from backend.models.generateQuestions import generate_questions
from backend.models.generateTaskCard import TASK_CARD_TEMPLATE, generate_task_card
from backend.service import MarketplaceService


PAYLOAD = {
    "initial_draft": "Support agents manually prioritize customer tickets.",
    "clarifying_questions": [
        "Who will use it?",
        "What data is available?",
        "How is success measured?",
    ],
    "answers": ["Agents", "Anonymized tickets", "80 percent accuracy"],
    "task_summary": "Build a triage prototype.",
}


class ModelBoundaryTests(unittest.TestCase):
    def test_card_normalizes_malformed_optional_list_fields(self):
        card = generate_task_card(
            PAYLOAD,
            llm_generate=lambda _: {
                "title": "Triage prototype",
                "missing_information": None,
                "warnings": "not a list",
            },
        )

        self.assertIsInstance(card["missing_information"], list)
        self.assertEqual(card["warnings"], [])
        self.assertIn("context", card["missing_information"])

    def test_question_generator_accepts_fenced_json(self):
        questions = generate_questions(
            "We need a better support workflow.",
            llm_generate=lambda _: '```json\n{"questions": ["Who uses it?", "What data exists?", "How is success measured?"]}\n```',
        )

        self.assertEqual(len(questions), 3)
        self.assertEqual(questions[0], "Who uses it?")

    def test_service_normalizes_partial_injected_card_before_persisting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            service = MarketplaceService(
                Database(Path(temp_dir) / "marketplace.sqlite3"),
                question_generator=lambda _: ["Users?", "Data?", "Success?"],
                card_generator=lambda _: {"title": "Injected card", "missing_information": None},
            )
            service.initialize()
            business = service.create_business({"name": "Acme"})
            task = service.create_task(
                {"business_id": business["id"], "initial_draft": "Improve support."},
                business["owner_token"],
            )
            generated = service.submit_answers(
                task["id"], {"answers": ["Agents", "Tickets", "Accuracy"]}, business["owner_token"]
            )

        self.assertEqual(set(generated["card"]), set(TASK_CARD_TEMPLATE))
        self.assertIsInstance(generated["card"]["missing_information"], list)
        self.assertEqual(generated["status"], "card_ready")

