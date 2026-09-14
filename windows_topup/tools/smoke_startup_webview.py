from __future__ import annotations

import time
from pathlib import Path

import webview


class StartupApi:
    def get_state(self):
        return {
            "screen": "splash",
            "state": "Searching for device",
            "view": {
                "title": "Trying to connect to device",
                "detail": "Verifying COM3 at 115200 baud...",
                "spinnerText": "Verifying the connected Topup reader...",
                "statusBar": "Startup smoke test",
                "boardLabel": "Topup Board checking",
                "boardReady": False,
                "sessionOpen": False,
            },
        }

    def action(self, _name, _payload=None):
        return self.get_state()


html = Path(__file__).resolve().parents[1] / "mock" / "SmartDispenser Console (functional).html"
window = webview.create_window("Topup startup smoke test", html.as_uri(), js_api=StartupApi(), width=1366, height=768)
failures: list[str] = []


def verify() -> None:
    try:
        time.sleep(3)
        result = window.evaluate_js(
            """
            (function () {
              var text = document.body.innerText;
              var icon = document.querySelector('.ph-magnifying-glass');
              var theme = document.querySelector('[data-theme-toggle]');
              return {
                title: text.indexOf('Trying to connect to device') >= 0,
                detail: text.indexOf('Verifying COM3 at 115200 baud...') >= 0,
                spinner: text.indexOf('Verifying the connected Topup reader...') >= 0,
                icon: !!icon,
                animatedRing: Array.from(document.querySelectorAll('span')).some(function (node) {
                  return getComputedStyle(node).animationName === 'ping';
                }),
                theme: !!theme,
                oldTkBrand: text.indexOf('TOPUP CONSOLE') >= 0
              };
            })();
            """
        )
        if not result or not all(result.get(key) for key in ("title", "detail", "spinner", "icon", "animatedRing", "theme")):
            failures.append(f"Startup visual incomplete: {result}")
        elif result.get("oldTkBrand"):
            failures.append(f"Old Tk startup branding is still visible: {result}")
    except Exception as error:
        failures.append(str(error))
    finally:
        window.destroy()


webview.start(verify, debug=False)
if failures:
    raise RuntimeError("; ".join(failures))
print("OK: Topup startup rendered with the Perso WebView layout and animations")
