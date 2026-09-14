"""Smoke test startup Topup tanpa membuka COM atau Database produksi."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


os.environ["LOCALAPPDATA"] = tempfile.mkdtemp(prefix="SmartDispenserTopupSmoke_")
os.environ["SMARTDISPENSER_TOPUP_SKIP_BOARD_DISCOVERY"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_perso_style import TopupConsole  # noqa: E402
from topup_core import TopupError  # noqa: E402


class OfflineTopupConsole(TopupConsole):
    def _startup_provision_database(self):
        self.startup_provision_attempted = True
        self.after(0, lambda: self._startup_database_failed(TopupError("Smoke test: provisioning intentionally unavailable")))

    @staticmethod
    def _find_topup_board():
        raise TopupError("Smoke test: Board intentionally unavailable")


app = OfflineTopupConsole(headless=True)
try:
    assert app.startup_active
    assert app.startup_title.cget("text") == "Verifying Database"
    app.after(3000, app.quit)
    app.mainloop()
    assert app.startup_active
    assert app.database_state.get() == "DATABASE: UNAVAILABLE"
    assert app.board_state.get() == "BOARD: SEARCHING"
    assert "dashboard" not in getattr(app, "pages", {})
    app._show_main()  # Build-only check; production startup never takes this path.
    assert "dashboard" in app.pages
    assert "settings" not in app.pages
    assert "settings" not in app.nav_buttons
    app.toggle_sidebar()
    app.after(700, app.quit)
    app.mainloop()
    assert app.sidebar_collapsed
    assert not app.sidebar_animating
    assert app.navigation.winfo_width() == 58
    print("OK: failed startup stays gated before Home; shell and sidebar still render")
finally:
    app.destroy()
