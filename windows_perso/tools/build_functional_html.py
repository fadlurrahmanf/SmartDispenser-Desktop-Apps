from __future__ import annotations

import json
import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "mock" / "SmartDispenser Console (standalone).html"
DESTINATION = PROJECT / "mock" / "SmartDispenser Console (functional).html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


raw = SOURCE.read_text(encoding="utf-8")
match = re.search(r'<script type="__bundler/template">\s*([\s\S]*?)\s*</script>', raw)
if not match:
    raise RuntimeError("Bundled template was not found")
template = json.loads(match.group(1))

outer_old = '<div style="font-family: var(--font-body); color: var(--color-text); padding: 18px; display: flex; flex-direction: column; gap: 13px;">'
outer_new = '<div style="font-family: var(--font-body); color: var(--color-text); padding: 0; width: 100vw; height: 100vh; min-height: 0; overflow: hidden; display: flex; flex-direction: column; gap: 0;">'
template = replace_once(template, outer_old, outer_new, "outer application container")
controls_start = template.index(outer_new) + len(outer_new)
application_start = template.index('<div ref="{{ holderRef }}"', controls_start)
template = template[:controls_start] + "\n\n  " + template[application_start:]
template = replace_once(
    template,
    '<div ref="{{ holderRef }}" style="width: 100%; overflow: hidden;">',
    '<div ref="{{ holderRef }}" style="width: 100%; height: 100%; min-height: 0; overflow: hidden;">',
    "responsive application holder",
)

# The standalone mock draws its own decorative Windows title bar.  The
# functional build already runs inside a native pywebview window, so keeping
# both bars duplicates the title and window controls.
fake_titlebar_pattern = re.compile(
    r'\n\s*<div style="height: 34px; flex: none; display: flex; align-items: center; gap: 10px; '
    r'padding-left: 14px; background: #1b1d2c; border-bottom: 1px solid var\(--color-neutral-900\);">'
    r'.*?</div>\s*(?=<sc-if value="\{\{ isSplash \}\}")',
    re.DOTALL,
)
template, removed_titlebars = fake_titlebar_pattern.subn("\n\n      ", template, count=1)
if removed_titlebars != 1:
    raise RuntimeError(f"mock title bar: expected one match, found {removed_titlebars}")

template = replace_once(
    template,
    'state = { screen: "splash", si: 0, size: 0, w: 1100, dialog: null, navOpen: true };',
    'state = { screen: "splash", si: 0, size: 0, w: 1100, h: 768, dialog: null, navOpen: true, backend: null, activityLogMinimized: true, theme: document.documentElement.getAttribute("data-perso-theme") === "light" ? "light" : "dark" };',
    "component state",
)
template = replace_once(
    template,
    'this.ro = new ResizeObserver(function () { self.setState({ w: el.clientWidth }); });',
    'this.ro = new ResizeObserver(function () { self.setState({ w: el.clientWidth, h: el.clientHeight }); });',
    "responsive resize observer",
)
template = replace_once(
    template,
    '    this.setState({ w: el.clientWidth });\n  }',
    '''    this.setState({ w: el.clientWidth, h: el.clientHeight });
    this.applyTheme(this.state.theme);
    window.__persoApplyBackend = function (data) { self.applyBackend(data); };
    this.startBackendBridge();
  }

  applyTheme(theme) {
    var root = document.documentElement;
    var dark = {
      "--color-bg":"#161826", "--color-surface":"#232532", "--color-text":"#e9e9ed",
      "--color-divider":"color-mix(in srgb, #e9e9ed 16%, transparent)",
      "--color-neutral-100":"#f3f5fe", "--color-neutral-200":"#e4e7f5", "--color-neutral-300":"#cfd3e5",
      "--color-neutral-400":"#b2b6ca", "--color-neutral-500":"#9397ab", "--color-neutral-600":"#75798c",
      "--color-neutral-700":"#595d6c", "--color-neutral-800":"#3f424d", "--color-neutral-900":"#292b31",
      "--color-accent":"#9184d9", "--color-accent-100":"#f5f4ff", "--color-accent-200":"#e7e5fe",
      "--color-accent-300":"#d2cefd", "--color-accent-400":"#b5abfc", "--color-accent-500":"#968ae0",
      "--color-accent-600":"#796cbf", "--color-accent-700":"#5d5294", "--color-accent-800":"#423a6a", "--color-accent-900":"#2b2741",
      "--color-accent-2-100":"#f5f4ff", "--color-accent-2-200":"#e7e5fe", "--color-accent-2-300":"#d2cefd",
      "--color-accent-2-400":"#b5afe8", "--color-accent-2-500":"#9690c9", "--color-accent-2-600":"#7972a9",
      "--color-accent-2-700":"#5c5783", "--color-accent-2-800":"#423e5d", "--color-accent-2-900":"#2b293a",
      "--color-chrome":"#1b1d2c", "--color-hero-glow":"#1e2133",
      "--color-success":"oklch(0.76 0.13 152)", "--color-warning":"oklch(0.80 0.14 86)", "--color-danger":"oklch(0.70 0.16 25)",
      "--shadow-sm":"0 0 0 1px #3f424d", "--shadow-md":"0 0 0 1px #595d6c, 0 6px 18px rgba(0,0,0,0.55)",
      "--shadow-lg":"0 0 0 1px #9397ab, 0 16px 40px rgba(0,0,0,0.65)"
    };
    var light = {
      "--color-bg":"#f4f6fb", "--color-surface":"#ffffff", "--color-text":"#202432", "--color-divider":"rgba(40,46,66,.18)",
      "--color-neutral-100":"#202432", "--color-neutral-200":"#303647", "--color-neutral-300":"#434b60",
      "--color-neutral-400":"#5b657a", "--color-neutral-500":"#737d91", "--color-neutral-600":"#8d96a8",
      "--color-neutral-700":"#aeb5c3", "--color-neutral-800":"#d1d6e0", "--color-neutral-900":"#e4e8ef",
      "--color-accent":"#6757bd", "--color-accent-100":"#332c60", "--color-accent-200":"#4b3f88",
      "--color-accent-300":"#5e50a9", "--color-accent-400":"#6757bd", "--color-accent-500":"#7869c8",
      "--color-accent-600":"#9b90d9", "--color-accent-700":"#bbb4e7", "--color-accent-800":"#d9d5f2", "--color-accent-900":"#ebe9f8",
      "--color-accent-2-100":"#312d51", "--color-accent-2-200":"#484273", "--color-accent-2-300":"#5d568f",
      "--color-accent-2-400":"#716aaa", "--color-accent-2-500":"#8b84bc", "--color-accent-2-600":"#aaa4cf",
      "--color-accent-2-700":"#c2bee0", "--color-accent-2-800":"#dcd9ed", "--color-accent-2-900":"#eeecf7",
      "--color-chrome":"#e9ecf3", "--color-hero-glow":"#e4e6f5",
      "--color-success":"#168653", "--color-warning":"#9a6500", "--color-danger":"#bd3b43",
      "--shadow-sm":"0 0 0 1px rgba(40,46,66,.16)", "--shadow-md":"0 0 0 1px rgba(40,46,66,.13), 0 6px 18px rgba(40,46,66,.12)",
      "--shadow-lg":"0 0 0 1px rgba(40,46,66,.12), 0 16px 40px rgba(40,46,66,.16)"
    };
    var palette = theme === "light" ? light : dark;
    Object.keys(palette).forEach(function (name) { root.style.setProperty(name, palette[name]); });
    root.setAttribute("data-perso-theme", theme);
    root.style.colorScheme = theme;
    document.body.style.background = theme === "light" ? "#eef1f7" : "#0f1018";
    try { window.localStorage.setItem("smartdispenser-perso-theme", theme); } catch (error) {}
  }

  toggleTheme() {
    var self = this;
    var nextTheme = this.state.theme === "dark" ? "light" : "dark";
    this.setState({ theme: nextTheme }, function () { self.applyTheme(nextTheme); });
  }

  startBackendBridge() {
    var self = this;
    this.refreshBackend();
    this.backendTimer = setInterval(function () { self.refreshBackend(); }, 300);
  }

  async refreshBackend() {
    if (!window.pywebview || !window.pywebview.api) return;
    var active = document.activeElement;
    while (active && active.shadowRoot && active.shadowRoot.activeElement) active = active.shadowRoot.activeElement;
    if ((active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA")) || Date.now() < (window.__persoCustomerEditingUntil || 0)) return;
    try {
      var data = await window.pywebview.api.get_state();
      this.applyBackend(data);
    } catch (error) { console.error("Perso bridge state failed", error); }
  }

  applyBackend(data) {
    if (!data) return;
    var self = this;
    var definition = SCREENS.filter(function (item) { return item.key === data.screen; })[0] || SCREENS[0];
    var index = Math.max(0, definition.states.indexOf(data.state));
    if (definition.key === "customers" && data.view && data.view.fields) {
      data.view.fields = data.view.fields.map(function (field) {
        return Object.assign({}, field, { isStatus: field.key === "status", isText: field.key !== "status" });
      });
    }
    this.setState({ screen: definition.key, si: index, backend: data }, function () {
      if (definition.key === "customers" && data.view) {
        if (data.view.fields) self.syncCustomerInputs(data.view.fields);
        self.syncCustomerSearch(data.view.search);
      }
    });
  }

  syncCustomerInputs(fields) {
    setTimeout(function () {
      fields.forEach(function (field) {
        var input = document.querySelector('[data-customer-field="' + field.key + '"]');
        if (!input || input === document.activeElement) return;
        input.value = field.value == null ? "" : String(field.value);
        if (input.tagName === "SELECT") input.disabled = !!field.readonly;
        else input.readOnly = !!field.readonly;
      });
    }, 0);
  }

  syncCustomerSearch(value) {
    setTimeout(function () {
      var input = document.querySelector("input[data-customer-search]");
      if (!input || input === document.activeElement) return;
      input.value = value == null ? "" : String(value);
    }, 0);
  }

  async bridgeAction(name, payload) {
    if (!window.pywebview || !window.pywebview.api) return;
    try {
      var data = await window.pywebview.api.action(name, payload || {});
      this.applyBackend(data);
    } catch (error) { console.error("Perso bridge action failed", error); }
  }

  collectCustomerFields() {
    var values = {};
    document.querySelectorAll("[data-customer-field]").forEach(function (input) {
      values[input.getAttribute("data-customer-field")] = input.value;
    });
    return values;
  }''',
    "backend lifecycle",
)
template = template.replace(
    '  componentWillUnmount() { if (this.ro) this.ro.disconnect(); }',
    '  componentWillUnmount() { if (this.ro) this.ro.disconnect(); if (this.backendTimer) clearInterval(this.backendTimer); window.__persoApplyBackend = null; }',
)
template = replace_once(
    template,
    '  pickScreen(key) { this.setState({ screen: key, si: 0, dialog: null }); }',
    '  pickScreen(key) { this.setState({ screen: key, si: 0, dialog: null }); this.bridgeAction("show_page", { page: key }); }',
    "navigation bridge",
)

render_anchor = '''    var s = screen === "splash" ? this.splashState(stateName)
      : screen === "gate" ? this.gateState(stateName)
      : screen === "test" ? this.testState(stateName)
      : screen === "owner" ? this.ownerState(stateName)
      : screen === "customers" ? this.customersState(stateName)
      : screen === "perso" ? this.persoState(stateName, SIZES[this.state.size].h < 900)
      : this.logsState(stateName);
'''
render_overlay = render_anchor + '''
    var backend = this.state.backend;
    if (backend && backend.view) {
      var live = backend.view;
      s = Object.assign({}, s, live);
      if (screen === "customers" && live.rows) {
        s.rows = live.rows.map(function (row) {
          return Object.assign({}, row, { pick: function () { self.bridgeAction("customer_select", { id: row.id }); } });
        });
        s.gridStyle = "height:100%;display:grid;grid-template-columns:minmax(0,1fr) " + (s.showDetails ? "336px" : "46px") + ";gap:" + (s.showDetails ? "20px" : "10px") + ";transition:grid-template-columns .26s ease;";
        s.panelStyle = "display:flex;flex-direction:column;gap:9px;min-height:0;overflow:hidden;animation:slideIn .26s ease;";
      }
      if (screen === "perso") {
        s.precheck = steps(PRECHECK, live.precheckDone || 0, -1, -1, [], "", SIZES[this.state.size].h < 900);
        s.writeSteps = steps(WRITE, live.writeDone || 0, -1, -1, [], "", SIZES[this.state.size].h < 900);
        if (s.metrics && s.metrics.length === 3) {
          s.metrics[0].value = live.cardSummary || s.metrics[0].value;
          s.metrics[1].value = live.walletSummary || s.metrics[1].value;
          s.metrics[2].value = live.protectionSummary || s.metrics[2].value;
        }
      }
    }
'''
template = replace_once(template, render_anchor, render_overlay, "live state overlay")
responsive_tight_count = template.count('SIZES[this.state.size].h < 900')
if responsive_tight_count != 3:
    raise RuntimeError(f"responsive compact layout: expected three matches, found {responsive_tight_count}")
template = template.replace(
    'SIZES[this.state.size].h < 900',
    '(this.state.h || SIZES[this.state.size].h) < 900',
)

template = replace_once(
    template,
    'stageStyle: "width:" + size.w + "px;height:" + size.h + "px;transform:scale(" + scale + ");transform-origin:top left;margin-bottom:" + (size.h * (scale - 1)) + "px;",\n      sizeLabel: size.label,',
    'stageStyle: "width:100%;height:100%;",\n      sizeLabel: (this.state.w || size.w) + " × " + (this.state.h || size.h),',
    "responsive stage",
)
template = replace_once(
    template,
    '<div style="flex: 1; min-height: 0; display: flex;">\n            <div style="{{ sidebarStyle }}">',
    '<div style="flex:1;min-height:0;display:flex;position:relative;">\n            <button type="button" aria-label="Toggle sidebar" title="Toggle sidebar" sc-camel-on-click="{{ toggleNav }}" style="{{ navToggleStyle }}"><i class="{{ navToggleIcon }}" style="font-size:14px;"></i></button>\n            <div style="{{ sidebarStyle }}">',
    "working sidebar toggle",
)
template = replace_once(
    template,
    '<div style="width: 100%; height: 100%; display: flex; flex-direction: column; background: var(--color-bg); border-radius: 10px; box-shadow: var(--shadow-lg); overflow: hidden; position: relative;">',
    '<div style="width:100%;height:100%;display:flex;flex-direction:column;background:var(--color-bg);border-radius:0;box-shadow:none;overflow:hidden;position:relative;">\n        <button type="button" data-theme-toggle="true" aria-label="{{ themeLabel }}" title="{{ themeLabel }}" sc-camel-on-click="{{ toggleTheme }}" style="position:absolute;z-index:50;top:14px;left:8px;width:26px;height:24px;display:grid;place-items:center;border:1px solid var(--color-neutral-800);border-radius:var(--radius-sm);background:var(--color-chrome);color:var(--color-neutral-300);cursor:pointer;"><i class="{{ themeIcon }}" style="font-size:14px;"></i></button>',
    "persistent theme toggle",
)
template = replace_once(
    template,
    '\n                <span style="margin-left: auto; font-variant-numeric: tabular-nums;">{{ sizeLabel }}</span>',
    '',
    "remove fixed window size label",
)
template = replace_once(
    template,
    'navToggleStyle: "width:26px;height:22px;display:grid;place-items:center;margin-right:2px;border:1px solid var(--color-neutral-800);border-radius:var(--radius-sm);background:transparent;color:var(--color-neutral-400);cursor:pointer;",',
    'navToggleStyle: "position:absolute;z-index:20;top:" + (this.state.navOpen ? "14px" : "48px") + ";left:" + (this.state.navOpen ? "180px" : "8px") + ";width:26px;height:24px;display:grid;place-items:center;border:1px solid var(--color-neutral-800);border-radius:var(--radius-sm);background:var(--color-chrome);color:var(--color-neutral-300);cursor:pointer;transition:left .26s cubic-bezier(.4,0,.2,1),top .26s cubic-bezier(.4,0,.2,1);",',
    "sliding sidebar toggle style",
)
template = replace_once(
    template,
    'sidebarStyle: "width:" + (this.state.navOpen ? 214 : 0) + "px;flex:none;display:flex;flex-direction:column;overflow:hidden;white-space:nowrap;background:#1b1d2c;border-right:1px solid " + (this.state.navOpen ? "var(--color-neutral-900)" : "transparent") + ";transition:width .26s cubic-bezier(.4,0,.2,1);",',
    'sidebarStyle: "width:" + (this.state.navOpen ? 214 : 44) + "px;flex:none;display:flex;flex-direction:column;overflow:hidden;white-space:nowrap;background:var(--color-chrome);border-right:1px solid var(--color-neutral-900);transition:width .26s cubic-bezier(.4,0,.2,1),background .2s ease;",',
    "collapsed sidebar rail",
)
template = replace_once(
    template,
    'navToggleIcon: this.state.navOpen ? "ph ph-sidebar-simple" : "ph ph-list",',
    'navToggleIcon: this.state.navOpen ? "ph ph-sidebar-simple" : "ph ph-list",\n      themeIcon: this.state.theme === "dark" ? "ph ph-moon" : "ph ph-sun",\n      themeLabel: this.state.theme === "dark" ? "Dark mode" : "Light mode",\n      toggleTheme: function () { self.toggleTheme(); },\n      navTextDisplay: this.state.navOpen ? "inline" : "none",\n      sidebarBrandStyle: "height:" + (this.state.navOpen ? "52px" : "88px") + ";flex:none;padding:" + (this.state.navOpen ? "15px 48px 13px 44px" : "0") + ";display:flex;align-items:center;gap:9px;visibility:" + (this.state.navOpen ? "visible" : "hidden") + ";transition:height .26s cubic-bezier(.4,0,.2,1);",\n      sidebarTextStyle: "display:" + (this.state.navOpen ? "flex" : "none") + ";flex-direction:column;",\n      sidebarMenuStyle: "display:" + (this.state.navOpen ? "block" : "none") + ";padding:14px 16px 8px;font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--color-neutral-600);",\n      sidebarFooterStyle: "margin-top:auto;padding:" + (this.state.navOpen ? "14px 16px" : "14px 0") + ";display:flex;flex-direction:column;align-items:" + (this.state.navOpen ? "stretch" : "center") + ";gap:9px;border-top:1px solid var(--color-neutral-900);",',
    "collapsed sidebar visibility values",
)
template = replace_once(
    template,
    '<div style="padding: 15px 16px 13px; display: flex; align-items: center; gap: 9px;">',
    '<div style="{{ sidebarBrandStyle }}">',
    "responsive sidebar brand",
)
template = replace_once(
    template,
    '<div style="display: flex; flex-direction: column;">\n                  <span style="font-size: 12px; font-weight: 500;">SmartDispenser</span>',
    '<div style="{{ sidebarTextStyle }}">\n                  <span style="font-size: 12px; font-weight: 500;">SmartDispenser</span>',
    "responsive sidebar brand text",
)
template = replace_once(
    template,
    '<div style="padding: 14px 16px 8px; font-size: 9px; letter-spacing: .16em; text-transform: uppercase; color: var(--color-neutral-600);">Menu</div>',
    '<div style="{{ sidebarMenuStyle }}">Menu</div>',
    "responsive sidebar menu heading",
)
template = replace_once(
    template,
    '<button type="button" sc-camel-on-click="{{ n.pick }}" style="{{ n.style }}"><i class="{{ n.icon }}" style="font-size: 16px; flex: none;"></i><span>{{ n.label }}</span><i class="{{ n.trail }}" style="font-size: 12px; margin-left: auto; opacity: .6;"></i></button>',
    '<button type="button" title="{{ n.label }}" aria-label="{{ n.label }}" sc-camel-on-click="{{ n.pick }}" style="{{ n.style }}"><i class="{{ n.icon }}" style="font-size:16px;flex:none;"></i><span style="display:{{ navTextDisplay }};">{{ n.label }}</span><i class="{{ n.trail }}" style="display:{{ navTextDisplay }};font-size:12px;margin-left:auto;opacity:.6;"></i></button>',
    "icon-only collapsed navigation",
)
template = replace_once(
    template,
    '<div style="margin-top: auto; padding: 14px 16px; display: flex; flex-direction: column; gap: 9px; border-top: 1px solid var(--color-neutral-900);">',
    '<div style="{{ sidebarFooterStyle }}">',
    "responsive sidebar footer",
)
template = replace_once(
    template,
    '<span style="font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: {{ boardColor }};">{{ boardLabel }}</span>',
    '<span style="display:{{ navTextDisplay }};font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:{{ boardColor }};">{{ boardLabel }}</span>',
    "collapsed Board label",
)
template = replace_once(
    template,
    '<span style="font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: {{ sessionColor }};">{{ sessionLabel }}</span>',
    '<span style="display:{{ navTextDisplay }};font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:{{ sessionColor }};">{{ sessionLabel }}</span>',
    "collapsed session label",
)
template = replace_once(
    template,
    'style: "display:flex;align-items:center;gap:10px;width:100%;padding:8px 10px;border:0;border-radius:var(--radius-md);font:inherit;font-size:12px;text-align:left;cursor:pointer;background:" + (active ? "var(--color-accent-900)" : "transparent") + ";color:" + (active ? "var(--color-accent-100)" : "var(--color-neutral-400)") + ";",',
    'style: "display:flex;align-items:center;justify-content:" + (self.state.navOpen ? "flex-start" : "center") + ";gap:10px;width:100%;padding:" + (self.state.navOpen ? "8px 10px" : "8px 0") + ";border:0;border-radius:var(--radius-md);font:inherit;font-size:12px;text-align:left;cursor:pointer;background:" + (active ? "var(--color-accent-900)" : "transparent") + ";color:" + (active ? "var(--color-accent-100)" : "var(--color-neutral-400)") + ";",',
    "center collapsed navigation icons",
)
template = replace_once(
    template,
    '<div style="flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 236px; gap: 13px;">',
    '<div style="flex:none;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) 236px;gap:13px;align-items:start;">',
    "compact personalization process panels",
)
template = replace_once(
    template,
    '"Operator confirmation accepted"',
    '"Database reservation confirmed"',
    "Database-first personalization step",
)
template = replace_once(
    template,
    'Waiting for any card — master card is allowed.',
    'Waiting for any card.',
    "neutral Test Card waiting message",
)

# The prototype's process checklist typography is too small at a maximized
# desktop resolution. Increase only these two panels so the rest of the mockup
# keeps its intended visual hierarchy and the panels remain compact.
process_headers = {
    '<span style="font-size: 9px; letter-spacing: .14em; text-transform: uppercase; color: var(--color-accent-400);">Card precheck — read only</span>':
        '<span style="font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--color-accent-400);">Card precheck — read only</span>',
    '<span style="font-size: 9px; letter-spacing: .14em; text-transform: uppercase; color: {{ s.writeKicker }};">Personalization — writes card</span>':
        '<span style="font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: {{ s.writeKicker }};">Personalization — writes card</span>',
    '<span style="margin-left: auto; font-size: 10px; color: var(--color-neutral-600); font-variant-numeric: tabular-nums;">{{ s.precheckCount }}</span>':
        '<span style="margin-left: auto; font-size: 12px; color: var(--color-neutral-600); font-variant-numeric: tabular-nums;">{{ s.precheckCount }}</span>',
    '<span style="margin-left: auto; font-size: 10px; color: var(--color-neutral-600); font-variant-numeric: tabular-nums;">{{ s.writeCount }}</span>':
        '<span style="margin-left: auto; font-size: 12px; color: var(--color-neutral-600); font-variant-numeric: tabular-nums;">{{ s.writeCount }}</span>',
}
for old, new in process_headers.items():
    template = replace_once(template, old, new, "larger process panel header")

process_list = '<div style="flex: 1; min-height: 0; display: flex; flex-direction: column; gap: {{ s.stepGap }};">'
if template.count(process_list) != 2:
    raise RuntimeError(f"process checklist typography: expected two matches, found {template.count(process_list)}")
template = template.replace(
    process_list,
    '<div style="flex:1;min-height:0;display:flex;flex-direction:column;gap:{{ s.stepGap }};font-size:13px;line-height:1.45;">',
    2,
)

process_number = '<span style="width: 13px; flex: none; color: var(--color-neutral-700); font-variant-numeric: tabular-nums;">{{ p.n }}</span>'
if template.count(process_number) != 2:
    raise RuntimeError(f"process step number typography: expected two matches, found {template.count(process_number)}")
template = template.replace(
    process_number,
    '<span style="width:18px;flex:none;font-size:12px;color:var(--color-neutral-700);font-variant-numeric:tabular-nums;">{{ p.n }}</span>',
    2,
)

return_anchor = '''      closeDialog: function () { self.setState({ dialog: "none" }); },
    };'''
return_actions = '''      closeDialog: function () { self.setState({ dialog: "none" }); },
      testAction: function () { self.bridgeAction("test_start"); },
      testStop: function () { self.bridgeAction("test_stop"); },
      ownerAction: function () { self.bridgeAction("owner_start"); },
      customerClearSearch: function () { self.bridgeAction("customer_clear_search"); },
      customerNew: function () { self.bridgeAction("customer_new"); },
      customerDeselect: function () { self.bridgeAction("customer_deselect"); },
      customerSave: function () { self.bridgeAction("customer_save", { fields: self.collectCustomerFields() }); },
      customerUpdate: function () { self.bridgeAction("customer_update", { fields: self.collectCustomerFields() }); },
      personalizeCustomer: function () { self.bridgeAction("personalize_customer"); },
      clearSerialView: function () { self.bridgeAction("serial_clear_view"); },
      toggleActivityLog: function () { self.setState({ activityLogMinimized: !self.state.activityLogMinimized }); },
      activityLogDisplay: self.state.activityLogMinimized ? "none" : "block",
      activityLogToggleLabel: self.state.activityLogMinimized ? "Expand" : "Minimize",
      activityLogToggleIcon: self.state.activityLogMinimized ? "ph ph-caret-down" : "ph ph-caret-up",
      removePersoClick: function () { self.setState({ dialog: "remove_perso" }); },
      logsToggle: function () { self.bridgeAction("logs_toggle"); },
      dialogYesClick: function () {
        if (self.state.dialog === "confirm") self.bridgeAction("personalize_commit");
        if (self.state.dialog === "clear") self.bridgeAction("logs_clear");
        if (self.state.dialog === "remove_perso") self.bridgeAction("perso_remove");
        self.setState({ dialog: "none" });
      },
    };'''
template = replace_once(template, return_anchor, return_actions, "live action bindings")

template = replace_once(
    template,
    '    if (this.state.dialog === "clear") {\n      s = Object.assign({}, s, { showDialog: true, dialogIcon: "ph ph-trash", dialogColor: BAD, dialogTitle: "Clear logs", dialogBody: "Delete every Activity Log entry from this view and the Database? This action cannot be undone.", dialogNo: "Cancel", dialogYes: "Delete all logs" });\n    }',
    '    if (this.state.dialog === "clear") {\n      s = Object.assign({}, s, { showDialog: true, dialogIcon: "ph ph-trash", dialogColor: BAD, dialogTitle: "Clear logs", dialogBody: "Delete every Activity Log entry from this view and the Database? This action cannot be undone.", dialogNo: "Cancel", dialogYes: "Delete all logs" });\n    }\n    if (this.state.dialog === "remove_perso") {\n      s = Object.assign({}, s, { showDialog: true, dialogIcon: "ph ph-warning", dialogColor: BAD, dialogTitle: "Remove personalization", dialogBody: "Remove Card Identity and close its active Database ownership? Wallet Data will be preserved. Keep the card on the NFC Reader until verification finishes.", dialogNo: "Cancel", dialogYes: "Remove personalization" });\n    }',
    "remove personalization confirmation",
)

template = replace_once(
    template,
    '<sc-if value="{{ isTest }}" hint-placeholder-val="{{ false }}">\n                  <div style="height: 100%; display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 18px;">',
    '<sc-if value="{{ isTest }}" hint-placeholder-val="{{ false }}">\n                  <div style="height: 100%; display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px;">',
    "Test Card single-column layout",
)
template = replace_once(
    template,
    '<div style="display: flex; flex-direction: column; gap: 14px; min-height: 0;">\n                      <div class="card" style="padding: 17px;">\n                        <div class="card-kicker">Scope of this test</div>',
    '<div style="display: none;">\n                      <div class="card" style="padding: 17px;">\n                        <div class="card-kicker">Scope of this test</div>',
    "hide Test Card supplementary panels",
)
template = replace_once(
    template,
    '<div class="card" style="display: flex; flex-direction: column; justify-content: center; gap: 20px; padding: 30px;">',
    '<div class="card" style="display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;gap:20px;padding:30px;">',
    "center Test Card content",
)
template = replace_once(
    template,
    '<div style="display: flex; align-items: center; gap: 15px;">',
    '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:15px;">',
    "center Test Card result",
)
template = replace_once(
    template,
    '"Card detected": { result: "Card detected — NFC reader is working.", sub: "3 card detections", lampColor: OK, heroIcon: "ph-fill ph-check-circle",',
    '"Card detected": { result: "Card detected — NFC reader is working.", sub: "3 card detections", lampColor: OK, heroIcon: "ph-fill ph-check-circle", heroAnim: "animation:breathe 1.1s ease-in-out infinite;",',
    "animate detected Test Card",
)
template = replace_once(
    template,
    '"Card removed": { result: "Card removed — waiting for another card.", sub: "3 card detections", lampColor: WARN, heroIcon: "ph ph-hand-tap",',
    '"Card removed": { result: "Card removed — waiting for another card.", sub: "3 card detections", lampColor: WARN, heroIcon: "ph ph-hand-tap", heroAnim: "animation:breathe 1.1s ease-in-out infinite;",',
    "animate removed Test Card",
)
template = replace_once(
    template,
    '<sc-if value="{{ isOwner }}" hint-placeholder-val="{{ false }}">\n                  <div style="height: 100%; display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 18px;">',
    '<sc-if value="{{ isOwner }}" hint-placeholder-val="{{ false }}">\n                  <div style="height: 100%; display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px;">',
    "Identify Card Owner single-column layout",
)
template = replace_once(
    template,
    '<div style="display: flex; flex-direction: column; gap: 14px; min-height: 0;">\n                      <div class="card" style="padding: 17px;">\n                        <div class="card-kicker">What the reader returns</div>',
    '<div style="display: none;">\n                      <div class="card" style="padding: 17px;">\n                        <div class="card-kicker">What the reader returns</div>',
    "hide Identify Card Owner supplementary panels",
)

template = replace_once(
    template,
    '''<div style="display: flex; align-items: center; gap: 10px;">
                        <button type="button" class="btn btn-primary" style="gap: 8px;"><i class="{{ s.actionIcon }}" style="font-size: 15px;"></i>{{ s.action }}</button>
                        <sc-if value="{{ s.showStop }}" hint-placeholder-val="{{ false }}">
                          <button type="button" class="btn btn-secondary">Stop test</button>
                        </sc-if>
                      </div>''',
    '',
    "remove automatic Test Card controls",
)
template = replace_once(
    template,
    '''<div style="display: flex; flex-direction: column; gap: 6px; padding: 15px 16px; border-radius: var(--radius-md); background: var(--color-accent-900); border: 1px solid var(--color-accent-800);">
                        <div style="font-size: 9px; letter-spacing: .16em; text-transform: uppercase; color: var(--color-accent-400);">Card number</div>
                        <div style="font-size: 26px; font-weight: 500; letter-spacing: .04em; font-variant-numeric: tabular-nums; color: {{ s.refColor }};">{{ s.reference }}</div>
                      </div>
                      <div style="display: flex; flex-direction: column; gap: 8px;">
                        <div style="font-size: 9px; letter-spacing: .16em; text-transform: uppercase; color: var(--color-neutral-600);">Registered owner</div>
                        <div style="font-size: 18px; font-weight: 500; color: {{ s.ownerColor }};">{{ s.owner }}</div>
                        <div style="font-size: 12px; line-height: 1.65; color: var(--color-neutral-500); font-variant-numeric: tabular-nums; text-wrap: pretty;">{{ s.details }}</div>
                      </div>''',
    '''<div style="overflow:hidden;border:1px solid var(--color-neutral-900);border-radius:var(--radius-md);">
                        <sc-raw-table class="table" style="width:100%;table-layout:fixed;font-size:13px;font-variant-numeric:tabular-nums;">
                          <sc-raw-tbody>
                            <sc-for list="{{ s.ownerRows }}" as="r" hint-placeholder-count="7">
                              <sc-raw-tr><sc-raw-th style="width:190px;white-space:nowrap;color:var(--color-neutral-500);">{{ r.label }}</sc-raw-th><sc-raw-td style="color:var(--color-neutral-200);word-break:break-word;">{{ r.value }}</sc-raw-td></sc-raw-tr>
                            </sc-for>
                          </sc-raw-tbody>
                        </sc-raw-table>
                      </div>''',
    "owner lookup result table",
)
template = replace_once(
    template,
    '''<div style="margin-top: auto; display: flex; align-items: center; gap: 10px;">
                        <button type="button" class="btn btn-primary" style="gap: 8px;"><i class="{{ s.actionIcon }}" style="font-size: 15px;"></i>{{ s.action }}</button>
                        <span class="tag tag-outline">Read only</span>
                      </div>''',
    '<div style="margin-top:auto;display:flex;justify-content:center;"><span class="tag tag-outline">Read only · Auto active</span></div>',
    "remove automatic owner lookup control",
)

template = replace_once(
    template,
    '<button type="button" class="btn btn-ghost" style="margin-left: auto; padding: 2px 9px; font-size: 11px;">Clear view</button>',
    '<button type="button" class="btn btn-ghost" sc-camel-on-click="{{ clearSerialView }}" style="margin-left: auto; padding: 2px 9px; font-size: 11px;">Clear view</button>',
    "clear parsed serial view",
)
template = replace_once(
    template,
    '<div style="flex: none;">\n                      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n                        <span style="font-size: 9px; letter-spacing: .14em; text-transform: uppercase; color: var(--color-accent-400);">Board activity log</span>',
    '<div style="flex:none;min-width:0;overflow:hidden;">\n                      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">\n                        <span style="font-size: 9px; letter-spacing: .14em; text-transform: uppercase; color: var(--color-accent-400);">Board activity log</span>',
    "bounded Board activity log container",
)
template = replace_once(
    template,
    '<button type="button" class="btn btn-ghost" sc-camel-on-click="{{ clearSerialView }}" style="margin-left: auto; padding: 2px 9px; font-size: 11px;">Clear view</button>\n                      </div>\n                      <div style="border: 1px solid var(--color-neutral-900); border-radius: var(--radius-md); overflow: hidden;">\n                        <sc-raw-table class="table" style="width: 100%; font-size: 11px; font-variant-numeric: tabular-nums;">',
    '<button type="button" class="btn btn-ghost" sc-camel-on-click="{{ toggleActivityLog }}" style="margin-left:auto;padding:2px 9px;font-size:11px;gap:5px;"><i class="{{ activityLogToggleIcon }}" style="font-size:12px;"></i>{{ activityLogToggleLabel }}</button><button type="button" class="btn btn-ghost" sc-camel-on-click="{{ clearSerialView }}" style="padding:2px 9px;font-size:11px;">Clear view</button>\n                      </div>\n                      <div style="display:{{ activityLogDisplay }};border:1px solid var(--color-neutral-900);border-radius:var(--radius-md);height:min(210px,22vh);min-height:120px;overflow:auto;">\n                        <sc-raw-table class="table" style="width:100%;table-layout:fixed;font-size:11px;font-variant-numeric:tabular-nums;">',
    "minimizable Board activity log table",
)

template = replace_once(
    template,
    '<button type="button" class="btn btn-secondary btn-block" style="justify-content: center;">Cancel</button>',
    '<sc-if value="{{ s.showRemovePerso }}" hint-placeholder-val="{{ false }}"><button type="button" class="btn btn-secondary btn-block" disabled="{{ s.removePersoDisabled }}" sc-camel-on-click="{{ removePersoClick }}" style="justify-content:center;color:oklch(0.72 0.16 25);border-color:color-mix(in srgb,oklch(0.72 0.16 25) 55%,transparent);"><i class="ph ph-eraser" style="font-size:15px;"></i>Remove personalization</button></sc-if><button type="button" class="btn btn-secondary btn-block" style="justify-content: center;">Cancel</button>',
    "remove personalization action",
)

template = replace_once(template, '<input class="input" type="text" value="{{ s.search }}" placeholder="Search customer number, name, or NIK"', '<input class="input" data-customer-search="true" type="text" sc-camel-default-value="{{ s.search }}" placeholder="Search customer number, name, NIK, KK, phone, or address"', "customer search")
template = replace_once(template, '<button type="button" class="btn btn-secondary btn-icon"><i class="ph ph-x"', '<button type="button" class="btn btn-secondary btn-icon" sc-camel-on-click="{{ customerClearSearch }}"><i class="ph ph-x"', "clear customer search")
template = replace_once(template, '<button type="button" class="btn btn-secondary" style="gap: 7px;"><i class="ph ph-plus"', '<button type="button" class="btn btn-secondary" sc-camel-on-click="{{ customerNew }}" style="gap: 7px;"><i class="ph ph-plus"', "new customer")
template = replace_once(template, '<sc-raw-tr style="{{ r.style }}">', '<sc-raw-tr sc-camel-on-click="{{ r.pick }}" style="{{ r.style }};cursor:pointer;">', "customer row selection")
template = replace_once(
    template,
    '<sc-raw-table class="table" style="width: 100%; font-size: 12px;">\n                          <sc-raw-thead><sc-raw-tr><sc-raw-th style="width: 116px;">Customer #</sc-raw-th><sc-raw-th>Full name</sc-raw-th><sc-raw-th style="width: 150px;">NIK</sc-raw-th><sc-raw-th style="width: 108px;">Card status</sc-raw-th>',
    '<sc-raw-table class="table" style="width:100%;table-layout:auto;font-size:12px;">\n                          <sc-raw-thead><sc-raw-tr><sc-raw-th style="width:1%;white-space:nowrap;">Customer #</sc-raw-th><sc-raw-th>Full name</sc-raw-th><sc-raw-th style="width:1%;white-space:nowrap;">NIK</sc-raw-th><sc-raw-th style="width:1%;white-space:nowrap;">Card status</sc-raw-th>',
    "content-sized customer columns",
)
template = replace_once(
    template,
    '<sc-raw-td style="font-variant-numeric: tabular-nums; color: var(--color-neutral-300);">{{ r.number }}</sc-raw-td>',
    '<sc-raw-td style="width:1%;white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--color-neutral-300);">{{ r.number }}</sc-raw-td>',
    "single-line customer number",
)
template = replace_once(
    template,
    '<sc-raw-td style="font-variant-numeric: tabular-nums; color: var(--color-neutral-500);">{{ r.nik }}</sc-raw-td>',
    '<sc-raw-td style="width:1%;white-space:nowrap;font-variant-numeric:tabular-nums;color:var(--color-neutral-500);">{{ r.nik }}</sc-raw-td>',
    "content-sized customer NIK",
)
template = replace_once(
    template,
    '<sc-raw-td><span class="{{ r.tagClass }}">{{ r.card }}</span></sc-raw-td>',
    '<sc-raw-td style="width:1%;white-space:nowrap;"><span class="{{ r.tagClass }}">{{ r.card }}</span></sc-raw-td>',
    "content-sized customer card status",
)
template = replace_once(
    template,
    '<span class="{{ s.formTagClass }}" style="margin-left: auto;">{{ s.formTag }}</span>',
    '<span class="{{ s.formTagClass }}" style="margin-left: auto;">{{ s.formTag }}</span><button type="button" class="btn btn-secondary btn-icon" sc-camel-on-click="{{ customerDeselect }}" title="Deselect customer" aria-label="Deselect customer" style="width:28px;height:28px;min-width:28px;"><i class="ph ph-x"></i></button>',
    "deselect customer",
)
template = replace_once(
    template,
    '<input class="input" type="text" value="{{ f.value }}" placeholder="{{ f.placeholder }}" sc-camel-read-only="{{ f.readonly }}" style="{{ f.style }}">',
    '<sc-if value="{{ f.isText }}" hint-placeholder-val="true"><input class="input" data-customer-field="{{ f.key }}" data-customer-readonly="{{ f.readonly }}" type="text" sc-camel-default-value="{{ f.value }}" placeholder="{{ f.placeholder }}" style="{{ f.style }}"></sc-if><sc-if value="{{ f.isStatus }}" hint-placeholder-val="false"><select class="input" data-customer-field="status" aria-label="Customer status" style="cursor:pointer;"><option value="active">Active</option><option value="inactive">Inactive</option></select></sc-if>',
    "customer text inputs and status options",
)
template = replace_once(template, '<button type="button" class="btn btn-primary" style="flex: 1; justify-content: center;">Save new</button>', '<button type="button" class="btn btn-primary" sc-camel-on-click="{{ customerSave }}" style="flex: 1; justify-content: center;">Save new</button>', "save customer")
template = replace_once(template, '<button type="button" class="btn btn-secondary" style="flex: 1; justify-content: center;">Update</button>', '<button type="button" class="btn btn-secondary" sc-camel-on-click="{{ customerUpdate }}" style="flex: 1; justify-content: center;">Update</button>', "update customer")
template = replace_once(template, 'sc-camel-on-click="{{ goPerso }}" style="flex: none;', 'sc-camel-on-click="{{ personalizeCustomer }}" style="flex: none;', "personalize selected customer")
template = template.replace('<span style="font-size: 13px; font-weight: 500; font-variant-numeric: tabular-nums;">CUS-000124</span>', '<span style="font-size: 13px; font-weight: 500; font-variant-numeric: tabular-nums;">{{ selectedCustomerNumber }}</span>')
template = template.replace('<span style="font-size: 13px; color: var(--color-neutral-300);">Siti Rahayu</span>', '<span style="font-size: 13px; color: var(--color-neutral-300);">{{ selectedCustomerName }}</span>')
template = replace_once(template, '<button type="button" class="btn btn-secondary" style="margin-left: auto; gap: 7px;"><i class="ph ph-arrow-down"', '<button type="button" class="btn btn-secondary" sc-camel-on-click="{{ logsToggle }}" style="margin-left: auto; gap: 7px;"><i class="ph ph-arrow-down"', "log ordering")
template = replace_once(template, 'sc-camel-on-click="{{ closeDialog }}" style="border-color: {{ s.dialogColor }};', 'sc-camel-on-click="{{ dialogYesClick }}" style="border-color: {{ s.dialogColor }};', "dialog confirmation")

template = replace_once(template, '      boardDot: dot(OK, "color-mix(in srgb, " + OK + " 20%, transparent)"),\n      boardColor: OK, boardLabel: "Reader connected",', '      boardDot: dot(backend && backend.view && backend.view.boardReady ? OK : BAD, "color-mix(in srgb, " + (backend && backend.view && backend.view.boardReady ? OK : BAD) + " 20%, transparent)"),\n      boardColor: backend && backend.view && backend.view.boardReady ? OK : BAD, boardLabel: backend && backend.view ? backend.view.boardLabel : "Reader checking",', "Board status")
template = replace_once(template, '      statusBar: screen === "customers" ? (locked ? "Session locked — tap the master card" : "Master registered · session open") : screen === "perso" ? s.lastEvent : "Master registered · session open",', '      statusBar: backend && backend.view ? backend.view.statusBar : (screen === "perso" ? s.lastEvent : "Starting application"),\n      selectedCustomerNumber: backend && backend.view ? backend.view.selectedCustomerNumber : "—",\n      selectedCustomerName: backend && backend.view ? backend.view.selectedCustomerName : "No customer selected",', "footer state")

template = replace_once(template, 'const OK = "oklch(0.76 0.13 152)";', 'const OK = "var(--color-success)";', "theme success color")
template = replace_once(template, 'const WARN = "oklch(0.80 0.14 86)";', 'const WARN = "var(--color-warning)";', "theme warning color")
template = replace_once(template, 'const BAD = "oklch(0.70 0.16 25)";', 'const BAD = "var(--color-danger)";', "theme danger color")

remaining_chrome = template.count("#1b1d2c")
if remaining_chrome != 2:
    raise RuntimeError(f"theme chrome color: expected layout and dark-palette matches, found {remaining_chrome}")
template = template.replace("#1b1d2c", "var(--color-chrome)", 1)
remaining_hero = template.count("#1e2133")
if remaining_hero != 2:
    raise RuntimeError(f"theme hero color: expected layout and dark-palette matches, found {remaining_hero}")
template = template.replace("#1e2133", "var(--color-hero-glow)", 1)

bridge_script = '''
<script>
document.addEventListener("input", function (event) {
  var target = event.target;
  if (!target || !target.matches) return;
  if (target.matches("input[data-customer-search]")) {
    var searchValue = target.value;
    var searchSequence = (window.__persoSearchSequence || 0) + 1;
    window.__persoSearchSequence = searchSequence;
    if (window.pywebview && window.pywebview.api) {
      Promise.resolve(window.pywebview.api.action("customer_search", { term: searchValue })).then(function (data) {
        if (searchSequence === window.__persoSearchSequence && window.__persoApplyBackend) {
          window.__persoApplyBackend(data);
        }
      }).catch(function (error) { console.error("Customer realtime search failed", error); });
    }
    return;
  }
  if (!target.matches("[data-customer-field]")) return;
  var key = target.getAttribute("data-customer-field");
  if (String(target.getAttribute("data-customer-readonly")).toLowerCase() === "true") return;
  window.__persoCustomerEditingUntil = Date.now() + 1500;
  window.__persoCustomerDraft = window.__persoCustomerDraft || {};
  window.__persoCustomerDraft[key] = target.value;
  clearTimeout(window.__persoCustomerDraftTimer);
  window.__persoCustomerDraftTimer = setTimeout(function () {
    if (window.pywebview && window.pywebview.api) window.pywebview.api.action("customer_draft", { fields: window.__persoCustomerDraft });
  }, 100);
});
document.addEventListener("focusin", function (event) {
  var target = event.target;
  if (!target || !target.matches) return;
  if (target.matches("input[data-customer-search]")) {
    window.__persoCustomerEditingUntil = Date.now() + 1500;
    return;
  }
  if (!target.matches("[data-customer-field]")) return;
  if (target.tagName !== "SELECT") target.readOnly = String(target.getAttribute("data-customer-readonly")).toLowerCase() === "true";
  window.__persoCustomerEditingUntil = Date.now() + 1500;
});
</script>
'''
template = template.replace("\n\n</body></html>", bridge_script + "\n</body></html>")

encoded = json.dumps(template, ensure_ascii=False).replace("</script>", "<\\u002Fscript>")
replacement = '<script type="__bundler/template">\n' + encoded + '\n  </script>'
result = raw[: match.start()] + replacement + raw[match.end() :]

# The standalone prototype ships with a large NFC-card thumbnail and an
# "Unpacking..." badge. Keep its loader nodes available to the bundler, but
# hide both before first paint in the functional desktop copy.
outer_head_end = result.find("</head>")
if outer_head_end < 0:
    raise RuntimeError("functional shell: closing head tag not found")
preloader_override = """
    <script id="functional-theme-bootstrap">
      (function () {
        var theme = "dark";
        try {
          if (window.localStorage.getItem("smartdispenser-perso-theme") === "light") theme = "light";
        } catch (error) {}
        document.documentElement.setAttribute("data-perso-theme", theme);
      })();
    </script>
    <style id="functional-theme-tokens">
      :root {
        --color-chrome: #1b1d2c;
        --color-hero-glow: #1e2133;
        --color-success: oklch(0.76 0.13 152);
        --color-warning: oklch(0.80 0.14 86);
        --color-danger: oklch(0.70 0.16 25);
        color-scheme: dark;
      }
      html[data-perso-theme="light"] {
        --color-bg: #f4f6fb;
        --color-surface: #ffffff;
        --color-text: #202432;
        --color-divider: rgba(40, 46, 66, 0.18);
        --color-neutral-100: #202432;
        --color-neutral-200: #303647;
        --color-neutral-300: #434b60;
        --color-neutral-400: #5b657a;
        --color-neutral-500: #737d91;
        --color-neutral-600: #8d96a8;
        --color-neutral-700: #aeb5c3;
        --color-neutral-800: #d1d6e0;
        --color-neutral-900: #e4e8ef;
        --color-accent: #6757bd;
        --color-accent-100: #332c60;
        --color-accent-200: #4b3f88;
        --color-accent-300: #5e50a9;
        --color-accent-400: #6757bd;
        --color-accent-500: #7869c8;
        --color-accent-600: #9b90d9;
        --color-accent-700: #bbb4e7;
        --color-accent-800: #d9d5f2;
        --color-accent-900: #ebe9f8;
        --color-accent-2-100: #312d51;
        --color-accent-2-200: #484273;
        --color-accent-2-300: #5d568f;
        --color-accent-2-400: #716aaa;
        --color-accent-2-500: #8b84bc;
        --color-accent-2-600: #aaa4cf;
        --color-accent-2-700: #c2bee0;
        --color-accent-2-800: #dcd9ed;
        --color-accent-2-900: #eeecf7;
        --color-chrome: #e9ecf3;
        --color-hero-glow: #e4e6f5;
        --color-success: #168653;
        --color-warning: #9a6500;
        --color-danger: #bd3b43;
        --shadow-sm: 0 0 0 1px rgba(40, 46, 66, 0.16);
        --shadow-md: 0 0 0 1px rgba(40, 46, 66, 0.13), 0 6px 18px rgba(40, 46, 66, 0.12);
        --shadow-lg: 0 0 0 1px rgba(40, 46, 66, 0.12), 0 16px 40px rgba(40, 46, 66, 0.16);
        color-scheme: light;
      }
      html[data-perso-theme="light"] body { background: #eef1f7 !important; }
    </style>
    <style id="functional-preloader-override">
      #__bundler_thumbnail, #__bundler_loading { display: none !important; }
    </style>
"""
result = result[:outer_head_end] + preloader_override + result[outer_head_end:]
DESTINATION.write_text(result, encoding="utf-8")
print(f"Created: {DESTINATION}")
