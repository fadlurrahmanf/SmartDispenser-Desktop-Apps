from __future__ import annotations

import sys
import threading
from datetime import date
from pathlib import Path
from typing import Any, Callable

import webview

from app_perso_style import TopupConsole


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
HTML = ROOT / "mock" / "SmartDispenser Console (functional).html"


class TopupRuntime:
    """Run the existing Topup backend on its Tk thread behind the Perso shell."""

    def __init__(self) -> None:
        self.ready = threading.Event()
        self.closed = False
        self.startup_error: BaseException | None = None
        self.app: TopupConsole | None = None
        self.thread = threading.Thread(target=self._run, name="topup-backend")
        self.thread.start()
        if not self.ready.wait(60):
            detail = f": {self.startup_error}" if self.startup_error else " after 60 seconds"
            raise RuntimeError(f"Topup backend did not start{detail}.")

    def _run(self) -> None:
        try:
            self.app = TopupConsole(headless=True)
            # Signal only after Tk has entered its own event queue. Calls made
            # before this point can fail even though the root object exists.
            self.app.after(0, self.ready.set)
            self.app.mainloop()
        except BaseException as error:
            self.startup_error = error
            self.ready.set()

    def call(self, function: Callable[[TopupConsole], Any], timeout: float = 8.0) -> Any:
        if self.closed or self.app is None:
            raise RuntimeError("Topup backend is not available.")
        finished = threading.Event()
        result: dict[str, Any] = {}

        def invoke() -> None:
            try:
                result["value"] = function(self.app)  # type: ignore[arg-type]
            except Exception as error:
                result["error"] = error
            finally:
                finished.set()

        self.app.after(0, invoke)
        if not finished.wait(timeout):
            raise TimeoutError("Topup backend did not answer in time.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def show_workspace(self) -> None:
        def show(app: TopupConsole) -> None:
            app.deiconify()
            app.state("zoomed")
            app.lift()
            app.attributes("-topmost", True)
            app.focus_force()
            app.after(250, lambda: app.attributes("-topmost", False))

        self.call(show)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.app is not None:
            try:
                self.app.after(0, self.app.on_close)
            except Exception:
                pass


class Api:
    def __init__(self, runtime: TopupRuntime) -> None:
        self.runtime = runtime

    def get_state(self) -> dict[str, Any]:
        return self.runtime.call(self._snapshot)

    def action(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}

        def run(app: TopupConsole) -> dict[str, Any]:
            if name == "master_hold_start":
                app._begin_startup_master_hold()
            elif name == "master_hold_stop":
                app._cancel_startup_master_hold()
            elif name == "show_page":
                app.show_page(str(payload.get("page", "dashboard")))
            elif name == "read_card":
                app.read_card()
            elif name == "change":
                app.change_confirmed(str(payload.get("operation", "")), payload.get("value"))
            elif name == "history_search":
                app.history_query.set(str(payload.get("term", "")))
                app.refresh_history()
            elif name == "refresh_logs":
                app.refresh_logs()
            elif name == "save_distribution_quota":
                app.save_distribution_quota(payload.get("liters"))
            return self._snapshot(app)

        # Action and resulting snapshot share one Tk dispatch. This avoids the
        # former extra bridge round-trip and artificial 50 ms UI delay.
        return self.runtime.call(run)

    @staticmethod
    def _screen_state(app: TopupConsole) -> tuple[str, str]:
        if app.startup_phase == "master_registration":
            if app.startup_hold_active:
                return "gate", "Holding 10 seconds"
            if app.startup_registration_card_present:
                return "gate", "Card detected"
            return "gate", "Waiting for card"
        phases = {
            "database": "Database ready",
            "board": "Searching for device",
            "master": "Checking master card",
            "ready": "Activate session",
        }
        return "splash", phases.get(app.startup_phase, "Searching for device")

    @classmethod
    def _snapshot(cls, app: TopupConsole) -> dict[str, Any]:
        if not app.startup_active:
            return cls._workspace_snapshot(app)
        screen, state = cls._screen_state(app)
        title = str(app.startup_title.cget("text"))
        detail = str(app.startup_detail.cget("text"))

        phase = app.startup_phase
        if phase == "master" and title == "Activate Topup session":
            # Lamp/status row below already says that the app is waiting for
            # the master card; suppress the duplicate line below the title.
            detail = ""
        if phase == "database":
            spinner = "Connecting to the Topup database..."
        elif phase == "board":
            spinner = "Verifying the connected Topup reader..."
        elif phase == "master":
            spinner = "Waiting for master card verification..."
        else:
            spinner = "Opening Topup workspace..."

        view: dict[str, Any] = {
            "title": title,
            "detail": detail,
            "spinnerText": spinner,
            "statusBar": app.status.get(),
            "boardLabel": "Topup Board connected" if app.reader else "Topup Board checking",
            "boardReady": bool(app.reader),
            "sessionOpen": app.session_state.get() == "SESSION: ACTIVE",
            "sessionLabel": "Session open" if app.session_state.get() == "SESSION: ACTIVE" else "Session locked",
            "masterRegistered": phase == "ready",
        }

        if screen in ("splash", "gate"):
            if title == "Card detected":
                action = "VERIFYING CARD"
            elif title == "Master card verified":
                action = "MASTER CARD VERIFIED"
            elif phase == "master":
                action = "WAITING FOR MASTER CARD"
            else:
                action = "STARTING"

            if title == "Master card verified":
                lamp_label = "Master Card Verified"
                lamp_color = "oklch(0.76 0.13 152)"
                lamp_style = (
                    "width:9px;height:9px;border-radius:50%;flex:none;"
                    "background:oklch(0.76 0.13 152);"
                    "box-shadow:0 0 0 3px color-mix(in srgb, oklch(0.76 0.13 152) 22%, transparent);"
                )
            elif title == "Card detected":
                lamp_label = "Card Detected"
                lamp_color = "var(--color-accent)"
                lamp_style = (
                    "width:9px;height:9px;border-radius:50%;flex:none;"
                    "background:var(--color-accent);box-shadow:0 0 0 3px transparent;"
                )
            else:
                lamp_label = "Waiting for master card"
                lamp_color = "var(--color-neutral-600)"
                lamp_style = (
                    "width:9px;height:9px;border-radius:50%;flex:none;"
                    "background:var(--color-neutral-700);box-shadow:0 0 0 3px transparent;"
                    "animation:blink 1.4s steps(1,end) infinite;"
                )
            view.update({
                "action": action,
                "lampLabel": lamp_label,
                "lampColor": lamp_color,
                "lampStyle": lamp_style,
            })

        if screen == "gate":
            seconds = max(0, min(10, int(app.startup_hold_seconds)))
            if app.startup_hold_active:
                view.update({
                    "holdLabel": f"Holding... {seconds} s / 10 s",
                    "holdBar": f"height:100%;width:{seconds * 10}%;background:var(--color-accent);",
                    "lampLabel": f"Card detected - {10 - seconds} s remaining",
                    "holdDisabled": False,
                })
            else:
                view["holdDisabled"] = not app.startup_registration_card_present

        return {"screen": screen, "state": state, "view": view}

    @staticmethod
    def _tree_rows(tree: Any) -> list[list[str]]:
        if tree is None:
            return []
        return [[str(value) for value in tree.item(item, "values")] for item in tree.get_children()]

    @classmethod
    def _workspace_snapshot(cls, app: TopupConsole) -> dict[str, Any]:
        page = app.current_page or "dashboard"
        wallet = app.wallet
        session_ready = app._session_ready()
        wallet_ready = bool(wallet and session_ready and app.store)
        history = cls._tree_rows(getattr(app, "history_table", None))
        logs = cls._tree_rows(getattr(app, "log_table", None))
        view: dict[str, Any] = {
            "page": page,
            "busy": app.busy,
            "statusBar": app.status.get(),
            "databaseReady": app.store is not None,
            "boardReady": app.reader is not None,
            "sessionOpen": session_ready,
            "databaseLabel": app.database_state.get(),
            "boardLabel": app.board_state.get(),
            "sessionLabel": app.session_state.get(),
            "canRead": session_ready and not app.busy,
            "canMutate": wallet_ready and not app.busy,
            "walletLoaded": wallet is not None,
            "cardReference": wallet.card_reference if wallet else "",
            "balanceLiter": wallet.balance if wallet else 0,
            "cardActive": bool(wallet.active) if wallet else False,
            "scheduleCode": wallet.schedule if wallet else 0,
            "reservedLiter": wallet.reserved if wallet else 0,
            "walletRevision": wallet.revision if wallet else 0,
            "balance": f"{wallet.balance} L" if wallet else "— L",
            "cardStatus": ("Active" if wallet.active else "Inactive") if wallet else "Not checked",
            "schedule": app.schedule_text.get(),
            "walletTitle": app.card_title.get(),
            "walletDetail": app.card_detail.get(),
            "usage": app.usage_text.get(),
            "ownerTitle": app.owner_title.get(),
            "ownerDetail": app.owner_detail.get(),
            "quotaOverview": app.quota_overview_data,
            "quotaDate": date.today().strftime("%d/%m/%Y"),
            "historySearch": app.history_query.get(),
            "history": history,
            "logs": logs,
            "testTitle": getattr(app, "card_test_title", None).get() if hasattr(app, "card_test_title") else "Waiting for card",
            "testDetail": getattr(app, "card_test_detail", None).get() if hasattr(app, "card_test_detail") else "",
            "testCount": getattr(app, "card_test_counter", None).get() if hasattr(app, "card_test_counter") else "0 card detections",
            "testPresent": bool(getattr(app, "card_test_present", False)),
        }
        return {"screen": "topup_workspace", "state": page, "view": view}


def main() -> int:
    if not HTML.is_file():
        raise FileNotFoundError(f"Functional startup HTML was not generated: {HTML}")

    runtime = TopupRuntime()
    api = Api(runtime)
    window = webview.create_window(
        "SmartDispenser — Topup Console",
        HTML.as_uri(),
        js_api=api,
        width=1366,
        height=768,
        min_size=(1060, 720),
        maximized=True,
        focus=True,
    )
    window.events.closed += runtime.close
    webview.start(debug=False)
    runtime.close()
    runtime.thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
