import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebBridgeResponsivenessTests(unittest.TestCase):
    def test_backend_polling_never_overlaps(self):
        source = (ROOT / "tools" / "build_functional_html.py").read_text(encoding="utf-8")
        self.assertIn("this.backendPending = false;", source)
        self.assertIn("if (this.backendPending) return;", source)
        self.assertIn("this.backendPending = true;", source)
        self.assertIn("finally { this.backendPending = false; }", source)

    def test_customer_search_is_debounced_before_database_call(self):
        source = (ROOT / "tools" / "build_functional_html.py").read_text(encoding="utf-8")
        self.assertIn("clearTimeout(window.__persoSearchTimer);", source)
        self.assertIn("window.__persoSearchTimer = setTimeout", source)
        self.assertIn("}, 220);", source)

    def test_action_response_has_no_artificial_sleep(self):
        source = (ROOT / "functional_web_app.py").read_text(encoding="utf-8")
        self.assertNotIn("time.sleep(0.08)", source)

    def test_master_registration_has_a_bound_start_cancel_action(self):
        source = (ROOT / "tools" / "build_functional_html.py").read_text(encoding="utf-8")
        backend = (ROOT / "functional_web_app.py").read_text(encoding="utf-8")
        self.assertIn('sc-camel-on-click="{{ masterHoldClick }}"', source)
        self.assertIn('"master_hold_start"', source)
        self.assertIn('"master_hold_stop"', source)
        self.assertIn('"masterHoldActive"', backend)
        self.assertIn('"holdBar"', backend)


if __name__ == "__main__":
    unittest.main()
