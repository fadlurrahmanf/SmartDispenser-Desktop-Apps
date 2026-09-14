from __future__ import annotations

import time
from pathlib import Path

import webview


class WorkspaceApi:
    def __init__(self) -> None:
        self.page = "topup"

    def get_state(self):
        return {
            "screen": "topup_workspace",
            "state": self.page,
            "view": {
                "page": self.page,
                "statusBar": "Topup workspace smoke test",
                "databaseReady": True,
                "boardReady": True,
                "sessionOpen": True,
                "databaseLabel": "DATABASE: READY",
                "boardLabel": "BOARD: COM3",
                "sessionLabel": "SESSION: ACTIVE",
                "canRead": True,
                "canMutate": True,
                "walletLoaded": True,
                "cardReference": "CARD-0000001F",
                "balanceLiter": 20,
                "cardActive": True,
                "scheduleCode": 1,
                "usedTodayLiter": 0,
                "reservedLiter": 0,
                "walletRevision": 2,
                "balance": "20 L",
                "cardStatus": "Active",
                "schedule": "Pagi",
                "walletTitle": "Wallet Data verified - Revision Revision  Revision 2",
                "walletDetail": "Card Reference: CARD-0000001F - Wallet V2 verified",
                "usage": "Used today 0 L - Reserved 0 L",
                "ownerTitle": "Card Reference: CARD-0000001F",
                "ownerDetail": "ID pencatatan kartu untuk jadwal pagi, siang, dan sore.",
                "quotaDate": "14/09/2026",
                "quotaOverview": {
                    "available_liter": 120,
                    "used_liter": 35,
                    "reserved_liter": 10,
                    "quota_limit_liter": 200,
                    "quota_configured": True,
                    "distributed_today_liter": 120,
                    "allocated_liter": 120,
                    "remaining_liter": 80,
                    "over_limit": False,
                    "card_count": 6,
                    "unscheduled_cards": 1,
                    "loading": False,
                    "error": "",
                    "schedules": [
                        {"label": "Pagi", "available_liter": 50, "used_liter": 20, "distributed_liter": 60, "card_count": 3},
                        {"label": "Siang", "available_liter": 40, "used_liter": 10, "distributed_liter": 40, "card_count": 2},
                        {"label": "Sore", "available_liter": 30, "used_liter": 5, "distributed_liter": 20, "card_count": 1},
                    ],
                },
                "historySearch": "",
                "history": [["10:00 WIB - 14/09/2026", "CARD-0000001F", "balance_adjust", "10", "10", "20"]],
                "logs": [["10:00 WIB - 14/09/2026", "wallet_read", "verified wallet read"]],
                "testTitle": "Waiting for card",
                "testDetail": "Read-only test",
                "testCount": "0 card detections",
                "testPresent": False,
            },
        }

    def action(self, name, payload=None):
        if name == "show_page":
            self.page = (payload or {}).get("page", "dashboard")
        return self.get_state()


api = WorkspaceApi()
html = Path(__file__).resolve().parents[1] / "mock" / "SmartDispenser Console (functional).html"
window = webview.create_window("Topup workspace smoke test", html.as_uri(), js_api=api, width=1366, height=768)
failures: list[str] = []


def verify() -> None:
    try:
        time.sleep(6)
        result = window.evaluate_js(
            """
            (function () {
              var host=document.getElementById('topup-web-app');
              var side=document.querySelector('.tw-side');
              var head=document.querySelector('.tw-head');
              var original=document.querySelector('x-dc');
              var text=host ? host.innerText : '';
              return {
                visible: host && getComputedStyle(host).display === 'block',
                originalHidden: !original || getComputedStyle(original).display === 'none',
                sidebarWidth: side ? Math.round(side.getBoundingClientRect().width) : 0,
                headerHeight: head ? Math.round(head.getBoundingClientRect().height) : 0,
                hasTopup: text.indexOf('Kelola kartu pelanggan') >= 0 && text.indexOf('20 L') >= 0,
                hasInstructions: document.querySelectorAll('.tw-howto-step').length === 4,
                hasClearActions: text.indexOf('TAMBAH KUOTA') >= 0 && text.indexOf('KURANGI KUOTA') >= 0,
                hasStoredState: text.toUpperCase().indexOf('STATUS KARTU TERSIMPAN') >= 0 && text.indexOf('Aktif') >= 0,
                hasStoredSchedule: text.toUpperCase().indexOf('JADWAL TERSIMPAN') >= 0 && text.indexOf('Pagi') >= 0,
                hidesUsedToday: text.toUpperCase().indexOf('TERPAKAI HARI INI') < 0,
                selectedSchedule: !!document.querySelector('.tw-btn.selected') && document.querySelector('.tw-btn.selected').innerText.indexOf('Pagi') >= 0,
                hasMenus: text.indexOf('Test Card') >= 0 && text.indexOf('Activity Logs') >= 0,
                hasTheme: !!document.querySelector('.tw-theme'),
                font: host ? getComputedStyle(host).fontFamily : '',
                topupThemeType: typeof window.topupTheme,
                apiType: window.pywebview && window.pywebview.api ? typeof window.pywebview.api.get_state : 'missing',
                bodyText: document.body.innerText.slice(0, 600)
              };
            })();
            """
        )
        if not result or not all(result.get(key) for key in ("visible", "originalHidden", "hasTopup", "hasMenus", "hasTheme", "hasInstructions", "hasClearActions", "hasStoredState", "hasStoredSchedule", "hidesUsedToday", "selectedSchedule")):
            failures.append(f"Workspace shell incomplete: {result}")
        elif result.get("sidebarWidth") != 214 or result.get("headerHeight") != 86:
            failures.append(f"Perso shell dimensions differ: {result}")
        render_count = window.evaluate_js("window.__topupRenderCount || 0")
        time.sleep(0.7)
        stable_render_count = window.evaluate_js("window.__topupRenderCount || 0")
        if stable_render_count != render_count:
            failures.append(f"Unchanged backend state rerendered: {render_count} -> {stable_render_count}")
        window.evaluate_js("window.topupGo('dashboard')")
        time.sleep(1)
        overview = window.evaluate_js(
            """
            (function () {
              var host=document.getElementById('topup-web-app');
              var text=host ? host.innerText : '';
              var bars=document.querySelectorAll('.tw-quota-row');
              return {
                waiting: text.indexOf('Waiting for customer card') >= 0,
                title: text.indexOf('Distribusi kuota per jadwal') >= 0,
                totals: text.indexOf('200 L') >= 0 && text.indexOf('120 L') >= 0 && text.indexOf('80 L') >= 0,
                quotaInput: !!document.getElementById('tw-quota-limit'),
                bars: bars.length,
                oldRequirements: text.indexOf('Startup requirements') >= 0
              };
            })();
            """
        )
        if (not overview or not overview.get("waiting") or not overview.get("title")
                or not overview.get("totals") or not overview.get("quotaInput") or overview.get("bars") != 3
                or overview.get("oldRequirements")):
            failures.append(f"Overview waiting screen incomplete: {overview}")
        window.evaluate_js("window.topupToggleNav()")
        time.sleep(0.5)
        collapsed = window.evaluate_js(
            """
            (function () {
              var toggle=document.querySelector('.tw-toggle');
              var first=document.querySelector('.tw-nav button');
              var side=document.querySelector('.tw-side');
              if (!toggle || !first || !side) return null;
              var t=toggle.getBoundingClientRect(), f=first.getBoundingClientRect();
              return {
                width: Math.round(side.getBoundingClientRect().width),
                gap: Math.round(f.top - t.bottom),
                overlap: t.bottom > f.top
              };
            })();
            """
        )
        if (not collapsed or collapsed.get("width") != 44 or collapsed.get("overlap")
                or collapsed.get("gap", 0) < 8):
            failures.append(f"Collapsed sidebar controls overlap: {collapsed}")
        before_theme = window.evaluate_js(
            """
            (function () {
              return {
                theme: document.documentElement.getAttribute('data-perso-theme'),
                background: getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim()
              };
            })();
            """
        )
        window.evaluate_js("window.topupTheme()")
        time.sleep(0.3)
        after_theme = window.evaluate_js(
            """
            (function () {
              var button=document.querySelector('.tw-theme');
              return {
                theme: document.documentElement.getAttribute('data-perso-theme'),
                background: getComputedStyle(document.documentElement).getPropertyValue('--color-bg').trim(),
                saved: window.localStorage.getItem('smartdispenser-perso-theme'),
                icon: button && button.querySelector('i') ? button.querySelector('i').className : ''
              };
            })();
            """
        )
        expected = "light" if before_theme and before_theme.get("theme") == "dark" else "dark"
        expected_icon = "ph-sun" if expected == "light" else "ph-moon"
        if (not after_theme or after_theme.get("theme") != expected
                or after_theme.get("saved") != expected
                or after_theme.get("background") == before_theme.get("background")
                or expected_icon not in after_theme.get("icon", "")):
            failures.append(f"Topup theme did not change: before={before_theme}, after={after_theme}")
    except Exception as error:
        failures.append(str(error))
    finally:
        window.destroy()


webview.start(verify, debug=False)
if failures:
    raise RuntimeError("; ".join(failures))
print("OK: Topup workspace rendered in the Perso WebView shell")
