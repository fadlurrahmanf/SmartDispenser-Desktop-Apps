import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from functional_web_startup import Api


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class Label:
    def __init__(self, text):
        self.text = text

    def cget(self, key):
        if key != "text":
            raise KeyError(key)
        return self.text


def app_for(phase, *, present=False, holding=False, seconds=0, title="Trying to connect to device", session="SESSION: LOCKED", reader=None):
    return SimpleNamespace(
        startup_phase=phase,
        startup_active=True,
        startup_registration_card_present=present,
        startup_hold_active=holding,
        startup_hold_seconds=seconds,
        startup_title=Label(title),
        startup_detail=Label("Verifying COM3 at 115200 baud..."),
        status=Value("Starting"),
        session_state=Value(session),
        reader=reader,
    )


class FunctionalStartupTest(unittest.TestCase):
    def test_action_returns_state_in_one_runtime_dispatch(self):
        calls = []
        app = SimpleNamespace(show_page=lambda page: calls.append(("page", page)))

        class Runtime:
            call_count = 0

            def call(self, function):
                self.call_count += 1
                return function(app)

        runtime = Runtime()
        with patch.object(Api, "_snapshot", return_value={"screen": "topup_workspace"}):
            result = Api(runtime).action("show_page", {"page": "dashboard"})
        self.assertEqual(runtime.call_count, 1)
        self.assertEqual(calls, [("page", "dashboard")])
        self.assertEqual(result["screen"], "topup_workspace")

    def test_board_state_uses_perso_search_visual(self):
        state = Api._snapshot(app_for("board"))
        self.assertEqual((state["screen"], state["state"]), ("splash", "Searching for device"))
        self.assertEqual(state["view"]["title"], "Trying to connect to device")

    def test_master_registration_states_follow_live_card_and_hold(self):
        self.assertEqual(Api._screen_state(app_for("master_registration")), ("gate", "Waiting for card"))
        self.assertEqual(
            Api._screen_state(app_for("master_registration", present=True)),
            ("gate", "Card detected"),
        )
        state = Api._snapshot(app_for("master_registration", present=True, holding=True, seconds=4))
        self.assertEqual((state["screen"], state["state"]), ("gate", "Holding 10 seconds"))
        self.assertIn("width:40%", state["view"]["holdBar"])

    def test_master_detection_uses_perso_intermediate_feedback(self):
        state = Api._snapshot(app_for("master", title="Card detected", reader=object()))
        self.assertEqual(state["view"]["action"], "VERIFYING CARD")
        self.assertEqual(state["view"]["lampLabel"], "Card Detected")
        self.assertEqual(state["view"]["lampColor"], "var(--color-accent)")

    def test_waiting_master_message_is_shown_only_in_status_row(self):
        state = Api._snapshot(app_for("master", title="Activate Topup session", reader=object()))
        self.assertEqual(state["view"]["detail"], "")
        self.assertEqual(state["view"]["lampLabel"], "Waiting for master card")
        self.assertEqual(state["view"]["spinnerText"], "Waiting for master card verification...")

    def test_verified_master_uses_perso_green_feedback(self):
        state = Api._snapshot(app_for(
            "ready",
            title="Master card verified",
            session="SESSION: ACTIVE",
            reader=object(),
        ))
        self.assertEqual(state["view"]["action"], "MASTER CARD VERIFIED")
        self.assertEqual(state["view"]["lampLabel"], "Master Card Verified")
        self.assertEqual(state["view"]["lampColor"], "oklch(0.76 0.13 152)")
        self.assertIn("box-shadow", state["view"]["lampStyle"])
        self.assertTrue(state["view"]["sessionOpen"])

    def test_topup_uses_the_exact_perso_visual_template(self):
        topup = Path(__file__).resolve().parents[1]
        perso = topup.parent / "windows_perso"

        def template(path):
            text = path.read_text(encoding="utf-8")
            match = re.search(r'<script type="__bundler/template">\s*([\s\S]*?)\s*</script>', text)
            self.assertIsNotNone(match)
            return json.loads(match.group(1))

        filename = "SmartDispenser Console (functional).html"
        topup_template = template(topup / "mock" / filename)
        perso_template = template(perso / "mock" / filename)
        marker = "\n</body></html>"
        perso_prefix = perso_template[:perso_template.rfind(marker)]
        normalized = topup_template.replace(
            "    /* Topup owns the single backend polling loop. */",
            "    this.startBackendBridge();",
            1,
        )
        self.assertTrue(normalized.startswith(perso_prefix))
        self.assertTrue(topup_template.endswith(marker))

    def test_topup_workspace_has_large_active_balance(self):
        html = (Path(__file__).resolve().parents[1] / "tools" / "build_startup_html.py").read_text(encoding="utf-8")
        self.assertIn("tw-balance-hero", html)
        self.assertIn("tw-balance-number", html)
        self.assertIn("Saldo air tersimpan", html)
        self.assertIn("Status kartu tersimpan", html)
        self.assertIn("Jadwal tersimpan", html)
        self.assertIn("Nilai di atas dibaca dari kartu", html)
        self.assertIn("Biarkan kartu tetap menempel", html)
        self.assertIn("Pilih satu perubahan", html)
        self.assertIn("Konfirmasi dan tunggu verifikasi", html)
        self.assertIn("Lepas kartu untuk selesai", html)
        self.assertIn("TAMBAH KUOTA", html)
        self.assertIn("KURANGI KUOTA", html)
        self.assertIn(".tw-card-facts .tw-card-fact:first-child{display:none}", html)

    def test_overview_does_not_repeat_startup_requirements(self):
        html = (Path(__file__).resolve().parents[1] / "tools" / "build_startup_html.py").read_text(encoding="utf-8")
        self.assertNotIn("Startup requirements", html)
        self.assertNotIn("Topup operation</div>", html)
        self.assertIn("function dashboard(v){var q=v.quotaOverview", html)
        self.assertIn("Waiting for customer card", html)
        self.assertIn("Distribusi kuota per jadwal", html)
        self.assertIn("tw-quota-bars", html)
        self.assertIn("Maksimal hari ini", html)
        self.assertIn("Dialokasikan hari ini", html)
        self.assertIn("Sisa hari ini", html)
        self.assertIn("Maksimal kuota hari ini", html)
        self.assertIn("save_distribution_quota", html)
        self.assertNotIn("Terpakai hari ini</div><div class=\"tw-quota-number\"", html)

    def test_collapsed_sidebar_reserves_space_above_first_menu(self):
        html = (Path(__file__).resolve().parents[1] / "tools" / "build_startup_html.py").read_text(encoding="utf-8")
        self.assertIn(".tw-side.closed .tw-brand{height:88px;padding:0}", html)

    def test_topup_theme_toggle_changes_root_and_persists_choice(self):
        html = (Path(__file__).resolve().parents[1] / "tools" / "build_startup_html.py").read_text(encoding="utf-8")
        self.assertIn("function applyTopupTheme(theme)", html)
        self.assertIn("root.style.setProperty(name,palette[name])", html)
        self.assertIn("root.setAttribute('data-perso-theme',theme)", html)
        self.assertIn("localStorage.setItem('smartdispenser-perso-theme',theme)", html)

    def test_topup_uses_one_non_overlapping_backend_poll_and_deduplicates_render(self):
        html = (Path(__file__).resolve().parents[1] / "tools" / "build_startup_html.py").read_text(encoding="utf-8")
        self.assertIn("backendPollInFlight", html)
        self.assertIn("signature===lastBackendSignature", html)
        self.assertIn("setTimeout(pollBackend,100)", html)
        self.assertIn("Topup owns the single backend polling loop", html)
        self.assertNotIn("setInterval(function(){if(window.pywebview", html)


if __name__ == "__main__":
    unittest.main()
