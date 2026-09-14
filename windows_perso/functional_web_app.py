from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import webview

from app import PersoApp, customer_field_is_readonly


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
HTML = ROOT / "mock" / "SmartDispenser Console (functional).html"


def _tag(card_status: str) -> tuple[str, str]:
    if "PERSONALIZED" in card_status and "NOT" not in card_status:
        return "Active card", "tag tag-accent"
    if "INACTIVE" in card_status:
        return "Inactive", "tag tag-neutral"
    return "No card", "tag tag-outline"


class PersoRuntime:
    def __init__(self) -> None:
        self.ready = threading.Event()
        self.closed = False
        self.app: PersoApp | None = None
        self.new_customer_mode = False
        self.thread = threading.Thread(target=self._run, name="perso-backend", daemon=True)
        self.thread.start()
        if not self.ready.wait(15):
            raise RuntimeError("Perso backend did not start.")

    def _run(self) -> None:
        self.app = PersoApp(headless=True)
        self.ready.set()
        self.app.mainloop()

    def call(self, function: Callable[[PersoApp], Any], timeout: float = 8.0) -> Any:
        if self.closed or self.app is None:
            raise RuntimeError("Perso backend is not available.")
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
            raise TimeoutError("Perso backend did not answer in time.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

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
    def __init__(self, runtime: PersoRuntime) -> None:
        self.runtime = runtime

    def get_state(self) -> dict[str, Any]:
        return self.runtime.call(self._snapshot)

    def action(self, name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}

        def run(app: PersoApp) -> None:
            page_map = {
                "test": "test", "owner": "owner", "customers": "customers",
                "perso": "debug", "logs": "logs",
            }
            if name == "show_page":
                app.show_page(page_map.get(str(payload.get("page")), "customers"))
            elif name == "test_start":
                app.start_card_test()
            elif name == "test_stop":
                app.stop_card_test()
            elif name == "owner_start":
                app.start_owner_lookup()
            elif name == "owner_stop":
                app.stop_owner_lookup()
            elif name == "customer_search":
                app.customer_search.set(str(payload.get("term", "")))
                app.load_customers()
            elif name == "customer_clear_search":
                app.clear_customer_search()
            elif name == "customer_new":
                self.runtime.new_customer_mode = True
                app.web_new_customer_mode = True
                app.clear_customer_form()
            elif name == "customer_deselect":
                self.runtime.new_customer_mode = False
                app.web_new_customer_mode = False
                app.clear_customer_form()
            elif name == "customer_draft":
                fields = payload.get("fields") or {}
                draft_targets = {
                    "nik": app.customer_form_nik,
                    "kk": app.customer_form_kk,
                    "name": app.customer_form_name,
                    "phone": app.customer_form_phone,
                    "address": app.customer_form_address,
                    "status": app.customer_form_status,
                }
                for key, target in draft_targets.items():
                    if key in fields:
                        target.set(str(fields[key]))
            elif name == "customer_select":
                customer_id = str(payload.get("id", ""))
                if customer_id and app.customer_tree.exists(customer_id):
                    self.runtime.new_customer_mode = False
                    app.web_new_customer_mode = False
                    app.customer_tree.selection_set(customer_id)
                    app.customer_tree.focus(customer_id)
                    app.on_customer_tree_selected()
            elif name in ("customer_save", "customer_update"):
                fields = payload.get("fields") or {}
                app.customer_form_nik.set(str(fields.get("nik", "")))
                app.customer_form_kk.set(str(fields.get("kk", "")))
                app.customer_form_name.set(str(fields.get("name", "")))
                app.customer_form_phone.set(str(fields.get("phone", "")))
                app.customer_form_address.set(str(fields.get("address", "")))
                app.customer_form_status.set(str(fields.get("status", "active")))
                if name == "customer_save":
                    app.save_new_customer()
                else:
                    app.update_customer()
            elif name == "personalize_customer":
                app.open_selected_customer_personalization()
            elif name == "personalize_commit":
                app.begin_personalization_commit()
            elif name == "perso_remove":
                app.begin_remove_personalization()
            elif name == "logs_toggle":
                app.toggle_log_order()
            elif name == "logs_clear":
                app.clear_logs()
            elif name == "serial_clear_view":
                app.clear_parsed_serial_monitor()
            elif name == "master_hold_start":
                app.begin_hold("register_master")
            elif name == "master_hold_stop":
                app.cancel_hold()

        self.runtime.call(run)
        time.sleep(0.08)
        return self.get_state()

    def _snapshot(self, app: PersoApp) -> dict[str, Any]:
        screen, state = self._screen_state(app)
        view: dict[str, Any] = {
            "statusBar": app.status.get(),
            "boardLabel": "Reader connected" if app.transport else "Reader offline",
            "boardReady": bool(app.transport and app.last_nfc_ready is not False),
            "sessionOpen": app.last_session_open is True,
            "sessionLabel": "Session open" if app.last_session_open is True else "Session locked",
            "masterRegistered": app.last_master_registered is True,
        }
        if screen in ("splash", "gate"):
            startup_title = str(app.loading_title.cget("text"))
            startup_detail = str(app.loading_detail.cget("text"))
            if startup_title == "Card detected":
                startup_action = "VERIFYING CARD"
            elif startup_title == "Card not verified":
                startup_action = "NOT THE MASTER CARD"
            elif startup_title == "Master card verified":
                startup_action = "MASTER CARD VERIFIED"
            elif app.startup_phase == "session_open":
                startup_action = "WAITING FOR MASTER CARD"
            else:
                startup_action = "STARTING"
            if startup_title == "Master card verified":
                lamp_label = "Master Card Verified"
                lamp_color = "oklch(0.76 0.13 152)"
                lamp_style = (
                    "width:9px;height:9px;border-radius:50%;flex:none;"
                    "background:oklch(0.76 0.13 152);"
                    "box-shadow:0 0 0 3px color-mix(in srgb, oklch(0.76 0.13 152) 22%, transparent);"
                )
            elif startup_title == "Card detected":
                lamp_label = "Card Detected"
                lamp_color = "var(--color-accent)"
                lamp_style = (
                    "width:9px;height:9px;border-radius:50%;flex:none;"
                    "background:var(--color-accent);box-shadow:0 0 0 3px transparent;"
                )
            elif startup_title == "Card not verified":
                lamp_label = "Not The Master Card"
                lamp_color = "oklch(0.70 0.16 25)"
                lamp_style = (
                    "width:9px;height:9px;border-radius:50%;flex:none;"
                    "background:oklch(0.70 0.16 25);box-shadow:0 0 0 3px transparent;"
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
                "title": startup_title,
                "detail": startup_detail,
                "action": startup_action,
                "lampLabel": lamp_label,
                "lampColor": lamp_color,
                "lampStyle": lamp_style,
            })
        elif screen == "test":
            view.update({
                "result": app.card_test_status.get(),
                "sub": app.card_test_count.get(),
                "action": "Reader test active" if app.card_test_confirmed else "Start card test",
                "showStop": bool(app.card_test_active),
            })
        elif screen == "owner":
            record = dict(getattr(app, "owner_lookup_record", {}) or {})
            owner_rows = [
                {"label": "Card Number", "value": record.get("card_number", app.owner_lookup_reference.get().replace("Card Number: ", "") or "—")},
                {"label": "Customer Number", "value": record.get("customer_number", "—")},
                {"label": "Full Name", "value": record.get("full_name", "—")},
                {"label": "NIK", "value": record.get("nik", "—")},
                {"label": "Family Card / KK", "value": record.get("kk", "—")},
                {"label": "Customer Status", "value": record.get("status", "—").capitalize()},
                {"label": "Activated", "value": record.get("activated_at", "—")},
            ]
            view.update({
                "result": app.owner_lookup_status.get(),
                "reference": app.owner_lookup_reference.get().replace("Card Number: ", ""),
                "owner": app.owner_lookup_customer.get(),
                "details": app.owner_lookup_details.get(),
                "action": "Lookup running" if app.owner_lookup_confirmed else "Start owner lookup",
                "ownerRows": owner_rows,
            })
        elif screen == "customers":
            rows = []
            if app.last_session_open is True:
                for item in app.customer_tree.get_children():
                    number, customer_name, nik, card_status = app.customer_tree.item(item, "values")
                    tag, tag_class = _tag(str(card_status))
                    rows.append({"id": item, "number": number, "name": customer_name, "nik": nik, "card": tag, "tagClass": tag_class})
            selected = app.selected_customer_id is not None
            has_active_card = selected and app.selected_customer_card_status.get().startswith("Card: PERSONALIZED")
            field_style = lambda readonly: "color:var(--color-neutral-500);cursor:not-allowed;" if readonly else ""
            fields = [
                {"key": "number", "label": "Customer number", "value": app.customer_form_number.get(), "placeholder": "—", "readonly": True, "style": field_style(True)},
                {"key": "nik", "label": "NIK (16 digits)", "value": app.customer_form_nik.get(), "placeholder": "16 digits", "readonly": customer_field_is_readonly("nik", has_active_card), "style": field_style(customer_field_is_readonly("nik", has_active_card))},
                {"key": "kk", "label": "Family Card / KK (16 digits)", "value": app.customer_form_kk.get(), "placeholder": "16 digits", "readonly": customer_field_is_readonly("kk", has_active_card), "style": field_style(customer_field_is_readonly("kk", has_active_card))},
                {"key": "name", "label": "Full name", "value": app.customer_form_name.get(), "placeholder": "As printed on the ID card", "readonly": customer_field_is_readonly("name", has_active_card), "style": field_style(customer_field_is_readonly("name", has_active_card))},
                {"key": "phone", "label": "Phone", "value": app.customer_form_phone.get(), "placeholder": "08••", "readonly": False, "style": ""},
                {"key": "address", "label": "Address", "value": app.customer_form_address.get(), "placeholder": "Street, city", "readonly": False, "style": ""},
                {"key": "status", "label": "Status", "value": app.customer_form_status.get(), "placeholder": "active / inactive", "readonly": False, "style": ""},
            ]
            view.update({
                "rows": rows, "fields": fields, "search": app.customer_search.get(),
                "showDetails": selected or self.runtime.new_customer_mode,
                "showDetailsRail": not (selected or self.runtime.new_customer_mode),
                "persoDisabled": not selected,
                "formTag": app.customer_form_number.get() if selected else ("New record" if self.runtime.new_customer_mode else "No selection"),
                "tableFoot": f"{len(rows)} customers · read from database",
            })
        elif screen == "perso":
            serial_rows = []
            if hasattr(app, "parsed_serial_tree"):
                for item in app.parsed_serial_tree.get_children():
                    values = list(app.parsed_serial_tree.item(item, "values"))
                    values.extend(["—"] * (8 - len(values)))
                    serial_rows.append({
                        "time": str(values[0]), "type": str(values[1]),
                        "code": str(values[2]), "nfc": str(values[3]),
                        "master": str(values[4]), "session": str(values[5]),
                        "operation": str(values[6]), "card": str(values[7]),
                    })
            view.update({
                "selectedCustomerNumber": app.selected_customer_number.get(),
                "selectedCustomerName": app.selected_customer_name.get(),
                "cardSummary": app.debug_card_summary.get(),
                "walletSummary": app.debug_wallet_summary.get(),
                "protectionSummary": app.debug_protection_summary.get(),
                "lastEvent": app.debug_last_event.get(),
                "quality": app.debug_quality.get(),
                "liveness": app.debug_liveness.get(),
                "commitDisabled": app.wallet_slot_action != "confirm",
                "precheckDone": min(10, app.technical_stage_highest),
                "writeDone": 7 if app.personalization_completed else max(0, app.personalization_active_step - 1),
                "serial": serial_rows,
                "showRemovePerso": app.wallet_slot_state == "already_used" and app.debug_card_present,
                "removePersoDisabled": app.wallet_slot_action in ("remove_arming", "removing"),
            })
        elif screen == "logs":
            ordered = list(reversed(app.log_entries)) if app.log_descending else list(app.log_entries)
            view["logs"] = [{"time": r[0], "type": r[1], "status": r[2], "operation": r[3], "color": "var(--color-neutral-300)"} for r in ordered]
            view["logsEmpty"] = not bool(ordered)
        return {"screen": screen, "state": state, "view": view}

    @staticmethod
    def _screen_state(app: PersoApp) -> tuple[str, str]:
        if not app.dashboard_ready:
            if app.startup_phase == "master_registration":
                if app.hold_command:
                    return "gate", "Holding 10 seconds"
                if app.master_registration_card_present:
                    return "gate", "Card detected"
                return "gate", "Waiting for card"
            phases = {
                "database_verify": "Database ready", "device_discovery": "Searching for device",
                "background_discovery": "Retrying connection", "master_check": "Checking master card",
                "session_lock": "Locking previous session", "session_open": "Activate session",
            }
            return "splash", phases.get(app.startup_phase, "Searching for device")
        page = getattr(app, "current_page", "customers")
        if page == "test":
            text = app.card_test_status.get().lower()
            if "detected" in text:
                state = "Card detected"
            elif "removed" in text:
                state = "Card removed"
            elif "did not confirm" in text:
                state = "Board did not confirm"
            elif app.card_test_confirmed:
                state = "Reader ready"
            else:
                state = "Not started"
            return "test", state
        if page == "owner":
            text = app.owner_lookup_status.get().lower()
            if "legacy" in text:
                state = "Legacy card"
            elif "not a valid" in text:
                state = "Not a project card"
            elif "removed" in text:
                state = "Card removed"
            elif "identified" in text or "belongs" in text:
                state = "Owner identified"
            elif app.owner_lookup_confirmed:
                state = "Reader ready"
            else:
                state = "Not started"
            return "owner", state
        if page == "debug":
            action = app.wallet_slot_action
            if app.personalization_completed:
                state = "Completed"
            elif action in ("remove_arming", "removing", "removed", "remove_failed") or app.wallet_slot_state == "already_used":
                state = "Already personalized card"
            elif action in ("writing", "result_pending"):
                state = "Writing card"
            elif action in ("failed", "failed_write"):
                state = "Write failed"
            elif action == "confirm":
                state = "Precheck passed"
            elif app.technical_scan_active or app.debug_card_present:
                state = "Precheck running"
            else:
                state = "Waiting for card"
            return "perso", state
        if page == "logs":
            return "logs", "Populated" if app.log_entries else "Empty"
        if app.last_session_open is not True:
            return "customers", "Session locked"
        if app.selected_customer_id is not None:
            return "customers", "Customer selected"
        if getattr(app, "web_new_customer_mode", False):
            return "customers", "New customer"
        return "customers", "List loaded"


def main() -> int:
    if not HTML.is_file():
        raise FileNotFoundError(f"Functional HTML was not generated: {HTML}")
    runtime = PersoRuntime()
    api = Api(runtime)
    window = webview.create_window(
        "SmartDispenser — Customer Personalization Console",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
