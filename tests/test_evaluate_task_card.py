import unittest

from backend.models.evaluateTaskCard import evaluate_task_card, readiness_level


class EvaluateTaskCardTests(unittest.TestCase):
    def test_empty_card_is_a_draft_with_actionable_gaps(self):
        result = evaluate_task_card({})

        self.assertEqual(result["score"], 0)
        self.assertEqual(result["readiness_level"], "draft")
        self.assertEqual(len(result["breakdown"]), 7)
        self.assertIn("expected_result", result["missing_information"])
        self.assertTrue(result["improvement_suggestions"])

    def test_complete_card_receives_full_score(self):
        card = {
            "context": "Support agents manually prioritize tickets.",
            "business_need": "Urgent requests should not be missed.",
            "available_data": {
                "description": "Anonymized ticket exports",
                "sources": ["Support desk"],
                "access_conditions": "Secure shared folder",
            },
            "expected_result": "A working prioritization prototype.",
            "success_criteria": [
                {
                    "metric": "Priority classification accuracy",
                    "target": "80% or more",
                    "verification_method": "Compare to labelled test set",
                }
            ],
            "limitations": ["No personal data", "Four-week scope"],
            "target_users": ["Support agents"],
            "business_contact": {"name": "Aida", "role": "Support lead", "email": "a@example.test"},
            "interaction_format": {"channel": "Video call", "frequency": "Weekly", "feedback_process": "Demo"},
        }

        result = evaluate_task_card(card)

        self.assertEqual(result["score"], 100)
        self.assertEqual(result["readiness_level"], "priority")
        self.assertEqual(result["missing_information"], [])

    def test_readiness_boundaries(self):
        self.assertEqual(readiness_level(0), "draft")
        self.assertEqual(readiness_level(39), "draft")
        self.assertEqual(readiness_level(40), "working")
        self.assertEqual(readiness_level(69), "working")
        self.assertEqual(readiness_level(70), "ready")
        self.assertEqual(readiness_level(89), "ready")
        self.assertEqual(readiness_level(90), "priority")

