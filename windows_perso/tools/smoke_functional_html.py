from __future__ import annotations

import sys
import time
from pathlib import Path

import webview


class OfflineApi:
    def get_state(self):
        return {
            "screen": "splash",
            "state": "Database ready",
            "view": {
                "statusBar": "Offline UI smoke test",
                "boardLabel": "Reader offline",
                "boardReady": False,
                "sessionOpen": False,
            },
        }

    def action(self, _name, _payload=None):
        return self.get_state()


html = Path(__file__).resolve().parents[1] / "mock" / "SmartDispenser Console (functional).html"
window = webview.create_window(
    "SmartDispenser Perso HTML - Offline Smoke Test",
    html.as_uri(),
    js_api=OfflineApi(),
    width=1060,
    height=720,
)
failure: list[str] = []


def close_after_load():
    try:
        time.sleep(2)
        before = window.evaluate_js(
            """
            (function () {
              var button = document.querySelector('[data-theme-toggle]');
              if (!button) return { ok: false, reason: 'theme toggle not found' };
              return {
                ok: true,
                theme: document.documentElement.getAttribute('data-perso-theme'),
                icon: button.querySelector('i').className,
                background: getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim()
              };
            })();
            """
        )
        if not before or not before.get("ok"):
            failure.append(f"Theme toggle unavailable: {before}")
            return

        window.evaluate_js("document.querySelector('[data-theme-toggle]').click()")
        time.sleep(0.3)
        after = window.evaluate_js(
            """
            (function () {
              var button = document.querySelector('[data-theme-toggle]');
              return {
                theme: document.documentElement.getAttribute('data-perso-theme'),
                icon: button.querySelector('i').className,
                background: getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim(),
                saved: window.localStorage.getItem('smartdispenser-perso-theme')
              };
            })();
            """
        )
        expected = "light" if before.get("theme") == "dark" else "dark"
        expected_icon = "ph ph-sun" if expected == "light" else "ph ph-moon"
        if after.get("theme") != expected or after.get("saved") != expected:
            failure.append(f"Theme did not toggle or persist: before={before}, after={after}")
        elif after.get("icon") != expected_icon:
            failure.append(f"Theme icon did not change: {after}")
        elif after.get("background") == before.get("background"):
            failure.append(f"Theme palette did not change: before={before}, after={after}")
    except Exception as error:
        failure.append(str(error))
    finally:
        window.destroy()


webview.start(close_after_load, debug=False)
if failure:
    raise RuntimeError("; ".join(failure))
print("OK: functional HTML rendered and theme toggle verified in WebView2")
raise SystemExit(0)
