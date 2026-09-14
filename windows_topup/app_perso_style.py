"""SmartDispenser Topup console with the current Perso operator model.

The UI uses the existing topup-v1 high-level bridge. It never sends PN532
commands, keys, APDUs, or raw card blocks.
"""
from __future__ import annotations

import secrets
import math
import os
import threading
import time
import tkinter as tk
from datetime import date
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from topup_core import (
    MySqlStore,
    SerialReaderAdapter,
    SimulationReader,
    TopupError,
    Wallet,
    backup_mysql,
    load_config,
    load_provisioning_config,
    new_request_id,
    save_config,
)


BG = "#161826"
CHROME = "#1b1d2c"
CARD = "#232532"
ROW = "#292b31"
DIVIDER = "#3f424d"
TEXT = "#e9e9ed"
MUTED = "#9397ab"
BLUE = "#9184d9"
GREEN = "#65d69a"
YELLOW = "#efbd45"
RED = "#ef767a"
SCHEDULES = {0: "Belum ditentukan", 1: "Pagi", 2: "Siang", 3: "Sore"}
STARTUP_BG = "#20272b"
STARTUP_TEXT = "#dce6e9"
STARTUP_MUTED = "#91a4aa"
STARTUP_BLUE = "#2f80ed"
STARTUP_GREEN = "#20d889"


def topup_candidate_ports(ports: list[Any]) -> list[Any]:
    """Urutkan semua COM non-Bluetooth persis seperti discovery Perso."""
    usable = []
    for port in ports:
        identity = f"{port.device} {port.description} {port.hwid}".lower()
        if "bluetooth" in identity or "bthenum" in identity:
            continue
        usable.append(port)
    preferred = ("usb serial", "stlink", "stm", "cp210", "ch340", "ftdi", "uart")
    usable.sort(
        key=lambda item: (
            not any(word in (item.description or "").lower() for word in preferred),
            item.device,
        )
    )
    return usable


class TopupConsole(tk.Tk):
    def __init__(self, headless: bool = False) -> None:
        super().__init__()
        self.headless = headless
        if headless:
            self.withdraw()
        self.title("SmartDispenser — Topup Console")
        self.minsize(1060, 720)
        self.geometry("1120x780")
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.reader: SerialReaderAdapter | SimulationReader | None = None
        self.store: MySqlStore | None = None
        self.operator_id: int | None = None
        self.wallet: Wallet | None = None
        self.current_customer: dict[str, Any] | None = None
        self.busy = False
        self.history_after: str | None = None
        self.startup_active = True
        self.startup_phase = "database"
        self.startup_spinner_angle = 0
        self.startup_is_done = False
        self.startup_board_thread_active = False
        self.startup_master_thread_active = False
        self.startup_master_event_after: str | None = None
        self.startup_master_feedback_after: str | None = None
        self.startup_master_feedback_pending = False
        self.startup_master_verified = False
        self.startup_enroll_started_at: float | None = None
        self.startup_registration_card_present = False
        self.startup_registration_after: str | None = None
        self.startup_hold_after: str | None = None
        self.startup_hold_seconds = 0
        self.startup_hold_active = False
        self.startup_provision_attempted = False
        self.sidebar_collapsed = False
        self.sidebar_animating = False
        self.current_page = ""
        self.card_test_active = False
        self.card_test_started = False
        self.card_test_polling = False
        self.card_test_after: str | None = None
        self.card_test_animation_after: str | None = None
        self.card_test_animation_step = 0
        self.card_test_present = False
        self.card_test_count = 0
        self.card_test_status_due = 0.0
        self.customer_watch_active = False
        self.customer_watch_started = False
        self.customer_watch_polling = False
        self.customer_watch_after: str | None = None
        self.customer_watch_probe_due = 0.0
        self.quota_refresh_after: str | None = None
        self.quota_refresh_in_flight = False
        self.quota_overview_data: dict[str, Any] = {
            "schedules": [
                {"schedule": 1, "label": "Morning", "card_count": 0, "available_liter": 0, "used_liter": 0, "reserved_liter": 0},
                {"schedule": 2, "label": "Afternoon", "card_count": 0, "available_liter": 0, "used_liter": 0, "reserved_liter": 0},
                {"schedule": 3, "label": "Evening", "card_count": 0, "available_liter": 0, "used_liter": 0, "reserved_liter": 0},
            ],
            "available_liter": 0, "used_liter": 0, "reserved_liter": 0,
            "card_count": 0, "unscheduled_cards": 0, "quota_limit_liter": 0,
            "quota_configured": False, "allocated_liter": 0, "remaining_liter": 0,
            "over_limit": False, "loading": True, "error": "",
        }

        self.status = tk.StringVar(value="Starting Topup Console...")
        self.database_state = tk.StringVar(value="DATABASE: CHECKING")
        self.board_state = tk.StringVar(value="BOARD: SEARCHING")
        self.operator_state = tk.StringVar(value="OPERATOR: LOCKED")
        self.session_state = tk.StringVar(value="SESSION: LOCKED")
        self.card_title = tk.StringVar(value="Waiting for card")
        self.card_detail = tk.StringVar(value="Tempelkan kartu pelanggan; Card Reference dibaca otomatis.")
        self.owner_title = tk.StringVar(value="Card Reference: —")
        self.owner_detail = tk.StringVar(value="Belum ada kartu pelanggan.")
        self.balance_text = tk.StringVar(value="— L")
        self.permission_text = tk.StringVar(value="Not checked")
        self.schedule_text = tk.StringVar(value="Not checked")
        self.usage_text = tk.StringVar(value="Used — L · Reserved — L")
        self.history_query = tk.StringVar()

        self._configure_styles()
        self._build_startup()
        self.after(40, self._animate_startup)
        self.after(1000, self._startup_database)
        smoke_autoclose = os.environ.get("SMARTDISPENSER_TOPUP_SMOKE_AUTOCLOSE_MS", "")
        if smoke_autoclose.isdigit():
            self.after(max(250, int(smoke_autoclose)), self.on_close)
        smoke_force_ready = os.environ.get("SMARTDISPENSER_TOPUP_SMOKE_FORCE_READY_MS", "")
        if smoke_force_ready.isdigit():
            self.after(max(250, int(smoke_force_ready)), self._show_main)
        if not headless:
            self.after(0, self._bring_to_front)

    def _bring_to_front(self) -> None:
        self.deiconify()
        self.state("zoomed")
        self.lift()
        self.attributes("-topmost", True)
        self.focus_force()
        self.after(250, lambda: self.attributes("-topmost", False))

    def _build_startup(self) -> None:
        self.startup_root = tk.Frame(self, bg=STARTUP_BG)
        self.startup_root.pack(fill="both", expand=True)
        center = tk.Frame(self.startup_root, bg=STARTUP_BG)
        center.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(center, text="SMARTDISPENSER", bg=STARTUP_BG, fg="#f2f6f7", font=("Segoe UI", 23, "bold")).pack()
        tk.Label(center, text="TOPUP CONSOLE", bg=STARTUP_BG, fg="#8fa1a7", font=("Segoe UI", 10, "bold")).pack(pady=(2, 24))
        self.startup_canvas = tk.Canvas(center, width=112, height=112, bg=STARTUP_BG, highlightthickness=0)
        self.startup_canvas.pack()
        self.startup_title = tk.Label(center, text="Verifying Database", bg=STARTUP_BG, fg=STARTUP_TEXT, font=("Segoe UI", 13, "bold"))
        self.startup_title.pack(pady=(22, 5))
        self.startup_detail = tk.Label(center, text="Connecting Topup records to Database...", bg=STARTUP_BG, fg=STARTUP_MUTED, font=("Segoe UI", 10))
        self.startup_detail.pack()
        self.startup_master_button = tk.Button(
            self.startup_root,
            text="HOLD 10 SEC • REGISTER MASTER",
            bg=STARTUP_BLUE,
            fg="#ffffff",
            activebackground="#4a98ff",
            activeforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=10,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self.startup_master_button.bind("<ButtonPress-1>", self._begin_startup_master_hold)
        self.startup_master_button.bind("<ButtonRelease-1>", self._cancel_startup_master_hold)
        self._set_startup_master_button_enabled(False)

    def _set_startup_master_button_enabled(self, enabled: bool) -> None:
        self.startup_master_button.configure(
            state="normal" if enabled else "disabled",
            bg=STARTUP_BLUE if enabled else "#45555a",
            fg="#ffffff" if enabled else "#9aa9ad",
            activebackground="#4a98ff" if enabled else "#45555a",
            cursor="hand2" if enabled else "arrow",
        )

    def _set_startup(self, title: str, detail: str, phase: str, done: bool = False) -> None:
        self.startup_phase = phase
        self.startup_title.configure(text=title)
        self.startup_detail.configure(text=detail, fg=STARTUP_MUTED)
        self.startup_is_done = done
        if done:
            self.startup_canvas.delete("all")
            self.startup_canvas.create_oval(12, 12, 100, 100, outline=STARTUP_GREEN, width=5)
            self.startup_canvas.create_text(56, 56, text="✓", fill=STARTUP_GREEN, font=("Segoe UI", 42, "bold"))

    def _animate_startup(self) -> None:
        if not self.startup_active:
            return
        if not self.startup_is_done:
            self.startup_canvas.delete("all")
            self.startup_canvas.create_oval(12, 12, 100, 100, outline="#34444a", width=5)
            self.startup_canvas.create_arc(
                12,
                12,
                100,
                100,
                start=self.startup_spinner_angle,
                extent=110,
                style="arc",
                outline=STARTUP_BLUE,
                width=5,
            )
            self.startup_spinner_angle = (self.startup_spinner_angle + 10) % 360
        self.after(40, self._animate_startup)

    def _startup_database(self) -> None:
        try:
            config = load_config()
        except Exception as error:
            self.status.set(f"Saved Database configuration unavailable: {error}")
            self._startup_provision_database()
            return
        if not config:
            self._startup_provision_database()
            return

        candidate = MySqlStore(config)

        def verify() -> None:
            try:
                candidate.setting("last_backup_day")
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_database_failed(caught))
                return
            self.after(0, lambda: self._startup_database_ready(candidate))

        threading.Thread(target=verify, daemon=True).start()

    def _startup_database_ready(self, store: MySqlStore) -> None:
        self.store = store
        self.database_state.set("DATABASE: READY")
        self.status.set("Database ready. Authenticating configured operator...")

        def authenticate() -> None:
            try:
                operator_pin = store.config.get("operator_pin")
                if operator_pin is None:
                    operator_pin = load_provisioning_config()["operator_pin"]
                operator_id = store.login(str(operator_pin))
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_database_failed(caught))
                return
            self.after(0, lambda: self._startup_database_authenticated(operator_id))

        threading.Thread(target=authenticate, daemon=True).start()

    def _startup_database_authenticated(self, operator_id: int) -> None:
        self.operator_id = operator_id
        self.operator_state.set("OPERATOR: ACTIVE")
        self.status.set("Database ready.")
        self.after(5000, self.backup_if_due)
        self._set_startup("Database ready", "Topup activity loaded.", "database", done=True)
        self.after(700, self._startup_board)

    def _startup_database_failed(self, error: Exception) -> None:
        if not self.startup_provision_attempted:
            self.status.set(f"Database connection needs repair: {error}")
            self._startup_provision_database()
            return
        self.database_state.set("DATABASE: UNAVAILABLE")
        self.status.set(str(error))
        self._set_startup("Database issue", "Waiting for the local Database. Retrying...", "database")
        self.after(1500, self._retry_startup_database)

    def _retry_startup_database(self) -> None:
        if not self.startup_active:
            return
        self.startup_provision_attempted = False
        self._startup_database()

    def _provision_from_file(self) -> MySqlStore:
        provision = load_provisioning_config()
        config = {
            "host": str(provision["host"]),
            "port": int(provision["port"]),
            "admin_user": str(provision["admin_user"]),
            "admin_password": str(provision["admin_password"]),
            "app_user": "sd_topup_app",
            "app_password": secrets.token_urlsafe(24),
            "operator_pin": str(provision["operator_pin"]),
        }
        store = MySqlStore.provision(config, str(provision["operator_pin"]))
        save_config(config)
        return store

    def _startup_provision_database(self) -> None:
        self.startup_provision_attempted = True
        self.database_state.set("DATABASE: PREPARING")
        self._set_startup("Preparing Database", "Applying the local Topup configuration automatically...", "database")

        def provision() -> None:
            try:
                store = self._provision_from_file()
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_database_failed(caught))
                return
            self.after(0, lambda: self._startup_database_ready(store))

        threading.Thread(target=provision, daemon=True).start()

    @staticmethod
    def _find_topup_board() -> tuple[SerialReaderAdapter, str]:
        try:
            from serial.tools import list_ports
        except ImportError as error:
            raise TopupError("pyserial is not installed") from error
        ports = topup_candidate_ports(list(list_ports.comports()))
        last_error: Exception | None = None
        for port in ports:
            candidate = SerialReaderAdapter(port.device)
            try:
                candidate.connect()
                return candidate, port.device
            except Exception as error:
                last_error = error
                candidate.close()
        raise TopupError("Topup Board not found" + (f": {last_error}" if last_error else ""))

    def _startup_board(self) -> None:
        if not self.startup_active:
            return
        self._set_startup("Searching for Topup device", "Searching USB Serial Port at 115200 baud...", "board")
        self.board_state.set("BOARD: SEARCHING")
        if os.environ.get("SMARTDISPENSER_TOPUP_SKIP_BOARD_DISCOVERY") == "1":
            self.after(0, lambda: self._startup_board_failed(TopupError("Board discovery disabled for smoke test")))
            return
        self.startup_board_thread_active = True

        def find() -> None:
            try:
                result = self._find_topup_board()
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_board_failed(caught))
                return
            self.after(0, lambda: self._startup_board_ready(result))

        threading.Thread(target=find, daemon=True).start()

    def _startup_board_ready(self, result: tuple[SerialReaderAdapter, str]) -> None:
        self.startup_board_thread_active = False
        reader, port = result
        if not self.startup_active:
            self._use_board(reader, port)
            return
        self.reader = reader
        self.board_state.set(f"BOARD: {port}")
        if self.store and self.operator_id is not None:
            self.status.set("Topup Board connected. Waiting for master card verification.")
        else:
            self._startup_database_failed(TopupError("Database authentication is not ready"))
            return
        # Firmware Topup reports the master authorization asynchronously, just
        # like Perso. Drain discovery-era events, then watch at UI speed so a
        # physical tap is acknowledged without waiting for the UNLOCK retry.
        self.reader.clear_events()
        self.startup_master_feedback_pending = False
        self.startup_master_verified = False
        self._set_startup("Checking master card", "Checking registration status on Topup Board...", "master")
        self._schedule_startup_master_event_poll(40)
        self.after(900, self._startup_master_attempt)

    def _schedule_startup_master_event_poll(self, delay: int = 50) -> None:
        if self.startup_master_event_after:
            self.after_cancel(self.startup_master_event_after)
        self.startup_master_event_after = self.after(delay, self._poll_startup_master_events)

    def _poll_startup_master_events(self) -> None:
        self.startup_master_event_after = None
        if not self.startup_active or self.startup_phase != "master" or not self.reader:
            return
        event = self.reader.next_event()
        while event is not None:
            if event.get("scope") == "master" and event.get("state") == "session_opened":
                # The Board event is the authoritative proof. Reflect it within
                # one UI tick, then preserve Perso's visible two-stage feedback.
                self.reader.master_unlocked = True
                self._startup_master_detected()
                return
            event = self.reader.next_event()
        self._schedule_startup_master_event_poll()

    def _startup_master_detected(self) -> None:
        if (not self.startup_active or self.startup_phase != "master"
                or self.startup_master_feedback_pending or self.startup_master_verified):
            return
        self.startup_master_feedback_pending = True
        if self.startup_master_event_after:
            self.after_cancel(self.startup_master_event_after)
            self.startup_master_event_after = None
        self._set_startup(
            "Card detected",
            "Checking whether this is the registered master card...",
            "master",
        )
        self.startup_master_feedback_after = self.after(350, self._startup_master_verified_feedback)

    def _startup_master_verified_feedback(self) -> None:
        self.startup_master_feedback_after = None
        if not self.startup_active or self.startup_phase != "master" or self.startup_master_verified:
            return
        self.startup_master_feedback_pending = False
        self.startup_master_verified = True
        self.startup_master_thread_active = False
        self.session_state.set("SESSION: ACTIVE")
        self.status.set("Master accepted. Topup Console is ready.")
        self._set_startup("Master card verified", "Topup session active. Opening workspace...", "ready", done=True)
        self.after(1200, self._show_main)

    def _startup_master_attempt(self) -> None:
        if (not self.startup_active or self.startup_phase != "master" or not self.reader
                or self.startup_master_thread_active or self.startup_master_feedback_pending
                or self.startup_master_verified):
            return
        self.startup_master_thread_active = True
        # Status menunggu sudah ditampilkan oleh indikator di bawah. Biarkan
        # area detail kosong agar pesan yang sama tidak muncul dua kali.
        self.startup_detail.configure(text="", fg=MUTED)

        def verify() -> None:
            try:
                self.reader.unlock_master()
            except Exception as error:
                if isinstance(error, TopupError) and str(error) == "master not set":
                    self.after(0, self._show_startup_master_registration)
                    return
                self.after(0, lambda caught=error: self._startup_master_wait(caught))
                return
            self.after(0, self._startup_master_ready)

        threading.Thread(target=verify, daemon=True).start()

    def _show_startup_master_registration(self) -> None:
        self.startup_master_thread_active = False
        if not self.startup_active:
            return
        self.startup_registration_card_present = False
        self.startup_hold_active = False
        self.startup_hold_seconds = 0
        self._set_startup(
            "No master card registered",
            "Tap the master card, then hold the button for 10 seconds.",
            "master_registration",
        )
        self._set_startup_master_button_enabled(False)
        if not self.startup_master_button.winfo_ismapped():
            self.startup_master_button.place(relx=0.5, rely=0.76, anchor="center")
        self.startup_master_button.configure(text="HOLD 10 SEC • REGISTER MASTER")
        self._begin_startup_registration_watch()

    def _begin_startup_registration_watch(self) -> None:
        if (not self.startup_active or self.startup_phase != "master_registration"
                or not self.reader or self.startup_master_thread_active):
            return
        self.startup_master_thread_active = True

        def begin() -> None:
            try:
                self.reader.begin_master_enrollment()
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_enroll_failed(caught))
                return
            self.after(0, self._startup_registration_watch_ready)

        threading.Thread(target=begin, daemon=True).start()

    def _startup_registration_watch_ready(self) -> None:
        self.startup_master_thread_active = False
        if not self.startup_active or self.startup_phase != "master_registration":
            return
        self._schedule_startup_registration_poll(80)

    def _schedule_startup_registration_poll(self, delay: int = 250) -> None:
        if self.startup_registration_after:
            self.after_cancel(self.startup_registration_after)
        self.startup_registration_after = self.after(delay, self._poll_startup_registration)

    def _poll_startup_registration(self) -> None:
        self.startup_registration_after = None
        if (not self.startup_active or self.startup_phase != "master_registration"
                or not self.reader or self.startup_hold_active or self.startup_master_thread_active):
            return
        self.startup_master_thread_active = True

        def poll() -> None:
            try:
                state = self.reader.master_enrollment_status().get("state", "waiting")
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_enroll_failed(caught))
                return
            self.after(0, lambda current=state: self._startup_registration_state(current))

        threading.Thread(target=poll, daemon=True).start()

    def _startup_registration_state(self, state: str) -> None:
        self.startup_master_thread_active = False
        if not self.startup_active or self.startup_phase != "master_registration":
            return
        if state == "registered":
            self._startup_enroll_ready()
            return
        present = state in ("holding", "ready")
        self.startup_registration_card_present = present
        self._set_startup_master_button_enabled(present)
        if present:
            self._set_startup(
                "Master card detected",
                "Keep the card on the reader and hold the button for 10 seconds.",
                "master_registration",
            )
        else:
            self._set_startup(
                "Waiting for master card",
                "Tap the master card, then hold the button for 10 seconds.",
                "master_registration",
            )
        self._schedule_startup_registration_poll()

    def _begin_startup_master_hold(self, _event: tk.Event | None = None) -> None:
        if (not self.startup_active or self.startup_phase != "master_registration"
                or not self.reader or not self.startup_registration_card_present
                or self.startup_hold_active or self.startup_master_thread_active):
            return
        if self.startup_registration_after:
            self.after_cancel(self.startup_registration_after)
            self.startup_registration_after = None
        self.startup_hold_active = True
        self.startup_hold_seconds = 0
        self.startup_enroll_started_at = time.monotonic()
        self.startup_master_thread_active = True
        self._set_startup("Registering master card", "Hold button and card: 0 / 10 seconds", "master_registration")

        def restart_hold() -> None:
            try:
                self.reader.begin_master_enrollment()
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_enroll_failed(caught))
                return
            self.after(0, self._startup_master_hold_started)

        threading.Thread(target=restart_hold, daemon=True).start()

    def _startup_master_hold_started(self) -> None:
        self.startup_master_thread_active = False
        if not self.startup_hold_active or self.startup_phase != "master_registration":
            self._begin_startup_registration_watch()
            return
        self.startup_hold_after = self.after(1000, self._tick_startup_master_hold)

    def _tick_startup_master_hold(self) -> None:
        self.startup_hold_after = None
        if (not self.startup_active or self.startup_phase != "master_registration"
                or not self.startup_hold_active):
            return
        self.startup_hold_seconds += 1
        self._set_startup(
            "Registering master card",
            f"Hold button and card: {self.startup_hold_seconds} / 10 seconds",
            "master_registration",
        )
        if self.startup_hold_seconds >= 10:
            self.startup_hold_active = False
            self._commit_startup_master_hold()
            return
        self.startup_hold_after = self.after(1000, self._tick_startup_master_hold)

    def _cancel_startup_master_hold(self, _event: tk.Event | None = None) -> None:
        if not self.startup_hold_active:
            return
        self.startup_hold_active = False
        self.startup_enroll_started_at = None
        if self.startup_hold_after:
            self.after_cancel(self.startup_hold_after)
            self.startup_hold_after = None
        self.startup_hold_seconds = 0
        self._set_startup(
            "Waiting for master card",
            "Registration cancelled. Tap the card and hold the button for 10 seconds.",
            "master_registration",
        )
        if not self.startup_master_thread_active:
            self._begin_startup_registration_watch()

    def _commit_startup_master_hold(self) -> None:
        if not self.reader or self.startup_master_thread_active:
            return
        self.startup_master_thread_active = True

        def commit() -> None:
            try:
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    state = self.reader.master_enrollment_status().get("state", "waiting")
                    if state == "registered":
                        self.after(0, self._startup_enroll_ready)
                        return
                    if state == "ready":
                        self.reader.commit_master_enrollment()
                        self.after(0, self._startup_enroll_ready)
                        return
                    if state == "waiting":
                        raise TopupError("card removed")
                    time.sleep(.1)
                raise TopupError("master hold incomplete")
            except Exception as error:
                self.after(0, lambda caught=error: self._startup_enroll_failed(caught))

        threading.Thread(target=commit, daemon=True).start()

    def _startup_enroll_failed(self, error: Exception) -> None:
        self.startup_master_thread_active = False
        self.startup_enroll_started_at = None
        self.startup_hold_active = False
        if self.startup_hold_after:
            self.after_cancel(self.startup_hold_after)
            self.startup_hold_after = None
        if not self.startup_active or self.startup_phase != "master_registration":
            return
        message = str(error)
        if message == "nfc unavailable":
            message = "NFC Reader is not ready. Power-cycle the Board, then try again."
        elif message in ("card absent", "card removed"):
            message = "Card was not held steadily on the NFC Reader for 10 seconds."
        self._set_startup("Master registration did not complete", message, "master_registration")
        self.startup_detail.configure(fg=YELLOW)
        self._set_startup_master_button_enabled(False)
        self._begin_startup_registration_watch()

    def _startup_enroll_ready(self) -> None:
        self.startup_master_thread_active = False
        self.startup_enroll_started_at = None
        self.startup_hold_active = False
        if self.startup_registration_after:
            self.after_cancel(self.startup_registration_after)
            self.startup_registration_after = None
        if not self.startup_active:
            return
        self.startup_master_button.place_forget()
        self._set_startup("Master card registered", "Opening Topup workspace...", "ready", done=True)
        self.session_state.set("SESSION: ACTIVE")
        self.status.set("Master registered. Topup Console is ready.")
        self.after(700, self._show_main)

    def _startup_master_wait(self, _error: Exception) -> None:
        self.startup_master_thread_active = False
        if (not self.startup_active or self.startup_phase != "master"
                or self.startup_master_feedback_pending or self.startup_master_verified):
            return
        self.startup_title.configure(text="Activate Topup session")
        self.startup_detail.configure(text="", fg=STARTUP_MUTED)
        self.after(900, self._startup_master_attempt)

    def _startup_master_ready(self) -> None:
        self.startup_master_thread_active = False
        if not self.startup_active or self.startup_master_verified:
            return
        # Compatibility for older firmware without EVT master/session_opened:
        # still show the same Perso two-stage feedback after UNLOCK succeeds.
        self._startup_master_detected()

    def _startup_board_failed(self, error: Exception) -> None:
        self.startup_board_thread_active = False
        self.board_state.set("BOARD: NOT CONNECTED")
        self.status.set(str(error))
        if self.startup_active:
            self._set_startup("Trying to connect to device", f"{error}. Retrying...", "board")
            self.after(1000, self._startup_board)

    def _show_main(self) -> None:
        if not self.startup_active:
            return
        if self.startup_master_event_after:
            self.after_cancel(self.startup_master_event_after)
            self.startup_master_event_after = None
        if self.startup_master_feedback_after:
            self.after_cancel(self.startup_master_feedback_after)
            self.startup_master_feedback_after = None
        self.startup_active = False
        self.startup_root.destroy()
        self._build()
        self.history_query.trace_add("write", self._schedule_history_refresh)
        if self.store:
            self.badges["database"].configure(fg=GREEN)
        elif self.database_state.get() == "DATABASE: CONFIG ERROR":
            self.badges["database"].configure(fg=RED)
        else:
            self.badges["database"].configure(fg=YELLOW)
        if self.reader:
            self.badges["board"].configure(fg=GREEN)
        elif self.startup_board_thread_active:
            self.badges["board"].configure(fg=YELLOW)
        else:
            self.badges["board"].configure(fg=RED)
        if self._session_ready():
            self.badges["session"].configure(fg=GREEN)
        self._refresh_access()
        self._schedule_quota_refresh(0)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 20))
        style.configure("Heading.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 14))
        style.configure("Metric.TLabel", background=CARD, foreground=TEXT, font=("Segoe UI", 18))
        style.configure("Small.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("TButton", background=BG, foreground=BLUE, borderwidth=1, bordercolor=BLUE, lightcolor=BLUE, darkcolor=BLUE, padding=(12, 8), font=("Segoe UI", 10))
        style.map("TButton", background=[("active", "#2b2741"), ("disabled", CARD)], foreground=[("disabled", "#595d6c")], bordercolor=[("disabled", DIVIDER)])
        style.configure("Dark.TButton", background=CARD, foreground=TEXT, bordercolor=DIVIDER, lightcolor=DIVIDER, darkcolor=DIVIDER)
        style.map("Dark.TButton", background=[("active", ROW)])
        style.configure("Danger.TButton", background=BG, foreground=RED, bordercolor=RED, lightcolor=RED, darkcolor=RED)
        style.map("Danger.TButton", background=[("active", "#3b232c")])
        style.configure("Treeview", background=BG, fieldbackground=BG, foreground=TEXT, rowheight=32, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=BG, foreground=MUTED, relief="flat", font=("Segoe UI", 9))
        style.map("Treeview", background=[("selected", "#423a6a")])

    def _build(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True)

        self.navigation = tk.Frame(root, bg=CHROME, width=212, highlightthickness=1, highlightbackground="#292b3c")
        self.navigation.pack(side="left", fill="y")
        self.navigation.pack_propagate(False)

        brand = tk.Frame(self.navigation, bg=CHROME, height=82)
        brand.pack(fill="x")
        brand.pack_propagate(False)
        self.brand_text = tk.Label(brand, text="SmartDispenser\nTOPUP CONSOLE", bg=CHROME, fg=TEXT, justify="left", font=("Segoe UI", 10))
        self.brand_text.pack(side="left", padx=(16, 4), pady=16)
        self.sidebar_toggle = tk.Button(
            brand, text="☰", command=self.toggle_sidebar, width=2, bg=CHROME, fg=TEXT,
            activebackground="#2b2741", activeforeground="white", relief="flat",
            borderwidth=0, font=("Segoe UI Symbol", 12), cursor="hand2",
        )
        self.sidebar_toggle.pack(side="right", padx=10)
        self.menu_label = tk.Label(self.navigation, text="MENU", bg=CHROME, fg=MUTED, font=("Segoe UI", 8))
        self.menu_label.pack(anchor="w", padx=16, pady=(14, 8))

        self.nav_buttons: dict[str, tk.Button] = {}
        self.nav_labels = {
            "test": ("◎", "Test Card"),
            "dashboard": ("◉", "Overview"),
            "topup": ("▣", "Card Topup"),
            "history": ("⌁", "Transactions"),
            "logs": ("▤", "Activity Logs"),
        }
        for key, (icon, label) in self.nav_labels.items():
            button = tk.Button(
                self.navigation, text=f"{icon}   {label}", command=lambda item=key: self.show_page(item), anchor="w",
                bg=CHROME, fg="#cfd3e5", activebackground="#2b2741", activeforeground="white",
                relief="flat", borderwidth=0, padx=14, pady=11,
                font=("Segoe UI", 10), cursor="hand2",
            )
            button.pack(fill="x", padx=8, pady=2)
            self.nav_buttons[key] = button

        self.sidebar_status = tk.Frame(self.navigation, bg=CHROME)
        self.sidebar_status.pack(side="bottom", fill="x", padx=15, pady=16)
        self.badges: dict[str, tk.Label] = {}
        for key, variable in (
            ("database", self.database_state),
            ("board", self.board_state),
            ("session", self.session_state),
        ):
            label = tk.Label(self.sidebar_status, textvariable=variable, bg=CHROME, fg=YELLOW, anchor="w", font=("Segoe UI", 8))
            label.pack(fill="x", pady=2)
            self.badges[key] = label

        main = tk.Frame(root, bg=BG)
        main.pack(side="right", fill="both", expand=True)
        header = tk.Frame(main, bg=BG, height=86, highlightthickness=1, highlightbackground="#292b3c")
        header.pack(fill="x")
        header.pack_propagate(False)
        header_left = tk.Frame(header, bg=BG)
        header_left.pack(side="left", padx=24, pady=14)
        self.page_kicker = tk.StringVar(value="TOPUP — OPERATOR CONSOLE")
        self.page_title = tk.StringVar(value="Topup overview")
        self.page_description = tk.StringVar(value="Database-backed Wallet Data operations with read-back verification.")
        tk.Label(header_left, textvariable=self.page_kicker, bg=BG, fg=BLUE, anchor="w", font=("Segoe UI", 8)).pack(anchor="w")
        tk.Label(header_left, textvariable=self.page_title, bg=BG, fg=TEXT, anchor="w", font=("Segoe UI", 17)).pack(anchor="w", pady=(3, 0))
        tk.Label(header, textvariable=self.page_description, bg=BG, fg=MUTED, justify="right", wraplength=430, font=("Segoe UI", 9)).pack(side="right", padx=24)

        footer = tk.Frame(main, bg=CHROME, height=28, highlightthickness=1, highlightbackground="#292b3c")
        footer.pack(side="bottom", fill="x")
        footer.pack_propagate(False)
        tk.Label(footer, textvariable=self.status, bg=CHROME, fg=MUTED, anchor="w", font=("Segoe UI", 8)).pack(fill="x", padx=16, pady=5)

        content = tk.Frame(main, bg=BG)
        content.pack(fill="both", expand=True, padx=22, pady=16)
        self.pages: dict[str, tk.Frame] = {}
        for key in ("test", "dashboard", "topup", "history", "logs"):
            page = tk.Frame(content, bg=BG)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page

        self._build_test_card()
        self._build_dashboard()
        self._build_topup()
        self._build_history()
        self._build_logs()
        self.show_page("dashboard")
        self._refresh_access()

    def toggle_sidebar(self) -> None:
        if self.sidebar_animating:
            return
        self.sidebar_animating = True
        self.sidebar_collapsed = not self.sidebar_collapsed
        target = 58 if self.sidebar_collapsed else 212
        if self.sidebar_collapsed:
            self.brand_text.pack_forget()
            self.menu_label.configure(text="")
            self.sidebar_status.pack_forget()
            for key, button in self.nav_buttons.items():
                button.configure(text=self.nav_labels[key][0], anchor="center", padx=0)

        def animate() -> None:
            current = self.navigation.winfo_width()
            step = -14 if target < current else 14
            next_width = max(target, current + step) if step < 0 else min(target, current + step)
            self.navigation.configure(width=next_width)
            if next_width != target:
                self.after(12, animate)
                return
            if not self.sidebar_collapsed:
                self.brand_text.pack(side="left", padx=(16, 4), pady=16, before=self.sidebar_toggle)
                self.menu_label.configure(text="MENU")
                self.sidebar_status.pack(side="bottom", fill="x", padx=15, pady=16)
                for key, button in self.nav_buttons.items():
                    icon, label = self.nav_labels[key]
                    button.configure(text=f"{icon}   {label}", anchor="w", padx=14)
            self.sidebar_animating = False

        animate()

    def _card(self, parent: tk.Widget, padding: int = 20) -> ttk.Frame:
        return ttk.Frame(parent, style="Card.TFrame", padding=padding)

    def _build_test_card(self) -> None:
        page = self.pages["test"]
        panel = self._card(page, 20)
        panel.pack(fill="both", expand=True)
        center = tk.Frame(panel, bg=CARD)
        center.place(relx=0.5, rely=0.5, anchor="center")

        self.card_test_canvas = tk.Canvas(center, width=160, height=160, bg=CARD, highlightthickness=0)
        self.card_test_canvas.pack()
        self.card_test_title = tk.StringVar(value="Waiting for card")
        self.card_test_detail = tk.StringVar(value="The reader test starts automatically on this page.")
        self.card_test_counter = tk.StringVar(value="0 card detections")
        tk.Label(center, textvariable=self.card_test_title, bg=CARD, fg=BLUE, font=("Segoe UI", 16, "bold")).pack(pady=(18, 5))
        tk.Label(center, textvariable=self.card_test_counter, bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack()
        tk.Label(
            center,
            textvariable=self.card_test_detail,
            bg=CARD,
            fg=MUTED,
            justify="center",
            wraplength=470,
            font=("Segoe UI", 9),
        ).pack(pady=(22, 0))
        self._animate_card_test()

    def _animate_card_test(self) -> None:
        if not hasattr(self, "card_test_canvas") or not self.card_test_canvas.winfo_exists():
            return
        self.card_test_canvas.delete("all")
        phase = self.card_test_animation_step / 18.0
        color = GREEN if self.card_test_present else (YELLOW if self.card_test_active else BLUE)
        for index in range(2):
            wave = (phase + index * 0.5) % 1.0
            radius = 38 + 31 * wave
            shade = "#423a6a" if wave > 0.62 else color
            self.card_test_canvas.create_oval(80-radius, 80-radius, 80+radius, 80+radius, outline=shade, width=1)
        pulse = 32 + int(3 * math.sin(self.card_test_animation_step / 5.0))
        self.card_test_canvas.create_oval(80-pulse, 80-pulse, 80+pulse, 80+pulse, outline=color, width=2)
        self.card_test_canvas.create_text(80, 80, text="◎", fill=color, font=("Segoe UI Symbol", 27, "bold"))
        self.card_test_animation_step = (self.card_test_animation_step + 1) % 180
        self.card_test_animation_after = self.after(55, self._animate_card_test)

    def _start_card_test(self) -> None:
        if self.card_test_active:
            return
        self.card_test_active = True
        self.card_test_started = False
        self.card_test_present = False
        self.card_test_status_due = 0.0
        self.card_test_title.set("Waiting for card")
        self.card_test_detail.set("Keep a card flat on the NFC reader. This test is read-only.")
        self.status.set("Test Card active — waiting for a card.")
        if self.reader:
            self.reader.clear_events()
        self._schedule_card_test_poll(80)

    def _stop_card_test(self, send_command: bool = True) -> None:
        self.card_test_active = False
        self.card_test_started = False
        self.card_test_present = False
        if self.card_test_after:
            self.after_cancel(self.card_test_after)
            self.card_test_after = None
        if send_command and self.reader:
            threading.Thread(target=self._stop_card_test_on_board, daemon=True).start()

    def _stop_card_test_on_board(self) -> None:
        try:
            if self.reader:
                self.reader.stop_card_test()
        except Exception:
            # Page transition/close must remain usable if the Board disappears.
            pass

    def _schedule_card_test_poll(self, delay: int = 300) -> None:
        if not self.card_test_active:
            return
        if self.card_test_after:
            self.after_cancel(self.card_test_after)
        self.card_test_after = self.after(delay, self._poll_card_test)

    def _poll_card_test(self) -> None:
        self.card_test_after = None
        if not self.card_test_active or self.card_test_polling:
            return
        if not self.reader:
            self.card_test_title.set("Reader not connected")
            self.card_test_detail.set("Reconnect the Topup Board to continue the read-only test.")
            self._schedule_card_test_poll(800)
            return
        if self.busy:
            self._schedule_card_test_poll(300)
            return
        if not self.card_test_started:
            self.card_test_polling = True

            def start() -> None:
                try:
                    self.reader.start_card_test()
                    error = None
                except Exception as caught:
                    error = caught
                self.after(0, lambda: self._card_test_started(error))

            threading.Thread(target=start, daemon=True).start()
            return
        event = self.reader.next_event()
        while event is not None:
            if event.get("scope") == "card_test":
                self._card_test_event(event.get("state") == "detected")
            event = self.reader.next_event()
        # Event adalah jalur utama. Status read-only ini menjadi pengaman bila
        # satu baris EVT hilang di UART/CH340, sama seperti verifikasi master
        # yang tidak hanya bergantung pada satu event.
        now = time.monotonic()
        if now >= self.card_test_status_due:
            self.card_test_polling = True
            self.card_test_status_due = now + 0.25

            def probe() -> None:
                try:
                    present, error = self.reader.card_test_status(), None
                except Exception as caught:
                    present, error = False, caught
                self.after(0, lambda: self._card_test_status_result(present, error))

            threading.Thread(target=probe, daemon=True).start()
            return
        self._schedule_card_test_poll(50)

    def _card_test_started(self, error: Exception | None) -> None:
        self.card_test_polling = False
        if not self.card_test_active:
            return
        if error is not None:
            self.card_test_started = False
            self.card_test_present = False
            self.card_test_title.set("Reader test unavailable")
            self.card_test_detail.set(str(error))
            self.status.set(f"Test Card: {error}")
            self._schedule_card_test_poll(800)
            return
        self.card_test_started = True
        self.card_test_status_due = 0.0
        self._schedule_card_test_poll(80)

    def _card_test_status_result(self, present: bool, error: Exception | None) -> None:
        self.card_test_polling = False
        if not self.card_test_active:
            return
        if error is not None:
            self.card_test_started = False
            self.card_test_title.set("Reader test unavailable")
            self.card_test_detail.set(str(error))
            self.status.set(f"Test Card: {error}")
            self._schedule_card_test_poll(500)
            return
        if present != self.card_test_present:
            self._card_test_event(present)
        self._schedule_card_test_poll(50)

    def _card_test_event(self, present: bool) -> None:
        if present and not self.card_test_present:
            self.card_test_count += 1
            self.card_test_counter.set(f"{self.card_test_count} card detection" + ("" if self.card_test_count == 1 else "s"))
        self.card_test_present = present
        if present:
            self.card_test_title.set("Card detected")
            self.card_test_detail.set("The reader detected a card. Nothing was written or changed.")
            self.status.set("Test Card: card detected — read-only.")
        else:
            self.card_test_title.set("Card removed — waiting for another card")
            self.card_test_detail.set("Keep a card flat on the NFC reader. The result updates automatically.")
            self.status.set("Test Card active — waiting for a card.")

    def _build_dashboard(self) -> None:
        page = self.pages["dashboard"]
        panel = self._card(page, 28)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Topup Operation", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Complete each requirement before changing Wallet Data.", style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(6, 20))

        self.dashboard_steps: list[tk.Label] = []
        step_box = tk.Frame(panel, bg=CARD)
        step_box.pack(fill="x")
        for _ in range(3):
            label = tk.Label(step_box, bg=ROW, fg=MUTED, anchor="w", padx=12, pady=10, font=("Segoe UI", 10, "bold"))
            label.pack(fill="x", pady=3)
            self.dashboard_steps.append(label)

        actions = ttk.Frame(panel, style="Card.TFrame")
        actions.pack(fill="x", pady=(22, 0))
        self.session_button = ttk.Button(actions, text="Verify Master Card", command=self.unlock_master, state="disabled")
        self.session_button.pack(side="left", padx=(0, 8))
        self.customer_watch_label = ttk.Label(actions, text="○  Waiting for customer card", style="Card.TLabel", foreground=BLUE)
        self.customer_watch_label.pack(side="left")

        summary = ttk.Frame(panel, style="Card.TFrame")
        summary.pack(fill="x", pady=(30, 0))
        for column, (title, variable, color) in enumerate((
            ("BALANCE", self.balance_text, GREEN),
            ("CARD STATUS", self.permission_text, BLUE),
            ("SCHEDULE", self.schedule_text, YELLOW),
        )):
            summary.columnconfigure(column, weight=1)
            card = ttk.Frame(summary, style="Card.TFrame", padding=(16, 12))
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0))
            ttk.Label(card, text=title, style="Small.TLabel", foreground=color).pack(anchor="w")
            ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(5, 0))

    def _build_topup(self) -> None:
        page = self.pages["topup"]
        panel = self._card(page, 22)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Card Topup", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Every change requires an active master session and final read-back verification.", style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(5, 16))

        owner = tk.Frame(panel, bg=ROW)
        owner.pack(fill="x", pady=(0, 14))
        tk.Label(owner, textvariable=self.owner_title, bg=ROW, fg="#f1f5f6", anchor="w", font=("Segoe UI", 13, "bold"), padx=14, pady=10).pack(fill="x")
        tk.Label(owner, textvariable=self.owner_detail, bg=ROW, fg=MUTED, anchor="w", font=("Segoe UI", 9), padx=14).pack(fill="x", pady=(0, 10))

        balance_hero = tk.Frame(panel, bg="#2b2741", padx=20, pady=20)
        balance_hero.pack(fill="x", pady=(0, 16))
        tk.Label(balance_hero, text="ACTIVE BALANCE", bg="#2b2741", fg=BLUE, font=("Segoe UI", 9, "bold")).pack()
        tk.Label(balance_hero, textvariable=self.balance_text, bg="#2b2741", fg=TEXT, font=("Segoe UI", 38, "bold")).pack(pady=(5, 0))

        wallet = ttk.Frame(panel, style="Card.TFrame")
        wallet.pack(fill="x", pady=(0, 14))
        ttk.Label(wallet, textvariable=self.card_title, style="Metric.TLabel").pack(anchor="w")
        ttk.Label(wallet, textvariable=self.card_detail, style="Card.TLabel", foreground=MUTED, wraplength=1000).pack(anchor="w", pady=(5, 4))
        ttk.Label(wallet, textvariable=self.usage_text, style="Card.TLabel", foreground=YELLOW).pack(anchor="w")

        amount_box = tk.Frame(panel, bg=CARD)
        amount_box.pack(fill="x", pady=(16, 10))
        tk.Label(amount_box, text="BALANCE", bg=CARD, fg=BLUE, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 7))
        self.mutation_buttons: list[ttk.Button] = []
        for label, amount in (("+10 L", 10), ("+20 L", 20), ("+30 L", 30), ("−10 L", -10), ("−20 L", -20), ("−30 L", -30)):
            button = ttk.Button(amount_box, text=label, command=lambda value=amount: self.change("balance_adjust", value))
            button.pack(side="left", padx=(0, 7))
            self.mutation_buttons.append(button)

        manage = tk.Frame(panel, bg=CARD)
        manage.pack(fill="x", pady=(14, 0))
        tk.Label(manage, text="STATUS AND SCHEDULE", bg=CARD, fg=BLUE, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 7))
        toggle = ttk.Button(manage, text="Activate / Deactivate", command=self.toggle_active, style="Dark.TButton")
        toggle.pack(side="left", padx=(0, 7))
        self.mutation_buttons.append(toggle)
        for value, label in ((1, "Morning"), (2, "Afternoon"), (3, "Evening")):
            button = ttk.Button(manage, text=label, command=lambda schedule=value: self.change("set_schedule", schedule), style="Dark.TButton")
            button.pack(side="left", padx=(0, 7))
            self.mutation_buttons.append(button)
        release = ttk.Button(manage, text="Release Reserved", command=lambda: self.change("release_reserved", None), style="Dark.TButton")
        release.pack(side="left")
        self.mutation_buttons.append(release)

    def _build_history(self) -> None:
        page = self.pages["history"]
        panel = self._card(page, 20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Transactions", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Search by Card Reference, action, or date.", style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(4, 12))
        search = tk.Frame(panel, bg=CARD)
        search.pack(fill="x", pady=(0, 12))
        self.history_entry = tk.Entry(search, textvariable=self.history_query, bg=ROW, fg="white", insertbackground="white", relief="flat", font=("Segoe UI", 10))
        self.history_entry.pack(side="left", fill="x", expand=True, ipady=8)
        ttk.Button(search, text="×", command=lambda: self.history_query.set(""), width=3, style="Dark.TButton").pack(side="left", padx=(7, 0))
        columns = ("time", "reference", "action", "amount", "before", "after")
        self.history_table = ttk.Treeview(panel, columns=columns, show="headings")
        for key, title, width in (("time", "TIME", 165), ("reference", "CARD REFERENCE", 220), ("action", "ACTION", 180), ("amount", "LITER", 80), ("before", "BEFORE", 90), ("after", "AFTER", 90)):
            self.history_table.heading(key, text=title)
            self.history_table.column(key, width=width, anchor="w")
        self.history_table.pack(fill="both", expand=True)

    def _build_logs(self) -> None:
        page = self.pages["logs"]
        panel = self._card(page, 20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Activity Logs", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(panel, text="Database activity without NFC keys or raw card blocks.", style="Card.TLabel", foreground=MUTED).pack(anchor="w", pady=(4, 12))
        self.log_table = ttk.Treeview(panel, columns=("time", "type", "detail"), show="headings")
        for key, title, width in (("time", "TIME", 180), ("type", "TYPE", 220), ("detail", "DETAIL", 700)):
            self.log_table.heading(key, text=title)
            self.log_table.column(key, width=width, anchor="w")
        self.log_table.pack(fill="both", expand=True)
        ttk.Button(panel, text="Refresh", command=self.refresh_logs, style="Dark.TButton").pack(anchor="e", pady=(10, 0))

    def show_page(self, key: str) -> None:
        if self.wallet is not None and self.current_page == "topup" and key != "topup":
            self.status.set("Angkat kartu pelanggan sebelum meninggalkan Card Topup.")
            key = "topup"
        if self.current_page == "test" and key != "test":
            self._stop_card_test()
        if self.current_page in ("dashboard", "topup") and key not in ("dashboard", "topup"):
            self._stop_customer_watch()
        if key == "topup" and (not self._session_ready() or self.wallet is None):
            key = "dashboard"
            self.status.set("Tempelkan kartu pelanggan untuk membuka Card Topup.")
        self.pages[key].lift()
        headers = {
            "test": ("TEST CARD — READ ONLY", "Reader detection test", "Detects a card automatically. It never changes Wallet Data or writes the card."),
            "dashboard": ("TOPUP — OPERATOR CONSOLE", "Topup overview", "Complete the required session steps before changing Wallet Data."),
            "topup": ("CARD TOPUP — VERIFIED WRITE", "Manage customer card", "Every change requires an active master session and final read-back verification."),
            "history": ("TRANSACTIONS — DATABASE", "Transaction history", "Search recorded Topup operations by customer, card, phone, or date."),
            "logs": ("ACTIVITY LOGS — READ ONLY", "Application activity", "Database events are shown without NFC keys or raw card blocks."),
        }
        kicker, title, description = headers[key]
        self.current_page = key
        self.page_kicker.set(kicker)
        self.page_title.set(title)
        self.page_description.set(description)
        for name, button in self.nav_buttons.items():
            button.configure(bg="#2b2741" if name == key else CHROME, fg="#e7e5fe" if name == key else "#cfd3e5")
        if key == "test":
            self._start_card_test()
        elif key in ("dashboard", "topup"):
            self._start_customer_watch()
        elif key == "history":
            self.refresh_history()
        elif key == "logs":
            self.refresh_logs()
        self._refresh_access()

    def _run(self, working: str, task: Callable[[], Any], done: Callable[[Any], None] | None = None) -> None:
        if self.busy:
            self.status.set("Another operation is still running.")
            return
        self.busy = True
        self.status.set(working)
        self._refresh_access()

        def worker() -> None:
            try:
                result = task()
            except Exception as error:
                self.after(0, lambda caught=error: self._finish_error(caught))
                return
            self.after(0, lambda value=result: self._finish_success(value, done))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_success(self, result: Any, done: Callable[[Any], None] | None) -> None:
        self.busy = False
        if done:
            done(result)
        self._refresh_access()

    def _finish_error(self, error: Exception) -> None:
        self.busy = False
        self.status.set(str(error))
        self._refresh_access()
        if not self.headless:
            messagebox.showerror("SmartDispenser Topup", str(error), parent=self)

    def _load_saved_database(self) -> None:
        try:
            config = load_config()
        except Exception as error:
            self.database_state.set("DATABASE: CONFIG ERROR")
            self.badges["database"].configure(fg=RED)
            self.status.set(str(error))
            self.after(200, self.discover_board)
            return
        if not config:
            self.database_state.set("DATABASE: NOT CONFIGURED")
            self.badges["database"].configure(fg=YELLOW)
            self.status.set("Configure the Database in Settings.")
            self.after(200, self.discover_board)
            return

        candidate = MySqlStore(config)

        def verify() -> MySqlStore:
            candidate.setting("last_backup_day")
            return candidate

        def ready(store: MySqlStore) -> None:
            self.store = store
            self.database_state.set("DATABASE: READY")
            self.badges["database"].configure(fg=GREEN)
            self.status.set("Database ready. Log in as operator.")
            self.after(200, self.discover_board)
            self.after(5000, self.backup_if_due)

        self._run("Checking Database...", verify, ready)

    def discover_board(self) -> None:
        self.board_state.set("BOARD: SEARCHING")
        self.badges["board"].configure(fg=YELLOW)
        self._run("Searching for Topup Board...", self._find_topup_board, lambda result: self._use_board(*result))

    def connect_board_manual(self) -> None:
        port = simpledialog.askstring("Board", "Device Port (example: COM3):", parent=self)
        if not port:
            return

        def connect() -> tuple[SerialReaderAdapter, str]:
            reader = SerialReaderAdapter(port.strip().upper())
            reader.connect()
            return reader, port.strip().upper()

        self._run("Connecting to Board...", connect, lambda result: self._use_board(*result))

    def _use_board(self, reader: SerialReaderAdapter, port: str) -> None:
        if isinstance(self.reader, SerialReaderAdapter):
            self.reader.close()
        self.reader = reader
        self.wallet = None
        self.current_customer = None
        self.board_state.set(f"BOARD: {port}")
        self.badges["board"].configure(fg=GREEN)
        self.session_state.set("SESSION: LOCKED")
        self.badges["session"].configure(fg=MUTED)
        self.status.set("Topup Board connected. Log in and activate the master session.")
        self._render_wallet()

    def simulation_mode(self) -> None:
        if isinstance(self.reader, SerialReaderAdapter):
            self.reader.close()
        simulated = SimulationReader()
        simulated.present()
        self.reader = simulated
        self.wallet = None
        self.current_customer = None
        self.board_state.set("BOARD: SIMULATION")
        self.badges["board"].configure(fg=YELLOW)
        self.session_state.set("SESSION: LOCKED")
        self.badges["session"].configure(fg=MUTED)
        self.status.set("Simulation active. No physical card will be changed.")
        self._render_wallet()
        self._refresh_access()

    def configure_database(self) -> None:
        def ready(store: MySqlStore) -> None:
            self.store = store
            self.database_state.set("DATABASE: READY")
            self.badges["database"].configure(fg=GREEN)
            self.status.set("Database and operator PIN are ready.")

        self._run("Reloading local Database configuration...", self._provision_from_file, ready)

    def login(self) -> None:
        if not self.store:
            self._finish_error(TopupError("Database is not ready"))
            return
        pin = simpledialog.askstring("Operator Login", "PIN:", show="*", parent=self)
        if pin is None:
            return

        def accepted(operator_id: int) -> None:
            self.operator_id = operator_id
            self.operator_state.set("OPERATOR: ACTIVE")
            self.badges["operator"].configure(fg=GREEN)
            self.status.set("Operator login successful. Tap the master card.")

        self._run("Verifying operator...", lambda: self.store.login(pin), accepted)

    def enroll_master(self) -> None:
        if not self.reader:
            self._finish_error(TopupError("Board is not connected"))
            return
        if not messagebox.askyesno("Register Master", "Keep the new master card on the NFC Reader for 10 seconds. Continue?", parent=self):
            return
        self._run("Registering master card — keep it still for 10 seconds...", self.reader.enroll_master, lambda _: self.status.set("Master card registered. Remove it before activation."))

    def unlock_master(self) -> None:
        if not self.reader or self.operator_id is None:
            self._finish_error(TopupError("Board and operator login are required"))
            return

        def active(_: Any) -> None:
            self.session_state.set("SESSION: ACTIVE")
            self.badges["session"].configure(fg=GREEN)
            self.status.set("Master accepted. Remove it, then read a customer card.")

        self._run("Checking master card...", self.reader.unlock_master, active)

    def _session_ready(self) -> bool:
        return bool(self.reader and self.operator_id is not None and getattr(self.reader, "master_unlocked", False))

    def _refresh_access(self) -> None:
        database_ready = self.store is not None
        board_ready = self.reader is not None
        operator_ready = self.operator_id is not None
        session_ready = self._session_ready()
        wallet_ready = self.wallet is not None and session_ready
        state = "disabled" if self.busy else "normal"
        self.session_button.configure(state=state if board_ready and operator_ready else "disabled")
        for button in self.mutation_buttons:
            button.configure(state=state if wallet_ready and database_ready else "disabled")
        for name, button in self.nav_buttons.items():
            if wallet_ready and self.current_page == "topup" and name != "topup":
                button.configure(state="disabled")
            elif name == "topup":
                button.configure(state=state if wallet_ready else "disabled")
            else:
                button.configure(state=state)
        checks = (
            ("1. Database ready", database_ready),
            ("2. Topup Board connected", board_ready),
            ("3. Master card verified", session_ready),
        )
        for label, (text, complete) in zip(self.dashboard_steps, checks):
            label.configure(text=("✓  " if complete else "○  ") + text, fg=GREEN if complete else MUTED)

    def _schedule_quota_refresh(self, delay: int = 15000) -> None:
        if self.quota_refresh_after:
            try:
                self.after_cancel(self.quota_refresh_after)
            except Exception:
                pass
        self.quota_refresh_after = self.after(delay, self._refresh_quota_overview)

    def _refresh_quota_overview(self) -> None:
        self.quota_refresh_after = None
        if not self.store:
            self._schedule_quota_refresh()
            return
        if self.quota_refresh_in_flight:
            self._schedule_quota_refresh(500)
            return
        self.quota_refresh_in_flight = True

        def load() -> None:
            try:
                result, error = self.store.quota_overview(), None
            except Exception as caught:
                result, error = None, caught
            self.after(0, lambda: self._quota_overview_loaded(result, error))

        threading.Thread(target=load, daemon=True).start()

    def _quota_overview_loaded(self, result: dict[str, Any] | None, error: Exception | None) -> None:
        self.quota_refresh_in_flight = False
        if result is not None:
            result["loading"] = False
            result["error"] = ""
            self.quota_overview_data = result
        elif error is not None:
            self.quota_overview_data = dict(self.quota_overview_data, loading=False, error=str(error))
        self._schedule_quota_refresh()

    def save_distribution_quota(self, value: Any) -> None:
        if not self.store or not self._session_ready():
            self._finish_error(TopupError("Database dan sesi master aktif diperlukan"))
            return

        def saved(liters: int) -> None:
            self.status.set(f"Maksimal kuota distribusi tersimpan: {liters} L.")
            self._schedule_quota_refresh(0)

        self._run(
            "Menyimpan maksimal kuota distribusi...",
            lambda: self.store.set_distribution_quota(value),
            saved,
        )

    def _start_customer_watch(self) -> None:
        if self.customer_watch_active:
            self._schedule_customer_watch(80)
            return
        self.customer_watch_active = True
        self.customer_watch_started = False
        self.customer_watch_probe_due = 0.0
        if self.reader:
            self.reader.clear_events()
        if hasattr(self, "customer_watch_label"):
            self.customer_watch_label.configure(text="○  Waiting for customer card", foreground=BLUE)
        self.status.set("Tempelkan kartu pelanggan. Card Reference akan dibaca otomatis.")
        self._schedule_customer_watch(80)

    def _stop_customer_watch(self) -> None:
        self.customer_watch_active = False
        self.customer_watch_started = False
        if self.customer_watch_after:
            self.after_cancel(self.customer_watch_after)
            self.customer_watch_after = None
        if self.reader:
            threading.Thread(target=self._stop_customer_watch_on_board, daemon=True).start()

    def _stop_customer_watch_on_board(self) -> None:
        try:
            if self.reader:
                self.reader.stop_card_watch()
        except Exception:
            pass

    def _schedule_customer_watch(self, delay: int = 350) -> None:
        if not self.customer_watch_active:
            return
        if self.customer_watch_after:
            self.after_cancel(self.customer_watch_after)
        self.customer_watch_after = self.after(delay, self._poll_customer_watch)

    def _poll_customer_watch(self) -> None:
        self.customer_watch_after = None
        if not self.customer_watch_active or self.customer_watch_polling:
            return
        if self.busy or not self._session_ready() or not self.store or not self.reader:
            self._schedule_customer_watch(400)
            return
        if not self.customer_watch_started:
            self.customer_watch_polling = True

            def start() -> None:
                try:
                    self.reader.start_card_watch()
                    error = None
                except Exception as caught:
                    error = caught
                self.after(0, lambda: self._customer_watch_started(error))

            threading.Thread(target=start, daemon=True).start()
            return
        event = self.reader.next_event()
        while event is not None:
            if event.get("scope") == "card" and event.get("state") == "detected":
                self.customer_watch_polling = True

                def read() -> None:
                    try:
                        wallet, error = self._read_customer_wallet(), None
                    except Exception as caught:
                        wallet, error = None, caught
                    self.after(0, lambda: self._customer_watch_result(wallet, error))

                threading.Thread(target=read, daemon=True).start()
                return
            if event.get("scope") == "card" and event.get("state") == "removed":
                self._customer_card_removed()
            event = self.reader.next_event()
        # Fallback read-only: bila EVT detected/removed terlewat, pembacaan
        # Wallet tetap menemukan kartu maupun memastikan kartu sudah dilepas.
        # Interval dibatasi agar Reader tidak dibanjiri permintaan.
        now = time.monotonic()
        if now >= self.customer_watch_probe_due:
            self.customer_watch_polling = True
            self.customer_watch_probe_due = now + 0.45
            record_read = self.wallet is None

            def probe() -> None:
                try:
                    wallet, error = self._read_customer_wallet(record=record_read), None
                except Exception as caught:
                    wallet, error = None, caught
                self.after(0, lambda: self._customer_watch_result(wallet, error))

            threading.Thread(target=probe, daemon=True).start()
            return
        self._schedule_customer_watch(75)

    def _read_customer_wallet(self, record: bool = True) -> Wallet:
        if not self.reader or not self.store:
            raise TopupError("Reader atau Database tidak tersedia")
        wallet = self.reader.read_wallet()
        if record:
            self.store.sync_wallet_state(wallet)
            self.store.audit(self.operator_id, "wallet_read", wallet.card_reference, "verified wallet read by Card Reference")
        return wallet

    def _customer_card_removed(self) -> None:
        had_wallet = self.wallet is not None
        self.wallet = None
        self.current_customer = None
        self._render_wallet()
        self.status.set("Kartu dilepas. Kembali ke Home dan menunggu kartu berikutnya.")
        if hasattr(self, "customer_watch_label"):
            self.customer_watch_label.configure(text="○  Waiting for customer card", foreground=BLUE)
        if had_wallet and self.current_page == "topup":
            self.show_page("dashboard")

    def _customer_watch_started(self, error: Exception | None) -> None:
        self.customer_watch_polling = False
        if not self.customer_watch_active:
            return
        if error is not None:
            # Jangan membuat Overview bergantung mutlak pada satu ACK event
            # stream. Fallback READ di bawah tetap dapat menemukan Wallet
            # pelanggan secara read-only dan non-blocking.
            self.customer_watch_started = True
            self.customer_watch_probe_due = 0.0
            self.status.set(f"Event kartu tidak terkonfirmasi; memakai pembacaan langsung: {error}")
            self._schedule_customer_watch(80)
            return
        self.customer_watch_started = True
        self.customer_watch_probe_due = 0.0
        self._schedule_customer_watch(80)

    def _customer_watch_result(self, wallet: Wallet | None, error: Exception | None) -> None:
        self.customer_watch_polling = False
        if not self.customer_watch_active:
            return
        if error is not None:
            message = str(error).lower()
            waiting = any(value in message for value in ("card absent", "tidak ada kartu", "customer card required"))
            if waiting and self.wallet is not None:
                self._customer_card_removed()
                return
            if not waiting:
                self.status.set(f"Kartu ditolak: {error}")
                if hasattr(self, "customer_watch_label"):
                    self.customer_watch_label.configure(text="!  Valid personalized card required", foreground=YELLOW)
            self._schedule_customer_watch(450)
            return
        if wallet is None:
            self._schedule_customer_watch()
            return
        if self.wallet is not None and wallet.card_reference == self.wallet.card_reference:
            # Presence confirmation only; do not duplicate Database audit or
            # reopen/rerender Card Topup while the same card remains present.
            self.wallet = wallet
            self._schedule_customer_watch(75)
            return
        self.wallet = wallet
        self.current_customer = None
        self.status.set(f"{wallet.card_reference} terbaca. Membuka Card Topup...")
        self._render_wallet()
        self.refresh_logs()
        self._schedule_quota_refresh(0)
        self.show_page("topup")

    def read_card(self) -> None:
        if not self._session_ready() or not self.store or not self.reader:
            self._finish_error(TopupError("Database, operator, Board, and master session are required"))
            return

        def read() -> Wallet:
            wallet = self.reader.read_wallet()
            self.store.sync_wallet_state(wallet)
            self.store.audit(self.operator_id, "wallet_read", wallet.card_reference, "verified wallet read by Card Reference")
            return wallet

        def ready(result: Wallet) -> None:
            self.wallet, self.current_customer = result, None
            self.status.set("Card read successfully.")
            self._render_wallet()
            self.refresh_logs()
            self._schedule_quota_refresh(0)
            self.show_page("topup")

        self._run("Reading and verifying card...", read, ready)

    def _render_wallet(self) -> None:
        if not self.wallet:
            self.card_title.set("Waiting for card")
            self.card_detail.set("Tempelkan kartu pelanggan; Card Reference dibaca otomatis.")
            self.owner_title.set("Card Reference: —")
            self.owner_detail.set("Belum ada kartu pelanggan.")
            self.balance_text.set("— L")
            self.permission_text.set("Belum diperiksa")
            self.schedule_text.set("Belum diperiksa")
            self.usage_text.set("Terpakai — L · Cadangan — L")
            self._refresh_access()
            return
        wallet = self.wallet
        self.card_title.set(f"Wallet Data verified · Revision {wallet.revision}")
        self.card_detail.set(f"Card Reference: {wallet.card_reference} · Wallet V2 verified")
        self.balance_text.set(f"{wallet.balance} L")
        self.permission_text.set("AKTIF" if wallet.active else "NONAKTIF")
        self.schedule_text.set(SCHEDULES.get(wallet.schedule, "Unknown"))
        self.usage_text.set(f"Terpakai hari ini {wallet.used_today} L · Cadangan {wallet.reserved} L")
        self.owner_title.set(f"Card Reference: {wallet.card_reference}")
        self.owner_detail.set("ID pencatatan kartu untuk jadwal pagi, siang, dan sore.")
        self._refresh_access()

    def toggle_active(self) -> None:
        if self.wallet:
            self.change("set_active", not self.wallet.active)

    def change(self, action: str, value: Any) -> None:
        if not self.store or not self.reader or not self.wallet or not self._session_ready():
            self._finish_error(TopupError("Read a card in an active master session first"))
            return
        before = self.wallet
        labels = {
            "balance_adjust": f"adjust balance by {int(value):+d} L",
            "set_active": "change card status",
            "set_schedule": f"set schedule to {SCHEDULES.get(int(value), 'Unknown')}",
            "release_reserved": f"release {before.reserved} L reserved balance",
        }
        if not messagebox.askyesno("Confirm Topup", f"Confirm {labels[action]}?\n\nBalance before: {before.balance} L", parent=self):
            return
        self.change_confirmed(action, value)

    def change_confirmed(self, action: str, value: Any) -> None:
        if not self.store or not self.reader or not self.wallet or not self._session_ready():
            self._finish_error(TopupError("Read a card in an active master session first"))
            return
        before = self.wallet
        operation_id = new_request_id()

        def mutate() -> Wallet:
            self.store.validate_distribution_quota(before, action, value)
            expected = self.reader.mutate(operation_id, action, value)
            verified = self.reader.read_wallet()
            if verified != expected:
                raise TopupError("Final read-back does not match; transaction requires inspection")
            self.store.transaction(self.operator_id, operation_id, action, before, verified, value)
            self.store.audit(self.operator_id, action, verified.card_reference, f"balance {before.balance}->{verified.balance}; revision {before.revision}->{verified.revision}")
            return verified

        def complete(wallet: Wallet) -> None:
            self.wallet = wallet
            self.status.set("SUCCESS — card write and read-back verified.")
            self._render_wallet()
            self.refresh_history()
            self.refresh_logs()
            self._schedule_quota_refresh(0)
            self.after(3000, lambda: self.status.set("Ready for the next operation."))

        self._run("Writing card and verifying read-back...", mutate, complete)

    def _schedule_history_refresh(self, *_: Any) -> None:
        if self.history_after:
            self.after_cancel(self.history_after)
        self.history_after = self.after(300, self.refresh_history)

    def refresh_history(self) -> None:
        if not self.store or not hasattr(self, "history_table"):
            return
        query = self.history_query.get()

        def loaded(rows: list[dict[str, Any]]) -> None:
            for item in self.history_table.get_children():
                self.history_table.delete(item)
            for row in rows:
                self.history_table.insert("", "end", values=(
                    row["created_at"], row["card_reference"], row["action"],
                    row["amount_liter"] if row["amount_liter"] is not None else "—",
                    row["balance_before"] if row["balance_before"] is not None else "—",
                    row["balance_after"] if row["balance_after"] is not None else "—",
                ))
            self.status.set(f"{len(rows)} transaction(s) displayed.")

        self._run("Loading transactions...", lambda: self.store.history(query), loaded)

    def refresh_logs(self) -> None:
        if not self.store or not hasattr(self, "log_table"):
            return

        def loaded(rows: list[dict[str, Any]]) -> None:
            for item in self.log_table.get_children():
                self.log_table.delete(item)
            for row in rows:
                self.log_table.insert("", "end", values=(row["created_at"], row["event_type"], row["detail"] or "—"))

        self._run("Loading Activity Logs...", lambda: self.store.recent_audit(100), loaded)

    def backup(self) -> None:
        if not self.store:
            self._finish_error(TopupError("Database is not ready"))
            return
        self._run("Backing up Database...", lambda: backup_mysql(self.store.config), lambda path: self.status.set(f"Backup created: {path.name}"))

    def backup_if_due(self) -> None:
        if not self.store:
            return

        def due() -> str | None:
            today = date.today().isoformat()
            if self.store.setting("last_backup_day") == today:
                return None
            backup_mysql(self.store.config)
            self.store.set_setting("last_backup_day", today)
            return today

        def complete(result: str | None, error: Exception | None = None) -> None:
            if error:
                self.status.set(str(error))
            if result:
                self.status.set("Daily Database backup created.")
            self.after(60 * 60 * 1000, self.backup_if_due)

        def worker() -> None:
            try:
                result = due()
            except Exception as error:
                self.after(0, lambda caught=error: complete(None, caught))
                return
            self.after(0, lambda: complete(result))

        threading.Thread(target=worker, daemon=True).start()

    def on_close(self) -> None:
        for timer_name in ("startup_master_event_after", "startup_master_feedback_after"):
            timer = getattr(self, timer_name, None)
            if timer:
                try:
                    self.after_cancel(timer)
                except Exception:
                    pass
                setattr(self, timer_name, None)
        if self.quota_refresh_after:
            try:
                self.after_cancel(self.quota_refresh_after)
            except Exception:
                pass
            self.quota_refresh_after = None
        self._stop_card_test(send_command=False)
        self.customer_watch_active = False
        if self.customer_watch_after:
            try:
                self.after_cancel(self.customer_watch_after)
            except Exception:
                pass
            self.customer_watch_after = None
        if self.card_test_animation_after:
            try:
                self.after_cancel(self.card_test_animation_after)
            except Exception:
                pass
            self.card_test_animation_after = None
        if isinstance(self.reader, SerialReaderAdapter):
            try:
                self.reader.stop_card_test()
            except Exception:
                pass
            try:
                self.reader.stop_card_watch()
            except Exception:
                pass
            try:
                self.reader.lock_session()
            except Exception:
                pass
            self.reader.close()
        self.destroy()


if __name__ == "__main__":
    TopupConsole().mainloop()
