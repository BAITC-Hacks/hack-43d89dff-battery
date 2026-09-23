import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.database import Database
from backend.models.generateQuestions import build_questions_prompt, generate_questions
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
    def test_question_prompt_exposes_exact_score_weights_and_draft(self):
        draft = "Support agents need a ticket triage prototype."
        prompt = build_questions_prompt(draft)

        self.assertIn(draft, prompt)
        self.assertIn("description 12 points", prompt)
        self.assertIn("Concrete expected deliverable: 15 points", prompt)
        self.assertIn("concrete target 7 points", prompt)
        self.assertIn("choose 3 to 5 direct questions", prompt)
        self.assertIn("Do not ask about required skills", prompt)

    def test_question_generator_passes_draft_to_llm_and_limits_result_to_five(self):
        prompts = []

        def generator(prompt):
            prompts.append(prompt)
            return {"questions": [f"Question {index}?" for index in range(1, 7)]}

        questions = generate_questions("Draft-specific support problem.", llm_generate=generator)

        self.assertEqual(len(prompts), 1)
        self.assertIn("Draft-specific support problem.", prompts[0])
        self.assertEqual(questions, [f"Question {index}?" for index in range(1, 6)])

    def test_question_generator_rejects_more_than_five_questions(self):
        with self.assertRaisesRegex(ValueError, "maximum <= 5"):
            generate_questions("Draft", llm_generate=lambda _: [], maximum=6)

    def test_auto_mode_does_not_silently_use_fixed_offline_questions(self):
        service = MarketplaceService(Database(":memory:"), ai_mode="auto")
        selected = ["Users?", "Data?", "Success?"]

        with (
            patch("backend.service.generate_questions", return_value=selected) as online,
            patch("backend.service.generate_questions_offline") as offline,
        ):
            questions = service._questions("A draft that must be analyzed.")

        self.assertEqual(questions, selected)
        online.assert_called_once_with("A draft that must be analyzed.")
        offline.assert_not_called()

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
