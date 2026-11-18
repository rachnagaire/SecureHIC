import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from dashboard import app


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_dashboard_page_and_demo_notice_are_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"DEMO ENVIRONMENT", response.data)
        self.assertIn(b"fictional", response.data)

    def test_overview_uses_demo_claims_without_fraud_determinations(self):
        response = self.client.get("/api/overview")
        self.assertEqual(response.status_code, 200)
        overview = response.get_json()
        self.assertEqual(overview["members_monitored"], 4)
        self.assertEqual(overview["needs_review"], 4)
        self.assertEqual(overview["potential_exposure"], 12100)

    def test_claim_search_and_status_filter(self):
        response = self.client.get("/api/claims?status=Needs%20review&q=imaging")
        claims = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([claim["id"] for claim in claims], ["CLM-80421"])
        self.assertEqual(claims[0]["patient"], "Amelia Chen")

    def test_patient_profile_returns_claim_history_and_unknown_is_not_found(self):
        response = self.client.get("/api/patients/MBR-1048")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "Amelia Chen")
        self.assertEqual(len(response.get_json()["claims"]), 2)
        self.assertEqual(self.client.get("/api/patients/unknown").status_code, 404)


if __name__ == "__main__":
    unittest.main()
