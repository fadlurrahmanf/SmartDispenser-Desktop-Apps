from __future__ import annotations

import time
from pathlib import Path

import webview


class CustomerInputApi:
    def __init__(self) -> None:
        self.draft: dict[str, str] = {}
        self.search = ""
        self.search_terms: list[str] = []

    def get_state(self):
        fields = [
            {"key": "number", "label": "Customer number", "value": "Generated when saved", "placeholder": "—", "readonly": True, "style": ""},
            {"key": "nik", "label": "NIK (16 digits)", "value": self.draft.get("nik", ""), "placeholder": "16 digits", "readonly": False, "style": ""},
            {"key": "kk", "label": "Family Card / KK (16 digits)", "value": "", "placeholder": "16 digits", "readonly": False, "style": ""},
            {"key": "name", "label": "Full name", "value": "", "placeholder": "Full name", "readonly": False, "style": ""},
            {"key": "phone", "label": "Phone", "value": "", "placeholder": "08", "readonly": False, "style": ""},
            {"key": "address", "label": "Address", "value": "", "placeholder": "Address", "readonly": False, "style": ""},
            {"key": "status", "label": "Status", "value": "active", "placeholder": "active", "readonly": False, "style": ""},
        ]
        records = [
            {"id": "1", "number": "CUST-0001", "name": "Test1", "nik": "••••3123", "card": "Active card", "tagClass": "tag tag-accent"},
            {"id": "2", "number": "CUST-0002", "name": "Test2", "nik": "••••3124", "card": "No card", "tagClass": "tag tag-outline"},
        ]
        term = self.search.casefold()
        rows = [record for record in records if not term or term in " ".join(str(value) for value in record.values()).casefold()]
        return {
            "screen": "customers",
            "state": "New customer",
            "view": {
                "statusBar": "Input smoke test",
                "boardLabel": "Reader offline",
                "boardReady": False,
                "sessionOpen": True,
                "rows": rows,
                "fields": fields,
                "search": self.search,
                "showDetails": True,
                "showDetailsRail": False,
                "persoDisabled": True,
                "formTag": "New record",
                "tableFoot": "Input smoke test",
            },
        }

    def action(self, name, payload=None):
        if name == "customer_draft":
            self.draft.update((payload or {}).get("fields") or {})
        elif name == "customer_search":
            self.search = str((payload or {}).get("term") or "")
            self.search_terms.append(self.search)
        return self.get_state()


api = CustomerInputApi()
html = Path(__file__).resolve().parents[1] / "mock" / "SmartDispenser Console (functional).html"
window = webview.create_window("Customer input smoke test", html.as_uri(), js_api=api, width=1100, height=760)
failure: list[str] = []


def verify_input() -> None:
    try:
        time.sleep(2.0)
        result = window.evaluate_js(
            """
            (function () {
              var input = document.querySelector('input[data-customer-field="nik"]');
              if (!input) return { ok: false, reason: 'NIK input not found' };
              input.focus();
              var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              setter.call(input, '1234567890123456');
              input.dispatchEvent(new Event('input', { bubbles: true }));
              return { ok: !input.readOnly, value: input.value };
            })();
            """
        )
        time.sleep(0.4)
        persisted = window.evaluate_js(
            "document.querySelector('input[data-customer-field=\"nik\"]').value"
        )
        if not result or not result.get("ok") or result.get("value") != "1234567890123456":
            failure.append(f"Input rejected: {result}")
        elif persisted != "1234567890123456":
            failure.append(f"Typed value was reset: {persisted!r}")
        elif api.draft.get("nik") != "1234567890123456":
            failure.append(f"Draft did not reach backend: {api.draft!r}")

        status_result = window.evaluate_js(
            """
            (function () {
              var select = document.querySelector('select[data-customer-field="status"]');
              if (!select) return { ok: false, reason: 'Status select not found' };
              select.value = 'inactive';
              select.dispatchEvent(new Event('input', { bubbles: true }));
              return {
                ok: !select.disabled,
                value: select.value,
                options: Array.from(select.options).map(function (item) { return item.value; })
              };
            })();
            """
        )
        time.sleep(0.3)
        if (not status_result or not status_result.get("ok")
                or status_result.get("value") != "inactive"
                or status_result.get("options") != ["active", "inactive"]):
            failure.append(f"Status options failed: {status_result}")
        elif api.draft.get("status") != "inactive":
            failure.append(f"Status did not reach backend: {api.draft!r}")

        search_result = None
        for term in ("T", "Te", "Test", "Test2"):
            search_result = window.evaluate_js(
                f"""
                (function () {{
                  var input = document.querySelector('input[data-customer-search]');
                  if (!input) return {{ ok: false, reason: 'Search input not found' }};
                  input.focus();
                  var setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                  setter.call(input, {term!r});
                  input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                  return {{ ok: !input.readOnly, value: input.value }};
                }})();
                """
            )
            time.sleep(0.2)
        search_persisted = window.evaluate_js(
            "document.querySelector('input[data-customer-search]').value"
        )
        visible_text = window.evaluate_js("document.body.innerText")
        if not search_result or not search_result.get("ok") or search_result.get("value") != "Test2":
            failure.append(f"Search input rejected: {search_result}")
        elif search_persisted != "Test2":
            failure.append(f"Search value was reset: {search_persisted!r}")
        elif api.search != "Test2":
            failure.append(f"Search did not reach backend: {api.search!r}")
        elif api.search_terms != ["T", "Te", "Test", "Test2"]:
            failure.append(f"Not every keystroke reached backend: {api.search_terms!r}")
        elif "Test2" not in visible_text or "Test1" in visible_text:
            failure.append("Customer rows did not update immediately to the latest search term")
    except Exception as error:
        failure.append(str(error))
    finally:
        window.destroy()


webview.start(verify_input, debug=False)
if failure:
    raise RuntimeError("; ".join(failure))
print("OK: customer form accepts typing, status is fixed, and every search keystroke updates visible results")
