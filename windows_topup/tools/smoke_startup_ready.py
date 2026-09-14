"""Smoke test the three-step startup with a simulated Topup Board."""
from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app_perso_style import TopupConsole  # noqa: E402
from topup_core import SimulationReader  # noqa: E402


class ReadyTopupConsole(TopupConsole):
    @staticmethod
    def _find_topup_board():
        return SimulationReader(), "SIMULATED-TOPUP"


app = ReadyTopupConsole(headless=True)
try:
    app.after(7000, app.quit)
    app.mainloop()
    assert not app.startup_active
    assert app.database_state.get() == "DATABASE: READY"
    assert app.board_state.get() == "BOARD: SIMULATED-TOPUP"
    assert app.operator_id is not None
    assert app._session_ready()
    assert "dashboard" in app.pages
    assert "settings" not in app.pages
    assert "settings" not in app.nav_buttons
    print("OK: Database -> Topup Board -> master card -> Home")
finally:
    app.destroy()
