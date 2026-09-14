from __future__ import annotations

import time
from pathlib import Path

import webview


class OperatorViewsApi:
    def __init__(self) -> None:
        self.screen = "test"

    def get_state(self):
        if self.screen == "owner":
            return {
                "screen": "owner",
                "state": "Owner identified",
                "view": {
                    "statusBar": "Owner lookup smoke test",
                    "boardLabel": "Reader connected",
                    "boardReady": True,
                    "sessionOpen": True,
                    "result": "Card owner identified.",
                    "ownerRows": [
                        {"label": "Card Number", "value": "CARD-0000001F"},
                        {"label": "Customer Number", "value": "CUST-TEST"},
                        {"label": "Full Name", "value": "Test Customer"},
                        {"label": "NIK", "value": "••••5678"},
                        {"label": "Family Card / KK", "value": "••••9012"},
                        {"label": "Customer Status", "value": "Active"},
                        {"label": "Activated", "value": "02:38 WIB - 14/09/2026"},
                    ],
                },
            }
        return {
            "screen": "test",
            "state": "Card removed",
            "view": {
                "statusBar": "Operator view smoke test",
                "boardLabel": "Reader connected",
                "boardReady": True,
                "sessionOpen": True,
                "result": "Card removed — waiting for another card.",
                "sub": "4 card detections",
                "action": "Reader test active",
                "showStop": True,
            },
        }

    def action(self, name, payload=None):
        if name == "show_page" and (payload or {}).get("page") == "owner":
            self.screen = "owner"
        return self.get_state()


api = OperatorViewsApi()
html = Path(__file__).resolve().parents[1] / "mock" / "SmartDispenser Console (functional).html"
window = webview.create_window("Operator views smoke test", html.as_uri(), js_api=api, width=1200, height=760)
failure: list[str] = []


def verify_views() -> None:
    try:
        time.sleep(2.0)
        test_result = window.evaluate_js(
            """
            (function () {
              var result = Array.from(document.querySelectorAll('div')).find(function (node) {
                return node.textContent.trim() === 'Card removed — waiting for another card.';
              });
              var card = result && result.closest('.card');
              var hand = document.querySelector('.ph-hand-tap');
              var root = document.querySelector('[data-theme-toggle]');
              root = root && root.parentElement;
              var text = document.body.innerText;
              return {
                found: !!card,
                align: card ? getComputedStyle(card).alignItems : '',
                textAlign: card ? getComputedStyle(card).textAlign : '',
                animation: hand && hand.parentElement ? getComputedStyle(hand.parentElement).animationName : '',
                hasControls: text.indexOf('Stop test') >= 0 || text.indexOf('Reader test active') >= 0,
                radius: root ? getComputedStyle(root).borderRadius : '',
                shadow: root ? getComputedStyle(root).boxShadow : ''
              };
            })();
            """
        )
        if (not test_result or not test_result.get("found")
                or test_result.get("align") != "center"
                or test_result.get("textAlign") != "center"):
            failure.append(f"Test Card is not centered: {test_result}")
        elif test_result.get("animation") != "breathe":
            failure.append(f"Test Card animation is missing: {test_result}")
        elif test_result.get("hasControls"):
            failure.append(f"Automatic Test Card still shows controls: {test_result}")
        elif test_result.get("radius") != "0px" or test_result.get("shadow") != "none":
            failure.append(f"Window corner styling remains: {test_result}")

        window.evaluate_js("document.querySelector('button[aria-label=\"Toggle sidebar\"]').click()")
        time.sleep(0.5)
        collapsed_result = window.evaluate_js(
            """
            (function () {
              var theme = document.querySelector('button[data-theme-toggle]');
              var toggle = document.querySelector('button[aria-label="Toggle sidebar"]');
              var firstNavIcon = document.querySelector('.ph-radio-button');
              var firstNav = firstNavIcon && firstNavIcon.closest('button');
              if (!theme || !toggle || !firstNav) return { found: false };
              var rects = [theme, toggle, firstNav].map(function (node) { return node.getBoundingClientRect(); });
              function overlaps(a, b) {
                return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
              }
              return {
                found: !!theme && !!toggle && !!firstNav,
                themeToggleOverlap: overlaps(rects[0], rects[1]),
                toggleMenuOverlap: overlaps(rects[1], rects[2]),
                gaps: [rects[1].top - rects[0].bottom, rects[2].top - rects[1].bottom]
              };
            })();
            """
        )
        if (not collapsed_result or not collapsed_result.get("found")
                or collapsed_result.get("themeToggleOverlap")
                or collapsed_result.get("toggleMenuOverlap")):
            failure.append(f"Collapsed sidebar controls overlap: {collapsed_result}")
        window.evaluate_js("document.querySelector('button[aria-label=\"Toggle sidebar\"]').click()")
        time.sleep(0.4)

        window.evaluate_js(
            "Array.from(document.querySelectorAll('button')).find(function (button) { return button.innerText.trim() === 'Identify Card Owner'; }).click()"
        )
        time.sleep(0.8)
        owner_result = window.evaluate_js(
            """
            (function () {
              var text = document.body.innerText;
              var tables = Array.from(document.querySelectorAll('table, sc-raw-table'));
              var ownerTable = tables.find(function (table) {
                return table.innerText.toUpperCase().indexOf('CUSTOMER NUMBER') >= 0 && table.innerText.indexOf('CUST-TEST') >= 0;
              });
              var customerNode = Array.from(document.querySelectorAll('*')).find(function (node) {
                return node.childElementCount === 0 && node.textContent.trim() === 'CUST-TEST';
              });
              return {
                found: !!ownerTable,
                hasRows: !!ownerTable && ownerTable.querySelectorAll('tr, sc-raw-tr').length === 7,
                hasControls: text.indexOf('Start owner lookup') >= 0 || text.indexOf('Lookup running') >= 0,
                hasWibTimestamp: text.indexOf('02:38 WIB - 14/09/2026') >= 0,
                text: text.slice(0, 1200),
                ancestry: customerNode ? [customerNode.tagName, customerNode.parentElement && customerNode.parentElement.tagName, customerNode.parentElement && customerNode.parentElement.parentElement && customerNode.parentElement.parentElement.tagName] : []
              };
            })();
            """
        )
        if (not owner_result or not owner_result.get("found") or not owner_result.get("hasRows")
                or not owner_result.get("hasWibTimestamp")):
            failure.append(f"Owner result table failed: {owner_result}")
        elif owner_result.get("hasControls"):
            failure.append(f"Automatic Owner Lookup still shows controls: {owner_result}")
    except Exception as error:
        failure.append(str(error))
    finally:
        window.destroy()


webview.start(verify_views, debug=False)
if failure:
    raise RuntimeError("; ".join(failure))
print("OK: centered animated Test Card, owner table, auto modes, and square corners verified")
