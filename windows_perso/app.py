from __future__ import annotations

import base64
import ctypes
import os
import json
import re
import time
import tkinter as tk
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import mysql.connector  # type: ignore
from tkinter import messagebox, ttk

from perso_core import PersoSimulator, ProtocolError, decode_frames_resilient, encode_frame, encode_stm32_compact_commit, is_perso_ready, request


WIB = timezone(timedelta(hours=7), name="WIB")
MACHINE_CONFIG_PATH = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "SmartDispenser" / "Perso" / "config.json"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def unprotect_machine_secret(value: str) -> str:
    """Decrypt an installer credential protected for this Windows machine."""
    if os.name != "nt":
        raise RuntimeError("Machine Database credentials require Windows.")
    encrypted = base64.b64decode(value)
    raw = ctypes.create_string_buffer(encrypted)
    source = _DataBlob(len(encrypted), ctypes.cast(raw, ctypes.POINTER(ctypes.c_byte)))
    target = _DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)
    ):
        raise RuntimeError("Windows could not decrypt the Database configuration.")
    try:
        return ctypes.string_at(target.pbData, target.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(target.pbData)


def read_machine_database_config(path: Path = MACHINE_CONFIG_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = ("host", "port", "app_user", "app_secret")
    if any(not raw.get(key) for key in required):
        raise RuntimeError("Machine Database configuration is incomplete.")
    return {
        "host": str(raw["host"]),
        "port": int(raw["port"]),
        "user": str(raw["app_user"]),
        "password": unprotect_machine_secret(str(raw["app_secret"])),
    }


def format_wib_datetime(value: Any, fallback: str = "—") -> str:
    """Format stored timestamps consistently without changing Database values."""
    if value is None:
        return fallback
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text or text in {"-", "—"}:
            return fallback
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=WIB)
    else:
        parsed = parsed.astimezone(WIB)
    return parsed.strftime("%H:%M WIB - %d/%m/%Y")


def validate_customer_fields(nik: str, family_card_number: str, full_name: str, phone: str = "") -> list[str]:
    """Return operator-facing validation errors without touching the database."""
    errors: list[str] = []
    if not re.fullmatch(r"\d{16}", nik.strip()):
        errors.append("NIK must contain exactly 16 digits.")
    if not re.fullmatch(r"\d{16}", family_card_number.strip()):
        errors.append("Family Card (KK) number must contain exactly 16 digits.")
    if not full_name.strip():
        errors.append("Full name is required.")
    if phone.strip() and not re.fullmatch(r"[+0-9 ()-]{6,32}", phone.strip()):
        errors.append("Phone number contains unsupported characters.")
    return errors


def mask_identity_number(value: str) -> str:
    value = value.strip()
    return ("•" * max(0, len(value) - 4) + value[-4:]) if value else "—"


def customer_field_is_readonly(field: str, has_active_card: bool) -> bool:
    """Protect identity fields once they are bound to an active card."""
    return field == "number" or (has_active_card and field in {"nik", "kk", "name"})


def read_user_environment(name: str) -> str | None:
    """Read a current-user variable even when Explorer has not refreshed it."""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            return value if isinstance(value, str) and value else None
    except OSError:
        return None


class SerialTransport:
    def __init__(self, port: str):
        try:
            import serial  # type: ignore
        except ImportError as error:
            raise RuntimeError("pyserial belum terpasang") from error
        # Membuka COM pada ESP32 dapat memunculkan teks boot ROM. DTR/RTS
        # dimatikan sebelum open untuk tidak memicu reset otomatis board.
        self.serial = serial.Serial()
        self.serial.port = port
        self.serial.baudrate = 115200
        self.serial.timeout = 0
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.open()
        self.buffer = bytearray()
        self.stm32_compact_mode = False

    def send(self, message: dict) -> None:
        compact = {
            "status_request": b"S", "session_lock": b"L", "cancel": b"X",
            "card_probe": b"C", "technical_scan": b"T", "card_quality_test": b"Q",
            "card_test_start": b"Y", "card_test_stop": b"Z",
            "owner_lookup_start": b"U", "owner_lookup_stop": b"V",
            "register_master_begin": b"E", "register_master_commit": b"R",
            "reset_master_begin": b"B", "reset_master_commit": b"D",
            "perso_arm": b"A", "perso_commit": b"P", "perso_remove": b"W",
        }
        command = message.get("type")
        if self.stm32_compact_mode and command == "perso_commit" and "card_reference" in message:
            # The CH340 -> STM32 UART path reliably handles the existing
            # two-byte compact commands, but can drop bytes from a longer
            # burst. Pace this one parameterized command so its eight hex
            # digits arrive intact before the terminating newline.
            for value in encode_stm32_compact_commit(message["card_reference"]):
                self.serial.write(bytes((value,)))
                self.serial.flush()
                time.sleep(0.02)
            return
        if self.stm32_compact_mode and command in compact and len(message) == 2:
            self.serial.write(b"!" + compact[command])
            return
        # ESP32 consumes the framed request. STM32 ignores a malformed framed
        # request, then handles the reset-delimited compact status handshake.
        self.serial.write(encode_frame(message))
        if command == "status_request":
            self.serial.flush()
            time.sleep(0.08)
            self.serial.write(b"!S")

    def poll(self) -> list[dict]:
        waiting = self.serial.in_waiting
        if waiting:
            self.buffer.extend(self.serial.read(waiting))
        events = decode_frames_resilient(self.buffer)
        if any(event.get("transport") == "stm32_char" for event in events):
            self.stm32_compact_mode = True
        return events

    def close(self) -> None:
        self.serial.close()


class PersoApp(tk.Tk):
    STEP_LABELS = [("precheck", "Check card"), ("write_protection", "Protection"), ("write_wallet", "Wallet"), ("verify_wallet", "Verification")]
    PRECHECK_PROCESS_STEPS = (
        "Master session active",
        "New card detected",
        "Background sector scan started",
        "All 16 sectors scanned",
        "Card quality test started",
        "Card quality passed (10/10)",
        "Wallet Data availability verified",
        "Card Identity availability verified",
        "Final Wallet Data and Card Identity check started",
        "Final Wallet Data and Card Identity check passed",
    )
    PERSONALIZATION_PROCESS_STEPS = (
        "Database reservation confirmed",
        "Sector 2 protection prepared",
        "Wallet Data written or preserved",
        "Card Number and security data written to Card Identity",
        "Wallet Data and Card Identity read-back verified",
        "Card personalization completed",
        "Card removed — process reset",
    )

    def __init__(self, headless: bool = False) -> None:
        super().__init__()
        self.headless = headless
        if self.headless:
            self.withdraw()
        self.title("SmartDispenser — Customer Personalization Console")
        self.minsize(1060, 720)
        self.geometry("1120x780")
        # Di Windows, buka langsung dalam keadaan maximize (setara klik
        # tombol kotak di title bar), namun pengguna tetap dapat restore.
        if not self.headless:
            self.after(0, self.bring_to_front)
        self.configure(bg="#20272b")
        local_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        self.parsed_serial_log_path = local_data / "SmartDispenser" / "logs" / "perso_customers_serial_parsed.jsonl"
        self.transport: SerialTransport | None = None
        # Status ini ditetapkan hanya setelah balasan handshake Perso yang
        # benar diterima. Ia mencegah badge dashboard kembali ke "belum
        # terhubung" selama transisi splash -> dashboard.
        self.verified_port: str | None = None
        self.simulator = PersoSimulator()
        self.simulation = tk.BooleanVar(value=False)
        self.port = tk.StringVar(value="COM3")
        self.status = tk.StringVar(value="Starting application")
        # Tk.Tk already uses ``master`` internally; do not replace it with
        # a StringVar or Tkinter fails before the window is created.
        self.master_status = tk.StringVar(value="Not registered")
        self.master_hint = tk.StringVar(value="Master registration required")
        self.session = tk.StringVar(value="Locked")
        self.card = tk.StringVar(value="No card detected")
        self.operator_guide_title = tk.StringVar(value="Preparing operator guide")
        self.operator_guide_detail = tk.StringVar(value="Waiting for board status.")
        self.board_operation = "idle"
        self.card_precheck = ""
        self.technical_scan_active = False
        self.debug_readable_blocks = 0
        self.debug_denied_blocks = 0
        self.debug_wallet_states: list[str] = []
        self.wallet_slot_state = ""
        self.wallet_slot_action = ""
        self.wallet_quality_ok: bool | None = None
        self.final_check_seconds = 0
        self.final_check_zero_ticks = 0
        self.debug_card_present = False
        self.final_result_hold_until = 0.0
        self.final_result_token = 0
        self.technical_reset_token = 0
        self.technical_stage_queue: list[tuple[int, bool, Any | None]] = []
        self.technical_stage_active = False
        self.technical_stage_after: str | None = None
        self.technical_stage_generation = 0
        self.technical_stage_highest = 0
        self.personalization_active_step = 0
        self.personalization_completed = False
        self.debug_detail_visible = False
        self.coverage_active = False
        self.coverage_index = 0
        self.coverage_scores: list[tuple[int, int]] = []
        self.coverage_positions = ("TENGAH", "ATAS", "BAWAH", "KIRI", "KANAN")
        self.step_state: dict[str, tk.Label] = {}
        self.hold_after: str | None = None
        self.hold_seconds = 0
        self.hold_command: str | None = None
        self.dashboard_ready = False
        self.startup_phase = "database_verify"
        self.startup_spinner_angle = 0
        self.loading_is_done = False
        self.session_open_feedback_pending = False
        self.session_gate_card_present = False
        self.session_gate_recovery_after: str | None = None
        self.startup_candidates: list[str] = []
        self.startup_candidate_index = 0
        self.startup_wait_port: str | None = None
        self.startup_wait_after: str | None = None
        self.session_lock_attempts = 0
        self.session_lock_after: str | None = None
        self.startup_skip_visible = False
        self.background_scan = False
        self.connection_spinner_angle = 0
        self.connection_spinner_running = False
        self.last_nfc_ready: bool | None = None
        self.last_master_registered: bool | None = None
        self.last_session_open: bool | None = None
        self.last_stm_event_at = 0.0
        self.last_stm_status_request_at = 0.0
        self.last_card_probe_at = 0.0
        self.liveness_phase = 0
        self.debug_liveness = tk.StringVar(value="◌ APP  |  ○ BOARD")
        self.card_test_status = tk.StringVar(value="Reader test is ready. Tap any card, including the master card.")
        self.card_test_count = tk.StringVar(value="0 card detections")
        self.card_test_active = False
        self.card_test_confirmed = False
        self.card_test_start_attempts = 0
        self.card_test_start_after: str | None = None
        self.card_test_detection_count = 0
        self.owner_lookup_status = tk.StringVar(value="Reader is ready. Tap a personalized card.")
        self.owner_lookup_reference = tk.StringVar(value="Card Number: —")
        self.owner_lookup_customer = tk.StringVar(value="Owner: —")
        self.owner_lookup_details = tk.StringVar(value="No card checked yet.")
        self.owner_lookup_record: dict[str, str] = {}
        self.owner_lookup_active = False
        self.owner_lookup_confirmed = False
        self.owner_lookup_start_attempts = 0
        self.owner_lookup_start_after: str | None = None
        self.master_tap_after: str | None = None
        self.master_gate: tk.Toplevel | None = None
        self.master_gate_card_label: tk.Label | None = None
        self.master_gate_button: tk.Button | None = None
        # Master registration is deliberately two-stage: card presence first,
        # then the 10-second hold. A press alone must never arm enrollment.
        self.master_registration_card_present = False
        # Recent Logs dapat dibalik tanpa mengubah urutan audit di database.
        # Default operator: kejadian terbaru berada paling atas.
        self.log_descending = True
        self.log_entries: list[tuple[str, str, str, str]] = []
        self.selected_customer_id: int | None = None
        self.selected_customer_number = tk.StringVar(value="No customer selected")
        self.selected_customer_name = tk.StringVar(value="Select a registered customer before scanning a card.")
        self.selected_customer_card_status = tk.StringVar(value="Card status: not checked")
        self.customer_search = tk.StringVar()
        self.customer_search_after: str | None = None
        self.customer_form_number = tk.StringVar(value="Generated when saved")
        self.customer_form_nik = tk.StringVar()
        self.customer_form_kk = tk.StringVar()
        self.customer_form_name = tk.StringVar()
        self.customer_form_phone = tk.StringVar()
        self.customer_form_address = tk.StringVar()
        self.customer_form_status = tk.StringVar(value="active")
        self.active_run_id: str | None = None
        self.active_run_customer_id: int | None = None
        self.active_run_card_session: int | None = None
        self.active_card_reference: int | None = None
        # Perso memakai akun MySQL khusus dengan akses terbatas, bukan root.
        # Kredensial berasal dari environment Windows dan tidak ditampilkan
        # di UI, audit, source code, atau EXE.
        machine_database = read_machine_database_config()
        mysql_user = machine_database["user"] if machine_database else read_user_environment("SMARTDISPENSER_MYSQL_USER")
        mysql_password = machine_database["password"] if machine_database else read_user_environment("SMARTDISPENSER_MYSQL_PASSWORD")
        self.database_config = {
            "host": machine_database["host"] if machine_database else "127.0.0.1",
            "port": machine_database["port"] if machine_database else 3306,
            "user": mysql_user,
            "password": mysql_password,
            "database": "Perso_database",
            # Avoid dynamic native authentication DLLs inside a one-file EXE.
            # The pure-Python connector supports MariaDB's native password
            # protocol without relying on a separately loaded plugin module.
            "use_pure": True,
        }
        self.database: Any | None = None
        self.build_loading()
        self.after(40, self.animate_startup_spinner)
        self.after(1000, self.load_local_database)
        self.after(80, self.poll)
        self.after(350, self.tick_liveness)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_loading(self) -> None:
        self.loading_root = tk.Frame(self, bg="#20272b")
        self.loading_root.pack(fill="both", expand=True)
        center = tk.Frame(self.loading_root, bg="#20272b")
        center.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(center, text="SMARTDISPENSER", bg="#20272b", fg="#f2f6f7", font=("Segoe UI", 23, "bold")).pack()
        tk.Label(center, text="PERSONALIZATION CONSOLE", bg="#20272b", fg="#8fa1a7", font=("Segoe UI", 10, "bold")).pack(pady=(2, 24))
        self.loading_canvas = tk.Canvas(center, width=112, height=112, bg="#20272b", highlightthickness=0)
        self.loading_canvas.pack()
        self.loading_title = tk.Label(center, text="Verifying Database", bg="#20272b", fg="#dce6e9", font=("Segoe UI", 13, "bold"))
        self.loading_title.pack(pady=(22, 5))
        self.loading_detail = tk.Label(center, text="Connecting Personalization records to Database...", bg="#20272b", fg="#91a4aa", font=("Segoe UI", 10))
        self.loading_detail.pack()
        self.skip_button = tk.Button(
            self.loading_root,
            text="Continue in background",
            command=self.skip_device_discovery,
            bg="#20272b",
            fg="#81939a",
            activebackground="#2a3539",
            activeforeground="#d2dde0",
            font=("Segoe UI", 9),
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=7,
            cursor="hand2",
        )
        self.loading_master_button = tk.Button(
            self.loading_root,
            text="HOLD 10 SEC • REGISTER MASTER",
            bg="#2f80ed",
            fg="#ffffff",
            activebackground="#4a98ff",
            activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            borderwidth=0,
            padx=18,
            pady=10,
            cursor="hand2",
        )
        self.loading_master_button.bind("<ButtonPress-1>", lambda _event: self.begin_hold("register_master"))
        self.loading_master_button.bind("<ButtonRelease-1>", lambda _event: self.cancel_hold())
        self.set_master_registration_button_enabled(False)

    def bring_to_front(self) -> None:
        """Open restored and maximized instead of leaving the operator at a minimized window."""
        self.deiconify()
        self.state("zoomed")
        self.lift()
        # A brief topmost flag reliably raises a Tk window on Windows, then is
        # removed so the application does not stay over every other program.
        self.attributes("-topmost", True)
        self.focus_force()
        self.after(250, lambda: self.attributes("-topmost", False))

    def set_loading(self, title: str, detail: str, done: bool = False) -> None:
        self.loading_title.configure(text=title)
        self.loading_detail.configure(text=detail)
        self.loading_is_done = done
        if done:
            self.loading_canvas.delete("all")
            self.loading_canvas.create_oval(12, 12, 100, 100, outline="#20d889", width=5)
            self.loading_canvas.create_text(56, 56, text="✓", fill="#20d889", font=("Segoe UI", 42, "bold"))

    def animate_startup_spinner(self) -> None:
        if self.dashboard_ready:
            return
        if not self.loading_is_done:
            self.loading_canvas.delete("all")
            self.loading_canvas.create_oval(12, 12, 100, 100, outline="#34444a", width=5)
            self.loading_canvas.create_arc(12, 12, 100, 100, start=self.startup_spinner_angle, extent=110, style="arc", outline="#2f80ed", width=5)
            self.startup_spinner_angle = (self.startup_spinner_angle + 10) % 360
        self.after(40, self.animate_startup_spinner)

    def load_local_database(self) -> None:
        try:
            if not self.database_config["user"] or not self.database_config["password"]:
                raise RuntimeError("Database credentials are not available in Windows.")
            self.database = mysql.connector.connect(**self.database_config)
            cursor = self.database.cursor()
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS audit_log ("
                "id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                "created_at VARCHAR(40) NOT NULL, event_type VARCHAR(32) NOT NULL, "
                "status VARCHAR(96) NOT NULL, operation VARCHAR(48), card_session BIGINT UNSIGNED)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS customers ("
                "id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                "customer_number VARCHAR(32) NOT NULL UNIQUE, "
                "nik VARCHAR(16) NOT NULL UNIQUE, family_card_number VARCHAR(16) NOT NULL, "
                "full_name VARCHAR(160) NOT NULL, phone VARCHAR(32), address VARCHAR(500), "
                "status VARCHAR(16) NOT NULL DEFAULT 'active', "
                "created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL)"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS personalization_runs ("
                "run_id VARCHAR(36) NOT NULL PRIMARY KEY, customer_id BIGINT UNSIGNED NOT NULL, "
                "device_port VARCHAR(32), card_session BIGINT UNSIGNED, "
                "started_at VARCHAR(40) NOT NULL, completed_at VARCHAR(40), "
                "result VARCHAR(32) NOT NULL, failure_stage VARCHAR(48), failure_code VARCHAR(96), "
                "precheck_result VARCHAR(32), sectors_checked SMALLINT UNSIGNED DEFAULT 0, "
                "readable_blocks SMALLINT UNSIGNED DEFAULT 0, restricted_blocks SMALLINT UNSIGNED DEFAULT 0, "
                "quality_success SMALLINT UNSIGNED, quality_attempts SMALLINT UNSIGNED, "
                "wallet_sector SMALLINT UNSIGNED NOT NULL DEFAULT 2, wallet_block SMALLINT UNSIGNED NOT NULL DEFAULT 8, "
                "wallet_version SMALLINT UNSIGNED NOT NULL DEFAULT 2, "
                "protection_written BOOLEAN NOT NULL DEFAULT FALSE, wallet_written BOOLEAN NOT NULL DEFAULT FALSE, "
                "verification_passed BOOLEAN NOT NULL DEFAULT FALSE, "
                "CONSTRAINT fk_runs_customer FOREIGN KEY (customer_id) REFERENCES customers(id))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS customer_cards ("
                "id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                "customer_id BIGINT UNSIGNED NOT NULL, personalization_run_id VARCHAR(36) NOT NULL UNIQUE, "
                "card_reference VARCHAR(96), card_session BIGINT UNSIGNED, status VARCHAR(24) NOT NULL DEFAULT 'active', "
                "wallet_version SMALLINT UNSIGNED NOT NULL DEFAULT 2, wallet_sector SMALLINT UNSIGNED NOT NULL DEFAULT 2, "
                "wallet_block SMALLINT UNSIGNED NOT NULL DEFAULT 8, activated_at VARCHAR(40) NOT NULL, "
                "CONSTRAINT fk_cards_customer FOREIGN KEY (customer_id) REFERENCES customers(id), "
                "CONSTRAINT fk_cards_run FOREIGN KEY (personalization_run_id) REFERENCES personalization_runs(run_id), "
                "INDEX idx_cards_customer_status (customer_id, status))"
            )
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS card_reference_allocations ("
                "card_reference INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
                "personalization_run_id VARCHAR(36) NOT NULL UNIQUE, allocated_at VARCHAR(40) NOT NULL, "
                "CONSTRAINT fk_reference_run FOREIGN KEY (personalization_run_id) REFERENCES personalization_runs(run_id))"
            )
            cursor.execute("SELECT COUNT(*) FROM audit_log")
            cursor.fetchone()
            cursor.close()
            self.database.commit()
        except Exception as error:
            self.set_loading("Database issue", str(error), done=False)
            self.after(1500, self.load_local_database)
            return
        self.set_loading("Database ready", "Personalization activity loaded.", done=True)
        self.after(700, self.start_device_discovery)

    def start_device_discovery(self) -> None:
        if self.dashboard_ready and not self.background_scan:
            return
        first_search = self.startup_phase not in ("device_discovery", "background_discovery")
        self.startup_phase = "background_discovery" if self.dashboard_ready else "device_discovery"
        if first_search:
            self.after(5000, self.offer_skip_device_discovery)
        self.set_device_discovery_message("Searching for NFC device", "Searching USB Serial Port at 115200 baud...")
        self.transport = None
        self.startup_candidates = self.find_candidate_ports()
        self.startup_candidate_index = 0
        self.try_next_device_port()

    def find_candidate_ports(self) -> list[str]:
        try:
            from serial.tools import list_ports  # type: ignore
            ports = list(list_ports.comports())
        except ImportError:
            return []
        usable = []
        for port in ports:
            identity = f"{port.device} {port.description} {port.hwid}".lower()
            if "bluetooth" in identity:
                continue
            usable.append(port)
        # Port USB serial umum didahulukan; semua COM non-Bluetooth tetap
        # dicoba agar board dengan nama driver yang berbeda tetap ditemukan.
        preferred = ("usb serial", "stlink", "stm", "cp210", "ch340", "ftdi", "uart")
        usable.sort(key=lambda item: (not any(word in (item.description or "").lower() for word in preferred), item.device))
        return [item.device for item in usable]

    def try_next_device_port(self) -> None:
        if self.dashboard_ready and not self.background_scan:
            return
        if self.startup_candidate_index >= len(self.startup_candidates):
            self.set_device_discovery_message("Trying to connect to device", "USB Serial Port not found. Retrying...")
            self.after(1000, self.start_device_discovery)
            return
        port = self.startup_candidates[self.startup_candidate_index]
        self.startup_candidate_index += 1
        self.startup_wait_port = port
        self.set_device_discovery_message("Trying to connect to device", f"Verifying {port} at 115200 baud...")
        try:
            self.transport = SerialTransport(port)
            self.transport.send(request("status_request"))
        except Exception:
            self.disconnect()
            self.after(80, self.try_next_device_port)
            return
        self.startup_wait_after = self.after(1300, self.device_verify_timeout)

    def device_verify_timeout(self) -> None:
        self.startup_wait_after = None
        if self.dashboard_ready and not self.background_scan:
            return
        self.disconnect()
        self.after(80, self.try_next_device_port)

    def finish_startup_device(self, port: str) -> None:
        if self.startup_wait_after:
            self.after_cancel(self.startup_wait_after)
            self.startup_wait_after = None
        self.port.set(port)
        self.verified_port = port
        self.background_scan = False
        self.startup_phase = "device_verified"
        self.status.set("Board verified on " + port)
        if self.dashboard_ready:
            self.set_connection_connected(port)
            self.open_master_registration_gate_if_required()
            return
        # Tahap ketiga pada splash: status master berasal dari balasan
        # handshake board yang sama, bukan dari UID kartu atau database PC.
        self.set_loading("Checking master card", "Checking registration status on device...", done=False)
        self.after(900, self.complete_startup_master_check)

    def complete_startup_master_check(self) -> None:
        # A previous EXE may have been terminated while Test Card was active.
        # Always leave that diagnostic mode before asking for master auth;
        # this is cleanup only and does not change Test Card behaviour.
        self.send("card_test_stop")
        self.send("owner_lookup_stop")
        if self.last_master_registered is True:
            if self.last_session_open is True:
                # A previous application process may have left the board
                # unlocked. Every new app launch begins with a fresh physical
                # master-card authorization.
                self.start_session_lock()
            else:
                # Tahap keempat: master telah terdaftar di EEPROM, tetapi
                # operator tetap harus membukakan sesi secara fisik.
                self.prepare_session_open_gate()
        elif self.last_master_registered is False:
            # Jangan masuk ke home page tanpa master. Operator tetap berada
            # pada layar loading yang sama untuk mendaftarkan satu master.
            self.startup_phase = "master_registration"
            self.master_registration_card_present = False
            self.set_master_registration_button_enabled(False)
            self.set_loading("No master card registered", "Tap the master card, then hold the button for 10 seconds.", done=False)
            self.loading_master_button.place(relx=0.5, rely=0.76, anchor="center")
        else:
            self.set_loading("Master status unavailable", "Opening workspace for operator review.", done=True)
            self.after(700, self.show_dashboard)

    def start_session_lock(self) -> None:
        """Lock an inherited board session and actively verify the response."""
        self.startup_phase = "session_lock"
        self.session_lock_attempts = 0
        self.set_loading("Locking previous session", "Preparing fresh master authorization...", done=False)
        self.request_session_lock()

    def request_session_lock(self) -> None:
        if self.startup_phase != "session_lock":
            return
        self.session_lock_attempts += 1
        self.send("session_lock")
        if self.session_lock_after:
            self.after_cancel(self.session_lock_after)
        self.session_lock_after = self.after(800, self.verify_session_locked)

    def verify_session_locked(self) -> None:
        if self.startup_phase != "session_lock":
            return
        # A status reply with session_open:false is equivalent to the explicit
        # session_locked event and is accepted below in handle_event.
        self.send("status_request")
        if self.session_lock_attempts < 3:
            self.session_lock_after = self.after(900, self.request_session_lock)
        else:
            self.set_loading("Waiting for session lock", "Retrying the Board session-lock confirmation...", done=False)
            self.session_lock_after = self.after(1500, self.request_session_lock)

    def complete_session_lock(self) -> None:
        if self.session_lock_after:
            self.after_cancel(self.session_lock_after)
            self.session_lock_after = None
        self.prepare_session_open_gate()

    def prepare_session_open_gate(self) -> None:
        """Recover the reader from a stale page mode before master authorization."""
        self.startup_phase = "session_open"
        self.session_open_feedback_pending = False
        self.session_gate_card_present = False
        self.set_loading("Activate Personalization session", "Tap the master card on the NFC Reader.", done=False)
        self.recover_session_open_reader_mode()

    def recover_session_open_reader_mode(self) -> None:
        """Keep requesting neutral reader mode until the Board opens the session."""
        if self.dashboard_ready or self.startup_phase != "session_open" or self.last_session_open is True:
            self.session_gate_recovery_after = None
            return
        # Compact serial commands can be dropped while the Board is busy. A
        # previous app exit may therefore leave Test Card or Owner Lookup mode
        # active, where a master tap is consumed by that mode instead.
        self.send("card_test_stop")
        self.send("owner_lookup_stop")
        self.send("status_request")
        self.session_gate_recovery_after = self.after(900, self.recover_session_open_reader_mode)

    def show_unverified_session_card_feedback(self) -> None:
        """Explain a detected card that did not unlock the master session."""
        if (self.dashboard_ready or self.startup_phase != "session_open"
                or not self.session_gate_card_present or self.last_session_open is True):
            return
        self.set_loading(
            "Card not verified",
            "This is not the registered master card. Remove it and tap the master card.",
            done=False,
        )

    def show_verified_master_feedback(self) -> None:
        """Keep the successful master result visible before opening the workspace."""
        if self.dashboard_ready or self.startup_phase != "session_open":
            return
        if self.session_gate_recovery_after:
            self.after_cancel(self.session_gate_recovery_after)
            self.session_gate_recovery_after = None
        self.set_loading(
            "Master card verified",
            "Personalization session active. Opening workspace...",
            done=True,
        )
        self.after(1200, self.show_dashboard)

    def on_close(self) -> None:
        """Lock the hardware session before the desktop process exits."""
        if self.session_gate_recovery_after:
            self.after_cancel(self.session_gate_recovery_after)
            self.session_gate_recovery_after = None
        if self.transport and not self.simulation.get():
            try:
                self.transport.send(request("card_test_stop"))
                self.transport.send(request("owner_lookup_stop"))
                self.transport.send(request("session_lock"))
            except OSError:
                pass
        self.disconnect()
        if self.database:
            try:
                self.database.close()
            except Exception:
                pass
        self.destroy()

    def set_device_discovery_message(self, title: str, detail: str) -> None:
        if self.dashboard_ready:
            self.status.set(detail)
            self.set_connection_searching()
        else:
            self.set_loading(title, detail)

    def offer_skip_device_discovery(self) -> None:
        if self.dashboard_ready or self.startup_phase != "device_discovery" or self.startup_skip_visible:
            return
        self.startup_skip_visible = True
        self.skip_button.place(relx=0.5, rely=0.94, anchor="center")

    def skip_device_discovery(self) -> None:
        # Proses scan yang sedang berjalan sengaja dibiarkan aktif. Dashboard
        # terbuka untuk operator, tetapi board dapat ditemukan kapan saja.
        self.background_scan = True
        self.startup_phase = "background_discovery"
        self.status.set("Searching for Board in background")
        self.show_dashboard()

    def show_dashboard(self) -> None:
        if self.dashboard_ready:
            return
        self.dashboard_ready = True
        self.startup_phase = "ready"
        self.loading_root.destroy()
        self.build()
        # The master status is received during the startup handshake, before
        # the dashboard widgets exist. Apply it now that the panel is built.
        if self.last_master_registered is not None:
            self.update_master_ui(bool(self.last_master_registered))
        if self.last_session_open is not None:
            self.update_session_ui(bool(self.last_session_open))
        self.load_recent_logs()
        self.refresh_ports(silent=True)
        if self.verified_port:
            if self.last_nfc_ready is False:
                self.set_connection_nfc_error(self.verified_port)
                self.card.set("NFC board not ready")
                self.set_nfc_controls(False)
            else:
                self.set_connection_connected(self.verified_port)
        else:
            self.set_connection_searching()
        self.open_master_registration_gate_if_required()

    def open_master_registration_gate_if_required(self) -> None:
        """Keep master guidance inline on the home page; do not open a modal."""
        if self.dashboard_ready and self.last_master_registered is False:
            self.master_hint.set("No master — register a master card first")
            self.status.set("Master not registered — operator registration required")
            return
        if not self.dashboard_ready or self.last_master_registered is not False or self.master_gate:
            return
        gate = tk.Toplevel(self)
        self.master_gate = gate
        gate.title("Register master card")
        gate.configure(bg="#20272b")
        gate.resizable(False, False)
        gate.transient(self)
        gate.protocol("WM_DELETE_WINDOW", lambda: None)
        gate.grab_set()
        panel = tk.Frame(gate, bg="#263238", padx=38, pady=34)
        panel.pack(fill="both", expand=True, padx=1, pady=1)
        tk.Label(panel, text="MASTER SETUP", bg="#263238", fg="#f0bd4f", font=("Segoe UI", 11, "bold")).pack()
        tk.Label(panel, text="No master card registered", bg="#263238", fg="#f4f7f8", font=("Segoe UI", 20, "bold")).pack(pady=(12, 6))
        tk.Label(panel, text="Tap one card to become the master.\nThis card is required to activate the Personalization session.", justify="center", bg="#263238", fg="#a8b6ba", font=("Segoe UI", 10)).pack(pady=(0, 16))
        self.master_gate_card_label = tk.Label(panel, text="○  WAITING FOR CARD", bg="#263238", fg="#93a5aa", font=("Segoe UI", 10, "bold"))
        self.master_gate_card_label.pack(pady=(0, 12))
        self.master_gate_button = tk.Button(panel, text="HOLD 10 SEC • REGISTER MASTER", bg="#2f80ed", fg="#ffffff", activebackground="#4a98ff", activeforeground="#ffffff", relief="flat", borderwidth=0, padx=18, pady=11, font=("Segoe UI", 10, "bold"), cursor="hand2")
        self.master_gate_button.pack(fill="x")
        self.master_gate_button.bind("<ButtonPress-1>", lambda _event: self.begin_hold("register_master"))
        self.master_gate_button.bind("<ButtonRelease-1>", lambda _event: self.cancel_hold())
        self.set_master_registration_button_enabled(False)
        gate.geometry("430x300")
        gate.update_idletasks()
        gate.geometry(f"+{self.winfo_rootx() + max(20, (self.winfo_width() - gate.winfo_width()) // 2)}+{self.winfo_rooty() + max(20, (self.winfo_height() - gate.winfo_height()) // 2)}")

    def close_master_registration_gate(self) -> None:
        if self.master_gate:
            self.master_gate.grab_release()
            self.master_gate.destroy()
        self.master_gate = None
        self.master_gate_card_label = None
        self.master_gate_button = None

    def set_master_registration_button_enabled(self, enabled: bool) -> None:
        """Allow master enrollment only while a candidate card is present."""
        widgets = [self.loading_master_button]
        if self.master_gate_button:
            widgets.append(self.master_gate_button)
        for button in widgets:
            button.configure(
                state="normal" if enabled else "disabled",
                bg="#2f80ed" if enabled else "#45555a",
                fg="#ffffff" if enabled else "#9aa9ad",
                activebackground="#4a98ff" if enabled else "#45555a",
                cursor="hand2" if enabled else "arrow",
            )

    def set_connection_searching(self) -> None:
        if not self.dashboard_ready:
            return
        self.connection_badge.configure(text="NOT CONNECTED", fg="#f0bd4f")
        if not self.connection_spinner.winfo_ismapped():
            self.connection_spinner.pack(side="left", padx=(0, 6))
        if not self.connection_spinner_running:
            self.connection_spinner_running = True
            self.after(50, self.animate_connection_spinner)

    def animate_connection_spinner(self) -> None:
        if not self.dashboard_ready or not self.background_scan:
            self.connection_spinner_running = False
            return
        self.connection_spinner.delete("all")
        self.connection_spinner.create_arc(2, 2, 18, 18, start=self.connection_spinner_angle, extent=105, style="arc", outline="#55a7ff", width=2)
        self.connection_spinner_angle = (self.connection_spinner_angle + 16) % 360
        self.after(50, self.animate_connection_spinner)

    def set_connection_connected(self, port: str) -> None:
        self.connection_spinner_running = False
        self.connection_spinner.pack_forget()
        self.connection_badge.configure(text="BOARD: " + port, fg="#23d18b")

    def set_connection_nfc_error(self, port: str) -> None:
        self.connection_spinner_running = False
        self.connection_spinner.pack_forget()
        self.connection_badge.configure(text="BOARD: " + port + " • NFC READER ERROR", fg="#ef5b5b")

    def set_nfc_controls(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button in (self.enroll, self.reset):
            button.configure(state=state)
        self.arm.configure(state="normal" if enabled and bool(self.last_session_open) else "disabled")
        self.commit.configure(state="disabled")

    def set_card_indicator(self, present: bool) -> None:
        if not hasattr(self, "card_lamp"):
            return
        self.card_lamp.itemconfigure(self.card_lamp_dot, fill="#25d284" if present else "#53656b", outline="#25d284" if present else "#71858b")
        self.card_lamp_label.configure(text="CARD DETECTED" if present else "WAITING FOR CARD", fg="#25d284" if present else "#93a5aa")

    def build(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#20272b")
        style.configure("Card.TFrame", background="#263238")
        style.configure("TLabel", background="#20272b", foreground="#d8e0e3", font=("Segoe UI", 10))
        style.configure("Card.TLabel", background="#263238", foreground="#d8e0e3", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#20272b", font=("Segoe UI", 22, "bold"), foreground="#f1f5f6")
        style.configure("Subtitle.TLabel", background="#20272b", foreground="#94a6ad", font=("Segoe UI", 10))
        style.configure("Heading.TLabel", background="#263238", font=("Segoe UI", 13, "bold"), foreground="#dce6e9")
        style.configure("Metric.TLabel", background="#263238", font=("Segoe UI", 17, "bold"), foreground="#f5f8f9")
        style.configure("MetricSub.TLabel", background="#263238", font=("Segoe UI", 9, "bold"), foreground="#91a4aa")
        style.configure("TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8), background="#2f80ed", foreground="#ffffff", borderwidth=0)
        style.map("TButton", background=[("active", "#4a98ff"), ("disabled", "#4b575b")], foreground=[("disabled", "#93a0a4")])
        style.configure("Danger.TButton", background="#d9534f")
        style.map("Danger.TButton", background=[("active", "#ef6a65")])
        style.configure("Dark.TButton", background="#34464d")
        style.map("Dark.TButton", background=[("active", "#466069")])
        style.configure("TCheckbutton", background="#263238", foreground="#d8e0e3", font=("Segoe UI", 10))
        style.map("TCheckbutton", background=[("active", "#263238")])
        style.configure("Treeview", background="#334047", foreground="#e1eaed", fieldbackground="#334047", rowheight=31, font=("Segoe UI", 10), borderwidth=0)
        style.configure("Treeview.Heading", background="#263238", foreground="#b9c7cc", font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#2f80ed")])

        root = ttk.Frame(self, padding=(28, 24))
        root.pack(fill="both", expand=True)
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 18))
        ttk.Label(header, text="PERSONALIZATION CONSOLE", style="Title.TLabel").pack(side="left")
        connection_state = tk.Frame(header, bg="#20272b")
        connection_state.pack(side="right", pady=(7, 0))
        self.connection_spinner = tk.Canvas(connection_state, width=20, height=20, bg="#20272b", highlightthickness=0)
        self.connection_badge = tk.Label(connection_state, text="NOT CONNECTED", bg="#20272b", fg="#f0bd4f", font=("Segoe UI", 10, "bold"))
        self.connection_badge.pack(side="left")
        tk.Label(connection_state, text="  |  ", bg="#20272b", fg="#52646a", font=("Segoe UI", 10)).pack(side="left")
        self.master_badge = tk.Label(connection_state, text="MASTER: NOT REGISTERED", bg="#20272b", fg="#f0bd4f", font=("Segoe UI", 10, "bold"))
        self.master_badge.pack(side="left")
        tk.Label(connection_state, text="  |  ", bg="#20272b", fg="#52646a", font=("Segoe UI", 10)).pack(side="left")
        self.session_badge = tk.Label(connection_state, text="SESSION: LOCKED", bg="#20272b", fg="#93a5aa", font=("Segoe UI", 10, "bold"))
        self.session_badge.pack(side="left")

        body = tk.Frame(root, bg="#20272b")
        body.pack(fill="both", expand=True)
        navigation = tk.Frame(body, bg="#263238", width=180)
        navigation.pack(side="left", fill="y", padx=(0, 16))
        navigation.pack_propagate(False)
        tk.Label(navigation, text="MENU", bg="#263238", fg="#91a4aa", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(20, 10))
        self.pages: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        content = tk.Frame(body, bg="#20272b")
        content.pack(side="right", fill="both", expand=True)
        for key in ("home", "perso", "customers", "debug", "test", "owner", "logs"):
            page = tk.Frame(content, bg="#20272b")
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page
        # The operator workspace is intentionally focused on inspection and
        # its audit trail. Startup and master-session safety pages remain
        # internal, but are not navigation destinations.
        for key, label in (("test", "◉  Test Card"), ("owner", "⌕  Identify Card Owner"), ("customers", "♙  Customers"), ("debug", "⌘  Personalization"), ("logs", "▤  Activity Logs")):
            button = tk.Button(navigation, text=label, command=lambda item=key: self.show_page(item), anchor="w", bg="#263238", fg="#d8e0e3", activebackground="#34464d", activeforeground="#ffffff", relief="flat", borderwidth=0, padx=18, pady=12, font=("Segoe UI", 10, "bold"), cursor="hand2")
            button.pack(fill="x", padx=8, pady=2)
            self.nav_buttons[key] = button

        home_page = self.pages["home"]
        home_card = ttk.Frame(home_page, style="Card.TFrame", padding=30)
        home_card.pack(fill="both", expand=True)
        ttk.Label(home_card, text="Personalization Dashboard", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(home_card, text="Ikuti langkah berikut secara berurutan. Personalisasi baru terbuka ketika semua syarat aman sudah terpenuhi.", style="Card.TLabel", foreground="#9cafb5", wraplength=720).pack(anchor="w", pady=(8, 20))
        procedure = tk.Frame(home_card, bg="#263238")
        procedure.pack(fill="x", pady=(0, 22))
        self.dashboard_steps: list[tk.Label] = []
        for _ in range(4):
            item = tk.Label(procedure, bg="#263238", fg="#71858b", font=("Segoe UI", 11, "bold"), anchor="w", padx=10, pady=7)
            item.pack(fill="x", pady=2)
            self.dashboard_steps.append(item)
        ttk.Label(home_card, text="Status kartu NFC", style="Card.TLabel", foreground="#91a4aa").pack(anchor="w")
        ttk.Label(home_card, textvariable=self.card, style="Metric.TLabel").pack(anchor="w", pady=(5, 2))
        self.dashboard_action_button = ttk.Button(home_card, text="Lanjut ke Personalisasi", command=lambda: self.show_page("perso"), state="disabled")
        self.dashboard_action_button.pack(anchor="w", pady=(18, 0))

        perso_page = self.pages["perso"]
        guide = ttk.Frame(perso_page, style="Card.TFrame", padding=(20, 16))
        guide.pack(fill="x", pady=(0, 14))
        ttk.Label(guide, text="PANDUAN OPERATOR", style="MetricSub.TLabel", foreground="#55a7ff").pack(anchor="w")
        ttk.Label(guide, textvariable=self.operator_guide_title, style="Heading.TLabel").pack(anchor="w", pady=(5, 2))
        ttk.Label(guide, textvariable=self.operator_guide_detail, style="Card.TLabel", foreground="#9cafb5", wraplength=700).pack(anchor="w")
        self.operator_guide_button = ttk.Button(guide, text="Menunggu board", command=self.run_guided_action, state="disabled")
        self.operator_guide_button.pack(anchor="e", pady=(8, 0))
        workspace = ttk.Frame(perso_page, style="Card.TFrame", padding=20)
        workspace.pack(fill="both", expand=True)
        ttk.Label(workspace, text="System Status and Actions", style="Heading.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Separator(workspace).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 18))
        workspace.columnconfigure(0, weight=3)
        workspace.columnconfigure(1, weight=2)

        left = ttk.Frame(workspace, style="Card.TFrame")
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 28))
        ttk.Label(left, text="Alur personalisasi", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(left, text="Status kartu: ", style="Card.TLabel").pack(anchor="w", pady=(14, 4))
        ttk.Label(left, textvariable=self.card, style="Metric.TLabel").pack(anchor="w")
        indicator = tk.Frame(left, bg="#263238")
        indicator.pack(anchor="w", pady=(7, 4))
        self.card_lamp = tk.Canvas(indicator, width=15, height=15, bg="#263238", highlightthickness=0)
        self.card_lamp_dot = self.card_lamp.create_oval(3, 3, 12, 12, fill="#53656b", outline="#71858b")
        self.card_lamp.pack(side="left", padx=(1, 6))
        self.card_lamp_label = tk.Label(indicator, text="MENUNGGU KARTU", bg="#263238", fg="#93a5aa", font=("Segoe UI", 9, "bold"))
        self.card_lamp_label.pack(side="left")
        ttk.Label(left, text="Kartu dan rahasia NFC tidak ditampilkan di aplikasi.", style="Card.TLabel", foreground="#93a5aa").pack(anchor="w", pady=(4, 16))
        for code, label in self.STEP_LABELS:
            item = tk.Label(left, text="○  " + label, bg="#263238", fg="#71858b", font=("Segoe UI", 11, "bold"), anchor="w", padx=8, pady=4)
            item.pack(fill="x", pady=2)
            self.step_state[code] = item

        right = ttk.Frame(workspace, style="Card.TFrame")
        right.grid(row=2, column=1, sticky="nsew")
        ttk.Label(right, text="Personalization Actions", style="Heading.TLabel").pack(anchor="w")
        controls = ttk.Frame(right, style="Card.TFrame")
        controls.pack(fill="x", pady=(12, 8))
        ttk.Checkbutton(controls, text="Mode simulasi", variable=self.simulation, command=self.disconnect).grid(row=0, column=0, sticky="w")
        self.port_selector = ttk.Combobox(controls, textvariable=self.port, width=8, state="normal")
        self.port_selector.grid(row=0, column=1, padx=(14, 6))
        ttk.Button(controls, text="↻", command=self.refresh_ports, style="Dark.TButton").grid(row=0, column=2, padx=(0, 5))
        ttk.Button(controls, text="Hubungkan", command=self.connect, style="Dark.TButton").grid(row=0, column=3)
        ttk.Button(controls, text="Status", command=lambda: self.send("status_request"), style="Dark.TButton").grid(row=1, column=0, pady=(10, 0), sticky="w")
        ttk.Button(controls, text="Kartu baru", command=lambda: self.simulate_card("blank"), style="Dark.TButton").grid(row=1, column=1, pady=(10, 0), padx=(14, 6))
        ttk.Button(controls, text="Angkat", command=self.simulate_remove, style="Dark.TButton").grid(row=1, column=2, columnspan=2, pady=(10, 0), sticky="ew")
        ttk.Separator(right).pack(fill="x", pady=10)
        self.enroll = ttk.Button(right, text="Tahan 10 dtk • Daftar master", style="Dark.TButton")
        self.enroll.pack(fill="x", pady=3)
        self.enroll.bind("<ButtonPress-1>", lambda _event: self.begin_hold("register_master"))
        self.enroll.bind("<ButtonRelease-1>", lambda _event: self.cancel_hold())
        self.reset = ttk.Button(right, text="Tahan 10 dtk • Reset master", style="Danger.TButton")
        self.reset.pack(fill="x", pady=3)
        self.reset.bind("<ButtonPress-1>", lambda _event: self.begin_hold("reset_master"))
        self.reset.bind("<ButtonRelease-1>", lambda _event: self.cancel_hold())
        self.update_master_ui(False)
        self.arm = ttk.Button(right, text="▶  Start Personalization", command=lambda: self.send("perso_arm"))
        self.arm.pack(fill="x", pady=(12, 3))
        self.commit = ttk.Button(right, text="Personalisasi kartu", command=self.confirm_perso, state="disabled")
        self.commit.pack(fill="x", pady=3)
        ttk.Button(right, text="Batal", command=lambda: self.send("cancel"), style="Dark.TButton").pack(fill="x", pady=3)
        ttk.Label(right, text="Daftar master: kartu harus tetap terdeteksi selama 10 detik.", style="Card.TLabel", foreground="#93a5aa", wraplength=290).pack(anchor="w", pady=(12, 0))

        debug_page = self.pages["debug"]
        debug_box = ttk.Frame(debug_page, style="Card.TFrame", padding=20)
        debug_box.pack(fill="both", expand=True)
        ttk.Label(debug_box, text="Card Personalization", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(debug_box, text="Card Precheck is read-only. Card writing starts only after operator confirmation; keys and raw card identity are never sent to the application.", style="Card.TLabel", foreground="#9cafb5", wraplength=920).pack(anchor="w", pady=(5, 12))
        customer_banner = tk.Frame(debug_box, bg="#34444a", padx=14, pady=9)
        customer_banner.pack(fill="x", pady=(0, 12))
        tk.Label(customer_banner, text="CUSTOMER", bg="#34444a", fg="#55a7ff", font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(customer_banner, textvariable=self.selected_customer_number, bg="#34444a", fg="#f5f8f9", font=("Segoe UI", 10, "bold")).pack(side="left", padx=(14, 8))
        tk.Label(customer_banner, textvariable=self.selected_customer_name, bg="#34444a", fg="#d8e0e3", font=("Segoe UI", 10)).pack(side="left")
        tk.Label(customer_banner, textvariable=self.selected_customer_card_status, bg="#34444a", fg="#f0bd4f", font=("Segoe UI", 9, "bold")).pack(side="right")
        self.debug_card_summary = tk.StringVar(value="Waiting for card")
        self.debug_wallet_summary = tk.StringVar(value="Not scanned")
        self.debug_protection_summary = tk.StringVar(value="Trailers are always masked")
        summary = ttk.Frame(debug_box, style="Card.TFrame")
        summary.pack(fill="x", pady=(0, 14))
        for column in range(3):
            summary.columnconfigure(column, weight=1)
        self._metric_card(summary, 0, "◉", "CARD", self.debug_card_summary, "MIFARE Classic 1K · 16 sectors", "#55a7ff")
        self._metric_card(summary, 1, "▣", "WALLET", self.debug_wallet_summary, "Sector 2 · Wallet Data + Card Identity", "#f0bd4f")
        self._metric_card(summary, 2, "⌁", "PROTECTION", self.debug_protection_summary, "Keys and trailers are not displayed", "#20d889")
        debug_actions = ttk.Frame(debug_box, style="Card.TFrame")
        debug_actions.pack(fill="x", pady=(0, 12))
        self.debug_status = tk.StringVar(value="Activate the Personalization session, then tap the card to inspect.")
        self.debug_last_event = tk.StringVar(value="Last event: waiting for a card.")
        self.debug_quality = tk.StringVar(value="○  CARD QUALITY NOT TESTED")
        process_steps = ttk.Frame(debug_box, style="Card.TFrame")
        process_steps.pack(fill="x", pady=(0, 12))
        ttk.Label(process_steps, text=f"CARD PRECHECK — READ ONLY · {len(self.PRECHECK_PROCESS_STEPS)} STEPS", style="MetricSub.TLabel", foreground="#55a7ff").pack(anchor="w", pady=(0, 6))
        self.technical_process_labels: list[tk.Label] = []
        process_grid = tk.Frame(process_steps, bg="#263238")
        process_grid.pack(fill="x")
        # A single vertical checklist makes the required order unambiguous.
        process_grid.columnconfigure(0, weight=1)
        for index, text in enumerate(self.PRECHECK_PROCESS_STEPS):
            item = tk.Label(
                process_grid, text=f"○  {index + 1}. {text}", anchor="w",
                bg="#34444a", fg="#93a5aa", font=("Segoe UI", 9, "bold"), padx=10, pady=4,
            )
            item.grid(row=index, column=0, sticky="ew", pady=(0, 3))
            self.technical_process_labels.append(item)
        ttk.Label(process_steps, text="PERSONALIZATION — WRITES CARD · 6 STEPS", style="MetricSub.TLabel", foreground="#f0bd4f").pack(anchor="w", pady=(8, 6))
        self.personalization_process_labels: list[tk.Label] = []
        personalization_grid = tk.Frame(process_steps, bg="#263238")
        personalization_grid.pack(fill="x")
        personalization_grid.columnconfigure(0, weight=1)
        for index, text in enumerate(self.PERSONALIZATION_PROCESS_STEPS):
            item = tk.Label(
                personalization_grid, text=f"○  {index + 1}. {text}", anchor="w",
                bg="#34444a", fg="#93a5aa", font=("Segoe UI", 9, "bold"), padx=10, pady=4,
            )
            item.grid(row=index, column=0, sticky="ew", pady=(0, 3))
            self.personalization_process_labels.append(item)
        self.wallet_slot_button = ttk.Button(
            debug_actions, text="Check Wallet Data and Card Identity first", command=self.fixed_slot_action,
            state="disabled", style="Dark.TButton",
        )
        self.wallet_slot_button.pack(side="left", padx=(8, 0))
        self.wallet_slot_button.pack_forget()
        self.debug_quality_label = ttk.Label(debug_actions, textvariable=self.debug_quality, style="Card.TLabel", foreground="#93a5aa")
        self.debug_quality_label.pack(side="left", padx=(16, 0))
        ttk.Label(debug_actions, textvariable=self.debug_status, style="Card.TLabel", foreground="#9cafb5").pack(side="left", padx=(16, 0))
        ttk.Label(debug_actions, textvariable=self.debug_liveness, style="Card.TLabel", foreground="#55a7ff").pack(side="right")
        ttk.Label(debug_box, textvariable=self.debug_last_event, style="Card.TLabel", foreground="#f0bd4f").pack(anchor="w", pady=(0, 10))

        serial_header = ttk.Frame(debug_box, style="Card.TFrame")
        serial_header.pack(fill="x", pady=(2, 5))
        ttk.Label(serial_header, text="PARSED SERIAL MONITOR", style="MetricSub.TLabel", foreground="#55a7ff").pack(side="left")
        ttk.Button(serial_header, text="Clear monitor", command=self.clear_parsed_serial_monitor, style="Dark.TButton").pack(side="right")
        serial_columns = ("time", "type", "code", "nfc", "master", "session", "operation", "card_session")
        self.parsed_serial_tree = ttk.Treeview(debug_box, columns=serial_columns, show="headings", height=4)
        serial_layout = (
            ("time", "TIME", 80), ("type", "TYPE", 105), ("code", "CODE", 245),
            ("nfc", "NFC", 85), ("master", "MASTER", 95), ("session", "SESSION", 95),
            ("operation", "OPERATION", 130), ("card_session", "CARD #", 70),
        )
        for column, label, width in serial_layout:
            self.parsed_serial_tree.heading(column, text=label)
            self.parsed_serial_tree.column(column, width=width, anchor="w")
        self.parsed_serial_tree.pack(fill="x", pady=(0, 10))

        self.debug_detail_frame = ttk.Frame(debug_box, style="Card.TFrame")
        columns = ("sector", "block", "kind", "state", "data")
        self.debug_tree = ttk.Treeview(self.debug_detail_frame, columns=columns, show="headings", height=16)
        for column, label, width in (("sector", "SECTOR", 80), ("block", "BLOCK", 80), ("kind", "TYPE", 175), ("state", "READ STATUS", 180), ("data", "DATA (HEX)", 340)):
            self.debug_tree.heading(column, text=label)
            self.debug_tree.column(column, width=width, anchor="w")
        self.debug_tree.pack(fill="both", expand=True)
        # The full sector map is retained internally for diagnostic processing,
        # but stays off the operator screen.  The summary cards are the
        # operator-facing result.
        self.debug_detail_frame.pack_forget()

        customers_page = self.pages["customers"]
        customers_box = ttk.Frame(customers_page, style="Card.TFrame", padding=20)
        customers_box.pack(fill="both", expand=True)
        ttk.Label(customers_box, text="Customers", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            customers_box,
            text="Register and update customer data first. A customer must be selected before Card Personalization can start.",
            style="Card.TLabel", foreground="#9cafb5",
        ).pack(anchor="w", pady=(5, 14))
        customer_body = tk.Frame(customers_box, bg="#263238")
        customer_body.pack(fill="both", expand=True)
        customer_left = tk.Frame(customer_body, bg="#263238")
        customer_left.pack(side="left", fill="both", expand=True, padx=(0, 18))
        customer_search_row = tk.Frame(customer_left, bg="#263238")
        customer_search_row.pack(fill="x", pady=(0, 8))
        self.customer_session_widgets: list[tuple[Any, str]] = []
        self.customer_search_entry = ttk.Entry(customer_search_row, textvariable=self.customer_search)
        self.customer_search_entry.pack(side="left", fill="x", expand=True)
        self.customer_search_entry.bind("<KeyRelease>", self.schedule_customer_search)
        self.customer_session_widgets.append((self.customer_search_entry, "normal"))
        customer_clear_search_button = ttk.Button(customer_search_row, text="×", command=self.clear_customer_search, style="Dark.TButton", width=3)
        customer_clear_search_button.pack(side="left", padx=(4, 0))
        customer_new_button = ttk.Button(customer_search_row, text="New", command=self.clear_customer_form, style="Dark.TButton")
        customer_new_button.pack(side="left", padx=(8, 0))
        self.customer_session_widgets.extend(((customer_clear_search_button, "normal"), (customer_new_button, "normal")))
        self.customer_tree = ttk.Treeview(
            customer_left, columns=("number", "name", "nik", "card"), show="headings", height=13,
        )
        for column, label, width in (
            ("number", "CUSTOMER #", 125), ("name", "FULL NAME", 230),
            ("nik", "NIK", 145), ("card", "CARD STATUS", 120),
        ):
            self.customer_tree.heading(column, text=label)
            self.customer_tree.column(column, width=width, anchor="w")
        self.customer_tree.pack(fill="both", expand=True)
        self.customer_tree.bind("<<TreeviewSelect>>", self.on_customer_tree_selected)
        self.customer_session_widgets.append((self.customer_tree, "normal"))

        customer_right = tk.Frame(customer_body, bg="#263238", width=390)
        customer_right.pack(side="right", fill="y")
        customer_right.pack_propagate(False)
        ttk.Label(customer_right, text="Customer details", style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        form_fields = (
            ("Customer number", self.customer_form_number, True),
            ("NIK (16 digits)", self.customer_form_nik, False),
            ("Family Card / KK (16 digits)", self.customer_form_kk, False),
            ("Full name", self.customer_form_name, False),
            ("Phone", self.customer_form_phone, False),
            ("Address", self.customer_form_address, False),
        )
        for label, variable, readonly in form_fields:
            ttk.Label(customer_right, text=label, style="Card.TLabel", foreground="#93a5aa").pack(anchor="w", pady=(7, 2))
            entry = ttk.Entry(customer_right, textvariable=variable)
            entry.pack(fill="x")
            if readonly:
                entry.configure(state="readonly")
            self.customer_session_widgets.append((entry, "readonly" if readonly else "normal"))
        ttk.Label(customer_right, text="Status", style="Card.TLabel", foreground="#93a5aa").pack(anchor="w", pady=(7, 2))
        customer_status_combo = ttk.Combobox(customer_right, textvariable=self.customer_form_status, values=("active", "inactive"), state="readonly")
        customer_status_combo.pack(fill="x")
        self.customer_session_widgets.append((customer_status_combo, "readonly"))
        customer_form_actions = tk.Frame(customer_right, bg="#263238")
        customer_form_actions.pack(fill="x", pady=(15, 7))
        customer_save_button = ttk.Button(customer_form_actions, text="Save new", command=self.save_new_customer)
        customer_save_button.pack(side="left")
        customer_update_button = ttk.Button(customer_form_actions, text="Update", command=self.update_customer, style="Dark.TButton")
        customer_update_button.pack(side="left", padx=(8, 0))
        self.customer_session_widgets.extend(((customer_save_button, "normal"), (customer_update_button, "normal")))
        self.personalize_selected_customer_button = ttk.Button(
            customer_right, text="Personalize card for selected customer", command=self.open_selected_customer_personalization,
        )
        self.personalize_selected_customer_button.pack(fill="x", pady=(8, 0))
        self.customer_session_widgets.append((self.personalize_selected_customer_button, "normal"))

        test_page = self.pages["test"]
        test_box = ttk.Frame(test_page, style="Card.TFrame", padding=28)
        test_box.pack(fill="both", expand=True)
        ttk.Label(test_box, text="Test Card — Read Only", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            test_box,
            text="Tests only whether the NFC reader can detect a card. Any card can be tested, including the master card. It does not open a session, scan sectors, or write the card.",
            style="Card.TLabel", foreground="#9cafb5", wraplength=850,
        ).pack(anchor="w", pady=(6, 28))
        self.card_test_result = ttk.Label(test_box, textvariable=self.card_test_status, style="Metric.TLabel", foreground="#55a7ff")
        self.card_test_result.pack(anchor="w", pady=(0, 8))
        ttk.Label(test_box, textvariable=self.card_test_count, style="Card.TLabel", foreground="#93a5aa").pack(anchor="w", pady=(0, 22))
        self.card_test_button = ttk.Button(test_box, text="Start card test", command=self.start_card_test)
        self.card_test_button.pack(anchor="w")
        ttk.Label(
            test_box,
            text="Keep the card flat on the reader. The result changes immediately when a card is detected or removed.",
            style="Card.TLabel", foreground="#93a5aa",
        ).pack(anchor="w", pady=(18, 0))

        owner_page = self.pages["owner"]
        owner_box = ttk.Frame(owner_page, style="Card.TFrame", padding=28)
        owner_box.pack(fill="both", expand=True)
        ttk.Label(owner_box, text="Identify Card Owner — Read Only", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(
            owner_box,
            text="Reads only a valid personalized Card Number, then looks up its registered owner in the Database. It does not expose UID, keys, wallet bytes, or write the card.",
            style="Card.TLabel", foreground="#9cafb5", wraplength=850,
        ).pack(anchor="w", pady=(6, 28))
        ttk.Label(owner_box, textvariable=self.owner_lookup_status, style="Metric.TLabel", foreground="#55a7ff").pack(anchor="w", pady=(0, 12))
        ttk.Label(owner_box, textvariable=self.owner_lookup_reference, style="Card.TLabel", foreground="#f0bd4f").pack(anchor="w", pady=(0, 8))
        ttk.Label(owner_box, textvariable=self.owner_lookup_customer, style="Heading.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(owner_box, textvariable=self.owner_lookup_details, style="Card.TLabel", foreground="#93a5aa", wraplength=850).pack(anchor="w", pady=(0, 22))
        self.owner_lookup_button = ttk.Button(owner_box, text="Start owner lookup", command=self.start_owner_lookup)
        self.owner_lookup_button.pack(anchor="w")

        log_page = self.pages["logs"]
        log_box = ttk.Frame(log_page, style="Card.TFrame", padding=20)
        log_box.pack(fill="both", expand=True)
        log_header = ttk.Frame(log_box, style="Card.TFrame")
        log_header.pack(fill="x")
        ttk.Label(log_header, text="Recent Logs", style="Heading.TLabel").pack(side="left")
        self.log_order_button = ttk.Button(log_header, text="Newest ↓", command=self.toggle_log_order, style="Dark.TButton")
        self.log_order_button.pack(side="right")
        ttk.Button(log_header, text="Clear logs", command=self.clear_logs, style="Danger.TButton").pack(side="right", padx=(0, 8))
        ttk.Label(log_box, text="Database activity without UID, keys, or raw card data", style="Card.TLabel", foreground="#93a5aa").pack(anchor="w", pady=(3, 12))
        self.log = ttk.Treeview(log_box, columns=("time", "type", "status", "operation"), show="headings", height=6)
        for column, label, width in (("time", "TIME", 135), ("type", "TYPE", 160), ("status", "STATUS", 245), ("operation", "OPERATION", 180)):
            self.log.heading(column, text=label, command=self.toggle_log_order if column == "time" else "")
            self.log.column(column, width=width, anchor="w")
        self.log.pack(fill="both", expand=True)
        self.load_customers()
        self.show_page("customers")
        self.refresh_operator_guide()
        self.refresh_dashboard_procedure()

    def load_customers(self) -> None:
        if not self.database or not hasattr(self, "customer_tree") or self.last_session_open is not True:
            return
        term = self.customer_search.get().strip()
        cursor = self.database.cursor()
        if term:
            like = f"%{term}%"
            cursor.execute(
                "SELECT c.id, c.customer_number, c.full_name, c.nik, "
                "CASE WHEN EXISTS (SELECT 1 FROM customer_cards cc WHERE cc.customer_id=c.id AND cc.status='active') "
                "THEN 'PERSONALIZED' ELSE 'NO CARD' END "
                "FROM customers c WHERE c.customer_number LIKE %s OR c.full_name LIKE %s OR c.nik LIKE %s "
                "OR c.family_card_number LIKE %s OR COALESCE(c.phone, '') LIKE %s OR COALESCE(c.address, '') LIKE %s "
                "ORDER BY c.full_name LIMIT 500",
                (like, like, like, like, like, like),
            )
        else:
            cursor.execute(
                "SELECT c.id, c.customer_number, c.full_name, c.nik, "
                "CASE WHEN EXISTS (SELECT 1 FROM customer_cards cc WHERE cc.customer_id=c.id AND cc.status='active') "
                "THEN 'PERSONALIZED' ELSE 'NO CARD' END "
                "FROM customers c ORDER BY c.full_name LIMIT 500"
            )
        rows = cursor.fetchall()
        cursor.close()
        for item in self.customer_tree.get_children():
            self.customer_tree.delete(item)
        for customer_id, number, name, nik, card_status in rows:
            self.customer_tree.insert(
                "", "end", iid=str(customer_id),
                values=(number, name, mask_identity_number(str(nik)), card_status),
            )

    def schedule_customer_search(self, _event: Any = None) -> None:
        if self.last_session_open is not True:
            return
        """Debounce keystrokes so MySQL is not queried for every key at once."""
        if self.customer_search_after:
            self.after_cancel(self.customer_search_after)
        self.customer_search_after = self.after(180, self.run_scheduled_customer_search)

    def run_scheduled_customer_search(self) -> None:
        self.customer_search_after = None
        self.load_customers()

    def clear_customer_search(self) -> None:
        if self.customer_search_after:
            self.after_cancel(self.customer_search_after)
            self.customer_search_after = None
        self.customer_search.set("")
        self.load_customers()
        self.customer_search_entry.focus_set()

    def clear_customer_form(self) -> None:
        self.selected_customer_id = None
        self.customer_form_number.set("Generated when saved")
        self.customer_form_nik.set("")
        self.customer_form_kk.set("")
        self.customer_form_name.set("")
        self.customer_form_phone.set("")
        self.customer_form_address.set("")
        self.customer_form_status.set("active")
        self.selected_customer_number.set("No customer selected")
        self.selected_customer_name.set("Select a registered customer before scanning a card.")
        self.selected_customer_card_status.set("Card status: not checked")
        if hasattr(self, "customer_tree"):
            self.customer_tree.selection_remove(*self.customer_tree.selection())

    def on_customer_tree_selected(self, _event: Any = None) -> None:
        if self.last_session_open is not True:
            return
        selection = self.customer_tree.selection()
        if not selection or not self.database:
            return
        customer_id = int(selection[0])
        cursor = self.database.cursor()
        cursor.execute(
            "SELECT id, customer_number, nik, family_card_number, full_name, phone, address, status "
            "FROM customers WHERE id=%s",
            (customer_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        if not row:
            return
        self.selected_customer_id = int(row[0])
        self.customer_form_number.set(str(row[1]))
        self.customer_form_nik.set(str(row[2]))
        self.customer_form_kk.set(str(row[3]))
        self.customer_form_name.set(str(row[4]))
        self.customer_form_phone.set(str(row[5] or ""))
        self.customer_form_address.set(str(row[6] or ""))
        self.customer_form_status.set(str(row[7]))
        self.selected_customer_number.set(str(row[1]))
        self.selected_customer_name.set(str(row[4]))
        self.refresh_selected_customer_card_status()

    def customer_form_values(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.customer_form_nik.get().strip(), self.customer_form_kk.get().strip(),
            self.customer_form_name.get().strip(), self.customer_form_phone.get().strip(),
            self.customer_form_address.get().strip(), self.customer_form_status.get().strip() or "active",
        )

    def save_new_customer(self) -> None:
        if not self.require_open_session("Customer data"):
            return
        if not self.database:
            messagebox.showerror("Database", "Database is not connected.")
            return
        nik, kk, name, phone, address, status = self.customer_form_values()
        errors = validate_customer_fields(nik, kk, name, phone)
        if errors:
            messagebox.showerror("Customer data", "\n".join(errors))
            return
        number = "CUST-" + uuid.uuid4().hex[:10].upper()
        now = datetime.now().astimezone().isoformat()
        try:
            cursor = self.database.cursor()
            cursor.execute(
                "INSERT INTO customers (customer_number, nik, family_card_number, full_name, phone, address, status, created_at, updated_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (number, nik, kk, name, phone or None, address or None, status, now, now),
            )
            customer_id = int(cursor.lastrowid)
            cursor.close()
            self.database.commit()
        except mysql.connector.IntegrityError:
            self.database.rollback()
            messagebox.showerror("Customer data", "NIK is already registered.")
            return
        except Exception as error:
            self.database.rollback()
            messagebox.showerror("Customer data", str(error))
            return
        self.load_customers()
        self.customer_tree.selection_set(str(customer_id))
        self.customer_tree.focus(str(customer_id))
        self.on_customer_tree_selected()
        messagebox.showinfo("Customer saved", f"{number} — {name} was added.")

    def update_customer(self) -> None:
        if not self.require_open_session("Customer data"):
            return
        if not self.database or self.selected_customer_id is None:
            messagebox.showerror("Customer data", "Select a customer to update.")
            return
        nik, kk, name, phone, address, status = self.customer_form_values()
        has_active_card = self.refresh_selected_customer_card_status()
        if has_active_card:
            try:
                cursor = self.database.cursor()
                cursor.execute(
                    "SELECT nik, family_card_number, full_name FROM customers WHERE id=%s",
                    (self.selected_customer_id,),
                )
                identity = cursor.fetchone()
                cursor.close()
                if identity is None:
                    raise RuntimeError("Customer record was not found.")
                # NIK, KK, and name are immutable while an active card is
                # assigned. Never trust alternate values submitted by the UI.
                nik, kk, name = (str(identity[0]), str(identity[1]), str(identity[2]))
            except Exception as error:
                messagebox.showerror("Customer data", str(error))
                return
        errors = validate_customer_fields(nik, kk, name, phone)
        if errors:
            messagebox.showerror("Customer data", "\n".join(errors))
            return
        try:
            cursor = self.database.cursor()
            cursor.execute(
                "UPDATE customers SET nik=%s, family_card_number=%s, full_name=%s, phone=%s, address=%s, status=%s, updated_at=%s WHERE id=%s",
                (nik, kk, name, phone or None, address or None, status, datetime.now().astimezone().isoformat(), self.selected_customer_id),
            )
            cursor.close()
            self.database.commit()
        except mysql.connector.IntegrityError:
            self.database.rollback()
            messagebox.showerror("Customer data", "NIK is already registered to another customer.")
            return
        except Exception as error:
            self.database.rollback()
            messagebox.showerror("Customer data", str(error))
            return
        customer_id = self.selected_customer_id
        self.load_customers()
        self.customer_tree.selection_set(str(customer_id))
        self.on_customer_tree_selected()
        messagebox.showinfo("Customer updated", "Customer data was updated.")

    def refresh_selected_customer_card_status(self) -> bool:
        if not self.database or self.selected_customer_id is None:
            self.selected_customer_card_status.set("Card status: not checked")
            return False
        cursor = self.database.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM customer_cards WHERE customer_id=%s AND status='active'",
            (self.selected_customer_id,),
        )
        has_active_card = int(cursor.fetchone()[0]) > 0
        cursor.close()
        self.selected_customer_card_status.set("Card: PERSONALIZED" if has_active_card else "Card: NOT PERSONALIZED")
        return has_active_card

    def open_selected_customer_personalization(self) -> None:
        if not self.require_open_session("Card Personalization"):
            return
        if self.selected_customer_id is None:
            messagebox.showerror("Card Personalization", "Select a registered customer first.")
            return
        if self.customer_form_status.get() != "active":
            messagebox.showerror("Card Personalization", "Only an active customer can receive a card.")
            return
        if self.refresh_selected_customer_card_status():
            messagebox.showerror(
                "Card Personalization",
                "This customer already has an active personalized card. Replacement is not implemented in this version.",
            )
            return
        self.show_page("debug")

    def start_personalization_run(self, event: dict) -> bool:
        """Create the database trace before the read-only precheck starts."""
        if not self.database or self.selected_customer_id is None:
            messagebox.showerror("Card Personalization", "A database-connected customer must be selected first.")
            return False
        if self.refresh_selected_customer_card_status():
            messagebox.showerror(
                "Card Personalization",
                "This customer already has an active card. Remove this card and select another customer.",
            )
            return False
        run_id = str(uuid.uuid4())
        raw_session = event.get("card_session")
        card_session = int(raw_session) if isinstance(raw_session, (int, float, str)) and str(raw_session).isdigit() else None
        try:
            cursor = self.database.cursor()
            cursor.execute(
                "INSERT INTO personalization_runs "
                "(run_id, customer_id, device_port, card_session, started_at, result) "
                "VALUES (%s,%s,%s,%s,%s,'precheck')",
                (run_id, self.selected_customer_id, self.port.get().strip(), card_session, datetime.now().astimezone().isoformat()),
            )
            cursor.execute(
                "INSERT INTO card_reference_allocations (personalization_run_id, allocated_at) VALUES (%s,%s)",
                (run_id, datetime.now().astimezone().isoformat()),
            )
            card_reference = int(cursor.lastrowid)
            if card_reference <= 0 or card_reference > 0xFFFFFFFF:
                raise RuntimeError("Card Number allocation exceeded the supported range.")
            cursor.close()
            self.database.commit()
        except Exception as error:
            self.database.rollback()
            messagebox.showerror("Personalization database", f"Could not create the run record. The card will not be changed.\n\n{error}")
            return False
        self.active_run_id = run_id
        self.active_run_customer_id = self.selected_customer_id
        self.active_run_card_session = card_session
        self.active_card_reference = card_reference
        return True

    def update_personalization_run(self, **values: Any) -> bool:
        if not self.database or not self.active_run_id:
            return False
        allowed = {
            "card_session", "completed_at", "result", "failure_stage", "failure_code",
            "precheck_result", "sectors_checked", "readable_blocks", "restricted_blocks",
            "quality_success", "quality_attempts", "protection_written", "wallet_written",
            "verification_passed",
        }
        fields = [(key, value) for key, value in values.items() if key in allowed]
        if not fields:
            return True
        sql = "UPDATE personalization_runs SET " + ", ".join(f"{key}=%s" for key, _ in fields) + " WHERE run_id=%s"
        try:
            cursor = self.database.cursor()
            cursor.execute(sql, tuple(value for _, value in fields) + (self.active_run_id,))
            cursor.close()
            self.database.commit()
            return True
        except Exception:
            self.database.rollback()
            return False

    def fail_or_cancel_personalization_run(self, result: str, stage: str, code: str) -> None:
        if self.active_run_id:
            self.update_personalization_run(
                result=result, failure_stage=stage, failure_code=code,
                completed_at=datetime.now().astimezone().isoformat(),
            )

            # A Database reservation is created before any card write. If the
            # write never completes, retain the row as history but make sure it
            # cannot be mistaken for an active customer card.
            if self.database:
                try:
                    cursor = self.database.cursor()
                    cursor.execute(
                        "UPDATE customer_cards SET status=%s "
                        "WHERE personalization_run_id=%s AND status='pending_write'",
                        ("write_failed" if result == "failed" else "cancelled", self.active_run_id),
                    )
                    cursor.close()
                    self.database.commit()
                except Exception:
                    self.database.rollback()

    def reserve_personalization_ownership(self) -> bool:
        """Commit a pending Database ownership row before touching the card."""
        if not self.database or not self.active_run_id or self.active_run_customer_id is None or self.active_card_reference is None:
            return False
        now = datetime.now().astimezone().isoformat()
        reference = f"CARD-{self.active_card_reference:08X}"
        try:
            cursor = self.database.cursor()
            cursor.execute(
                "SELECT personalization_run_id, status FROM customer_cards "
                "WHERE customer_id=%s AND status IN ('active','pending_write') LIMIT 1 FOR UPDATE",
                (self.active_run_customer_id,),
            )
            occupied = cursor.fetchone()
            if occupied is not None and str(occupied[0]) != self.active_run_id:
                raise RuntimeError(f"Customer already has a {occupied[1]} card assignment.")
            if occupied is not None and str(occupied[1]) == "active":
                raise RuntimeError("This personalization run is already active; the card will not be rewritten.")
            cursor.execute(
                "SELECT customer_id, card_reference, status FROM customer_cards "
                "WHERE personalization_run_id=%s LIMIT 1 FOR UPDATE",
                (self.active_run_id,),
            )
            existing = cursor.fetchone()
            if existing is None:
                cursor.execute(
                    "INSERT INTO customer_cards "
                    "(customer_id, personalization_run_id, card_reference, card_session, status, wallet_version, wallet_sector, wallet_block, activated_at) "
                    "VALUES (%s,%s,%s,%s,'pending_write',2,2,8,%s)",
                    (self.active_run_customer_id, self.active_run_id, reference, self.active_run_card_session, now),
                )
            else:
                existing_customer, existing_reference, existing_status = existing
                if int(existing_customer) != self.active_run_customer_id or str(existing_reference) != reference:
                    raise RuntimeError("The existing Database reservation does not match this customer and Card Number.")
                if str(existing_status) != "pending_write":
                    raise RuntimeError(f"The personalization reservation is already {existing_status}.")
            cursor.execute(
                "UPDATE personalization_runs SET result='writing', failure_stage=NULL, failure_code=NULL "
                "WHERE run_id=%s",
                (self.active_run_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("The personalization run could not be armed.")
            cursor.close()
            self.database.commit()
            self.selected_customer_card_status.set(f"Card: RESERVED · {reference}")
            return True
        except Exception as error:
            self.database.rollback()
            messagebox.showerror(
                "Personalization database",
                "Could not reserve customer ownership in the Database. The card will not be changed.\n\n" + str(error),
            )
            return False

    def record_personalization_success(self) -> bool:
        """Activate the ownership row reserved before the physical write."""
        if not self.database or not self.active_run_id or self.active_run_customer_id is None or self.active_card_reference is None:
            return False
        now = datetime.now().astimezone().isoformat()
        reference = f"CARD-{self.active_card_reference:08X}"
        try:
            cursor = self.database.cursor()
            cursor.execute(
                "SELECT id, customer_id, card_reference, status FROM customer_cards "
                "WHERE personalization_run_id=%s LIMIT 1 FOR UPDATE",
                (self.active_run_id,),
            )
            reserved = cursor.fetchone()
            if reserved is None:
                raise RuntimeError("The pre-write Database reservation is missing.")
            card_id, customer_id, stored_reference, stored_status = reserved
            if int(customer_id) != self.active_run_customer_id or str(stored_reference) != reference:
                raise RuntimeError("The Database reservation does not match the written card.")
            if str(stored_status) not in ("pending_write", "active"):
                raise RuntimeError(f"The Database reservation is {stored_status}, not pending.")
            cursor.execute(
                "SELECT id FROM customer_cards WHERE customer_id=%s AND status='active' AND id<>%s LIMIT 1 FOR UPDATE",
                (self.active_run_customer_id, card_id),
            )
            if cursor.fetchone() is not None:
                raise RuntimeError("Customer already has another active personalized card.")
            cursor.execute(
                "UPDATE personalization_runs SET result='success', completed_at=%s, "
                "protection_written=TRUE, wallet_written=TRUE, verification_passed=TRUE WHERE run_id=%s",
                (now, self.active_run_id),
            )
            cursor.execute(
                "UPDATE customer_cards SET status='active', activated_at=%s "
                "WHERE id=%s AND status IN ('pending_write','active')",
                (now, card_id),
            )
            cursor.close()
            self.database.commit()
            self.selected_customer_card_status.set(f"Card: PERSONALIZED · {reference}")
            return True
        except Exception as error:
            self.database.rollback()
            messagebox.showerror(
                "DATABASE SYNC REQUIRED",
                "The card was written and verified, but customer ownership could not be saved. "
                "Do not personalize this card again. Record it for manual reconciliation.\n\n" + str(error),
            )
            return False

    def record_personalization_removal(self, card_reference: int) -> str:
        """Detach one verified card from its owner without deleting history."""
        if not self.database or card_reference <= 0:
            return "database_failed"
        reference = f"CARD-{card_reference:08X}"
        try:
            cursor = self.database.cursor()
            cursor.execute(
                "SELECT customer_id FROM customer_cards "
                "WHERE card_reference=%s AND status='active' ORDER BY id DESC LIMIT 1 FOR UPDATE",
                (reference,),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.close()
                self.database.rollback()
                return "not_found"
            owner_id = int(row[0])
            cursor.execute(
                "UPDATE customer_cards SET status='removed' "
                "WHERE card_reference=%s AND status='active'",
                (reference,),
            )
            cursor.close()
            self.database.commit()
            if self.selected_customer_id == owner_id:
                self.selected_customer_card_status.set("Card: NOT PERSONALIZED")
            self.load_customers()
            return "updated"
        except Exception:
            self.database.rollback()
            return "database_failed"

    def show_page(self, key: str) -> None:
        if not hasattr(self, "pages") or key not in self.pages:
            return
        if key != "home" and self.last_session_open is not True:
            key = "home"
        if key == "debug" and self.selected_customer_id is None:
            key = "customers"
        if key in ("perso", "debug") and not bool(self.last_session_open):
            key = "home"
        previous = getattr(self, "current_page", "")
        if previous == "test" and key != "test":
            self.stop_card_test()
        if previous == "owner" and key != "owner":
            self.stop_owner_lookup()
        if previous == "debug" and key != "debug":
            # Do not let a card detected on a different page remain as a
            # stale STM32 candidate for the next personalization run.
            if self.active_run_id and not self.personalization_completed:
                self.fail_or_cancel_personalization_run("cancelled", "operator_navigation", "left_personalization_page")
                self.active_run_id = None
                self.active_run_customer_id = None
                self.active_run_card_session = None
                self.active_card_reference = None
            self.send("cancel")
        if key == "test" and previous != "test":
            self.start_card_test()
        if key == "owner" and previous != "owner":
            self.start_owner_lookup()
        if key == "debug" and previous != "debug":
            # A new personalization visit always starts with a fresh card. This makes
            # the master -> remove -> non-master operator sequence explicit.
            self.clear_technical_scan("Personalization ready. Remove any card, then tap a non-master card.")
            self.send("cancel")
        self.current_page = key
        self.pages[key].lift()
        for name, button in self.nav_buttons.items():
            button.configure(bg="#2f80ed" if name == key else "#263238")

    def start_card_test(self) -> None:
        if self.card_test_active and self.card_test_confirmed:
            return
        self.card_test_active = True
        self.card_test_confirmed = False
        self.card_test_start_attempts = 0
        self.card_test_status.set("Waiting for any card.")
        self.card_test_button.configure(text="Starting reader test...", state="disabled")
        self.request_card_test_start()

    def request_card_test_start(self) -> None:
        if not self.card_test_active or self.card_test_confirmed:
            return
        self.card_test_start_attempts += 1
        self.send("card_test_start")
        if self.card_test_start_after:
            self.after_cancel(self.card_test_start_after)
        if self.card_test_start_attempts < 4:
            self.card_test_start_after = self.after(700, self.request_card_test_start)
        else:
            self.card_test_start_after = self.after(900, self.fail_card_test_start)

    def confirm_card_test_start(self) -> None:
        self.card_test_active = True
        self.card_test_confirmed = True
        if self.card_test_start_after:
            self.after_cancel(self.card_test_start_after)
            self.card_test_start_after = None
        self.card_test_button.configure(text="Reader test active", state="disabled")

    def fail_card_test_start(self) -> None:
        if self.card_test_confirmed:
            return
        self.card_test_active = False
        self.card_test_status.set("Board did not confirm Test Card mode. Press Retry.")
        self.card_test_button.configure(text="Retry card test", state="normal")

    def stop_card_test(self) -> None:
        if self.card_test_start_after:
            self.after_cancel(self.card_test_start_after)
            self.card_test_start_after = None
        self.card_test_active = False
        self.card_test_confirmed = False
        self.card_test_status.set("Reader test stopped.")
        if hasattr(self, "card_test_button"):
            self.card_test_button.configure(text="Start card test", state="normal")
        self.send("card_test_stop")

    def start_owner_lookup(self) -> None:
        if self.owner_lookup_active and self.owner_lookup_confirmed:
            return
        self.owner_lookup_active = True
        self.owner_lookup_confirmed = False
        self.owner_lookup_start_attempts = 0
        self.owner_lookup_status.set("Starting read-only owner lookup...")
        self.owner_lookup_record = {}
        self.owner_lookup_reference.set("Card Number: —")
        self.owner_lookup_customer.set("Owner: —")
        self.owner_lookup_details.set("Tap a personalized card after the Board is ready.")
        self.owner_lookup_button.configure(text="Starting owner lookup...", state="disabled")
        self.request_owner_lookup_start()

    def request_owner_lookup_start(self) -> None:
        if not self.owner_lookup_active or self.owner_lookup_confirmed:
            return
        self.owner_lookup_start_attempts += 1
        self.send("owner_lookup_start")
        if self.owner_lookup_start_after:
            self.after_cancel(self.owner_lookup_start_after)
        if self.owner_lookup_start_attempts < 4:
            self.owner_lookup_start_after = self.after(700, self.request_owner_lookup_start)
        else:
            self.owner_lookup_start_after = self.after(900, self.fail_owner_lookup_start)

    def confirm_owner_lookup_start(self) -> None:
        self.owner_lookup_active = True
        self.owner_lookup_confirmed = True
        if self.owner_lookup_start_after:
            self.after_cancel(self.owner_lookup_start_after)
            self.owner_lookup_start_after = None
        self.owner_lookup_status.set("Reader ready — tap a personalized card.")
        self.owner_lookup_button.configure(text="Owner lookup active", state="disabled")

    def fail_owner_lookup_start(self) -> None:
        if self.owner_lookup_confirmed:
            return
        self.owner_lookup_active = False
        self.owner_lookup_status.set("Board did not confirm owner lookup mode. Press Retry.")
        self.owner_lookup_button.configure(text="Retry owner lookup", state="normal")

    def stop_owner_lookup(self) -> None:
        if self.owner_lookup_start_after:
            self.after_cancel(self.owner_lookup_start_after)
            self.owner_lookup_start_after = None
        self.owner_lookup_active = False
        self.owner_lookup_confirmed = False
        if hasattr(self, "owner_lookup_button"):
            self.owner_lookup_button.configure(text="Start owner lookup", state="normal")
        self.send("owner_lookup_stop")

    def show_card_owner(self, card_reference: int) -> None:
        reference = f"CARD-{card_reference:08X}"
        self.owner_lookup_record = {"card_number": reference}
        self.owner_lookup_reference.set("Card Number: " + reference)
        if not self.database:
            self.owner_lookup_status.set("Card is valid, but the Database is unavailable.")
            self.owner_lookup_customer.set("Owner: database unavailable")
            self.owner_lookup_details.set("The card was not changed.")
            return
        try:
            cursor = self.database.cursor()
            cursor.execute(
                "SELECT c.customer_number,c.full_name,c.nik,c.family_card_number,cc.status,cc.activated_at "
                "FROM customer_cards cc JOIN customers c ON c.id=cc.customer_id "
                "WHERE cc.card_reference=%s ORDER BY cc.id DESC LIMIT 1",
                (reference,),
            )
            row = cursor.fetchone()
            cursor.close()
        except Exception as error:
            self.owner_lookup_status.set("Card is valid, but owner lookup failed.")
            self.owner_lookup_customer.set("Owner: database error")
            self.owner_lookup_details.set(str(error))
            return
        if not row:
            self.owner_lookup_status.set("Valid personalized card; owner record was not found.")
            self.owner_lookup_customer.set("Owner: not registered in this database")
            self.owner_lookup_details.set("The card was not changed. Check Database synchronization or Activity Logs.")
            return
        customer_number, full_name, nik, kk, status, activated_at = row
        self.owner_lookup_record = {
            "card_number": reference,
            "customer_number": str(customer_number or "—"),
            "full_name": str(full_name or "—"),
            "nik": mask_identity_number(str(nik or "")),
            "kk": mask_identity_number(str(kk or "")),
            "status": str(status or "—"),
            "activated_at": format_wib_datetime(activated_at),
        }
        self.owner_lookup_status.set("Card owner identified.")
        self.owner_lookup_customer.set(f"{full_name} · {customer_number}")
        self.owner_lookup_details.set(
            f"NIK: {mask_identity_number(str(nik or ''))}   |   KK: {mask_identity_number(str(kk or ''))}   |   "
            f"Card status: {status}   |   Activated: {format_wib_datetime(activated_at)}"
        )

    def refresh_operator_guide(self) -> None:
        if not hasattr(self, "operator_guide_button"):
            return
        if self.last_master_registered is False:
            title, detail, button, state = (
                "Daftarkan kartu master",
                "Gunakan layar awal untuk mendaftarkan satu kartu master terlebih dahulu.",
                "Menunggu pendaftaran master",
                "disabled",
            )
        elif not bool(self.last_session_open):
            title, detail, button, state = (
                "Tempel kartu master",
                "Tempel kartu master pada NFC Reader untuk mengaktifkan sesi Personalization.",
                "Menunggu kartu master",
                "disabled",
            )
        elif self.board_operation == "perso_armed":
            title, detail, button, state = (
                "Tempel kartu pelanggan baru",
                "Gunakan kartu kosong dan biarkan tetap terdeteksi sekitar 3 detik.",
                "Memeriksa kartu...",
                "disabled",
            )
        elif self.board_operation == "perso_review" and self.card_precheck == "blank":
            title, detail, button, state = (
                "Kartu baru siap",
                "Periksa kartu sudah benar, lalu lanjutkan untuk menulis dan memverifikasi kartu pelanggan.",
                "Personalisasi kartu",
                "normal",
            )
        elif self.board_operation == "perso_review":
            title, detail, button, state = (
                "Kartu tidak dapat diperso",
                "Angkat kartu ini dan gunakan kartu pelanggan baru yang kosong.",
                "Menunggu kartu baru",
                "disabled",
            )
        else:
            title, detail, button, state = (
                "Sesi Personalization siap",
                "Tekan tombol untuk memulai Personalization, lalu tempel kartu pelanggan baru.",
                "Mulai Personalization",
                "normal",
            )
        self.operator_guide_title.set(title)
        self.operator_guide_detail.set(detail)
        self.operator_guide_button.configure(text=button, state=state)
        self.refresh_dashboard_procedure()

    def refresh_dashboard_procedure(self) -> None:
        if not hasattr(self, "dashboard_steps"):
            return
        # The checklist must only mark the board ready after the firmware has
        # explicitly reported that its NFC sensor is usable.
        board_ready = bool(self.verified_port) and self.last_nfc_ready is True
        master_ready = self.last_master_registered is True
        session_ready = self.last_session_open is True
        checks = (
            ("1. Board terverifikasi", board_ready),
            ("2. Master terdaftar di EEPROM", master_ready),
            ("3. Kartu master mengaktifkan sesi Personalization", session_ready),
            ("4. Mulai personalisasi kartu pelanggan", session_ready),
        )
        for label, (text, complete) in zip(self.dashboard_steps, checks):
            label.configure(text=("✓  " if complete else "○  ") + text, fg="#25d284" if complete else "#93a5aa")
        if hasattr(self, "dashboard_action_button"):
            self.dashboard_action_button.configure(state="normal" if session_ready else "disabled")
        if hasattr(self, "nav_buttons"):
            for key in ("perso", "debug"):
                if key in self.nav_buttons:
                    self.nav_buttons[key].configure(state="normal" if session_ready else "disabled")

    def clear_technical_scan(self, reason: str | None = None) -> None:
        # A cancelled or removed card must never leave the next card tap
        # blocked behind an old in-progress scan flag.
        self.technical_scan_active = False
        if hasattr(self, "debug_tree"):
            for row in self.debug_tree.get_children():
                self.debug_tree.delete(row)
        if hasattr(self, "debug_status"):
            self.debug_status.set("Scan results cleared.")
        if reason and hasattr(self, "debug_last_event"):
            self.debug_last_event.set("Last event: " + reason)
        self.debug_readable_blocks = 0
        self.debug_denied_blocks = 0
        self.debug_wallet_states = []
        self.wallet_slot_state = ""
        self.wallet_slot_action = ""
        self.wallet_quality_ok = None
        if hasattr(self, "wallet_slot_button"):
            self.wallet_slot_button.configure(text="Check Wallet Data and Card Identity first", state="disabled")
            self.wallet_slot_button.pack_forget()
        if hasattr(self, "debug_card_summary"):
            self.debug_card_summary.set("Waiting for card")
        if hasattr(self, "debug_quality"):
            self.set_debug_card_quality(None)
            self.debug_wallet_summary.set("Not scanned")
            self.debug_protection_summary.set("Trailers are always masked")
        self.reset_technical_process()
        self.reset_personalization_process()

    def reset_technical_process(self) -> None:
        """Return the visible operator checklist to its starting state."""
        self.technical_stage_generation += 1
        if self.technical_stage_after:
            self.after_cancel(self.technical_stage_after)
            self.technical_stage_after = None
        self.technical_stage_queue = []
        self.technical_stage_active = False
        self.technical_stage_highest = 0
        for index, item in enumerate(getattr(self, "technical_process_labels", [])):
            item.configure(text=f"○  {index + 1}. {self.PRECHECK_PROCESS_STEPS[index]}", fg="#93a5aa")

    def reset_personalization_process(self) -> None:
        self.personalization_active_step = 0
        self.personalization_completed = False
        for index, item in enumerate(getattr(self, "personalization_process_labels", [])):
            item.configure(text=f"○  {index + 1}. {self.PERSONALIZATION_PROCESS_STEPS[index]}", fg="#93a5aa")

    def set_personalization_process_step(self, step: int, passed: bool | None) -> None:
        if not 1 <= step <= len(getattr(self, "personalization_process_labels", [])):
            return
        label = self.PERSONALIZATION_PROCESS_STEPS[step - 1]
        if passed is True:
            symbol, color = "✓", "#25d284"
        elif passed is False:
            symbol, color = "✕", "#ff5d68"
        else:
            symbol, color = "◌", "#55a7ff"
        self.personalization_process_labels[step - 1].configure(
            text=f"{symbol}  {step}. {label}", fg=color,
        )

    def begin_personalization_process_step(self, step: int) -> None:
        if self.personalization_active_step and self.personalization_active_step < step:
            self.set_personalization_process_step(self.personalization_active_step, True)
        self.personalization_active_step = step
        self.set_personalization_process_step(step, None)

    def clear_parsed_serial_monitor(self) -> None:
        if not hasattr(self, "parsed_serial_tree"):
            return
        for row in self.parsed_serial_tree.get_children():
            self.parsed_serial_tree.delete(row)

    def append_parsed_serial_event(self, event: dict) -> None:
        """Show safe protocol fields only; never raw frames, UID, keys, or blocks."""
        def flag(name: str, yes: str, no: str) -> str:
            if name not in event:
                return "—"
            return yes if bool(event[name]) else no

        parsed = {
            "time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "type": str(event.get("type", "unknown"))[:24],
            "code": str(event.get("code", "—"))[:48],
            "nfc": flag("nfc_ready", "READY", "DOWN"),
            "master": flag("master_registered", "YES", "NO"),
            "session": flag("session_open", "OPEN", "LOCKED"),
            "operation": str(event.get("operation", "—"))[:24],
            "card_session": str(event.get("card_session", "—"))[:12],
        }

        # Mirror only the already-parsed allowlist above. This file can be
        # tailed while the app owns COM3, without exposing raw serial frames,
        # card UID, keys, or block contents.
        try:
            self.parsed_serial_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.parsed_serial_log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(parsed, ensure_ascii=True, separators=(",", ":")) + "\n")
        except OSError:
            # Diagnostics must never interrupt the operator workflow.
            pass

        if hasattr(self, "parsed_serial_tree"):
            values = (
                format_wib_datetime(parsed["time"]), parsed["type"], parsed["code"], parsed["nfc"],
                parsed["master"], parsed["session"], parsed["operation"], parsed["card_session"],
            )
            self.parsed_serial_tree.insert("", 0, values=values)
            rows = self.parsed_serial_tree.get_children()
            for row in rows[100:]:
                self.parsed_serial_tree.delete(row)

    def set_technical_process_step(self, step: int, passed: bool | None) -> None:
        if not 1 <= step <= len(getattr(self, "technical_process_labels", [])):
            return
        item = self.technical_process_labels[step - 1]
        label = self.PRECHECK_PROCESS_STEPS[step - 1]
        if passed is True:
            symbol, color = "✓", "#25d284"
        elif passed is False:
            symbol, color = "✕", "#ff5d68"
        else:
            symbol, color = "◌", "#55a7ff"
        item.configure(text=f"{symbol}  {step}. {label}", fg=color)

    def queue_technical_steps_through(self, target: int, passed: bool = True, after: Any | None = None) -> None:
        """Hold each process step for 1 second; never leave gaps."""
        target = max(1, min(target, len(self.PRECHECK_PROCESS_STEPS)))
        first = self.technical_stage_highest + 1
        if first > target:
            return
        for step in range(first, target + 1):
            outcome = passed if step == target else True
            callback = after if step == target else None
            self.technical_stage_queue.append((step, outcome, callback))
        self.technical_stage_highest = target
        self.start_next_technical_stage()

    def queue_technical_step(self, step: int, passed: bool = True, after: Any | None = None) -> None:
        """Queue one terminal step without inventing skipped successful stages."""
        if not 1 <= step <= len(self.PRECHECK_PROCESS_STEPS):
            return
        if step <= self.technical_stage_highest:
            return
        self.technical_stage_queue.append((step, passed, after))
        self.technical_stage_highest = step
        self.start_next_technical_stage()

    def start_next_technical_stage(self) -> None:
        if self.technical_stage_active or not self.technical_stage_queue:
            return
        step, outcome, callback = self.technical_stage_queue.pop(0)
        self.technical_stage_active = True
        generation = self.technical_stage_generation
        label = self.PRECHECK_PROCESS_STEPS[step - 1]

        # Keep the active step visible for one second, without showing a
        # countdown that distracts the operator.
        item = self.technical_process_labels[step - 1]
        item.configure(text=f"◌  {step}. {label}", fg="#55a7ff")
        self.debug_status.set(f"Card Precheck {step}/{len(self.PRECHECK_PROCESS_STEPS)}: {label}")

        def finish() -> None:
            if generation != self.technical_stage_generation:
                return
            self.set_technical_process_step(step, outcome)
            self.technical_stage_active = False
            self.technical_stage_after = None
            if callback:
                callback()
            self.start_next_technical_stage()

        self.technical_stage_after = self.after(1000, finish)

    def fail_active_technical_stage(self, reason: str) -> None:
        """Stop the staged UI with a visible reason instead of a silent reset."""
        if self.technical_stage_after:
            self.after_cancel(self.technical_stage_after)
            self.technical_stage_after = None
        self.technical_stage_generation += 1
        self.technical_stage_queue = []
        self.technical_stage_active = False
        active = max(1, self.technical_stage_highest)
        self.set_technical_process_step(active, False)
        self.debug_last_event.set("Last event: " + reason)
        self.debug_status.set(reason)

    def start_final_block_check(self) -> None:
        """Start the real final check after both wallet blocks are visibly verified."""
        if (self.wallet_slot_state not in ("ready", "legacy_ready")
                or self.wallet_slot_action in ("awaiting_check", "result_pending", "confirm", "failed", "writing")):
            return
        if not self.debug_card_present:
            self.fail_active_technical_stage("Card was removed before the final Wallet Data and Card Identity check could begin.")
            return
        self.wallet_slot_action = "awaiting_check"
        self.wallet_slot_button.pack_forget()
        self.queue_technical_steps_through(9)
        self.start_final_slot_countdown()
        self.send("perso_arm")

    def begin_sequenced_technical_scan(self) -> None:
        """Start the real scan while the visible Step 3 counts down."""
        if not self.debug_card_present:
            self.fail_active_technical_stage("Card was removed before the sector scan could begin.")
            return
        self.technical_scan_active = True
        self.queue_technical_steps_through(3)
        self.debug_status.set("Starting the background sector scan on the Board...")
        self.send("technical_scan")

    def begin_sequenced_quality_test(self) -> None:
        """Run the real quality test while the visible Step 5 counts down."""
        if not self.debug_card_present:
            self.fail_active_technical_stage("Card was removed before the quality test could begin.")
            return
        self.queue_technical_steps_through(5)
        self.debug_quality.set("◌  TESTING CARD QUALITY...")
        self.debug_quality_label.configure(foreground="#55a7ff")
        self.debug_status.set("Starting the 10-read card quality test on the Board...")
        self.send("card_quality_test")

    def finish_final_block_check(self, passed: bool) -> None:
        """Keep the final precheck result visible until the card is truly removed."""
        if passed:
            self.wallet_slot_action = "confirm"
            migrating = self.wallet_slot_state == "legacy_ready"
            self.debug_wallet_summary.set("Legacy wallet ready for migration" if migrating else "Wallet Data and Card Identity ready")
            self.wallet_slot_button.configure(text="Confirm compact migration" if migrating else "Confirm card personalization", state="normal")
            self.wallet_slot_button.pack(side="left", padx=(8, 0))
            self.debug_status.set(
                "Final check PASSED — confirm adding compact metadata without changing the existing wallet."
                if migrating else "Final check PASSED — confirm writing the wallet and compact metadata."
            )
        else:
            # Keep a failed result latched as well. The same card must not be
            # treated as a fresh detection until it is physically removed.
            self.fail_or_cancel_personalization_run("failed", "final_block_check", self.card_precheck or "failed")
            self.wallet_slot_action = "failed"
            self.wallet_slot_button.configure(text="Wallet Data and Card Identity unavailable", state="disabled")
            self.wallet_slot_button.pack_forget()
            self.debug_status.set("Final check FAILED — this card will not be changed.")
        # Never clear a completed read because a display timer expired.  The
        # only valid transition to Step 10/reset is confirmed card removal.
        self.final_result_hold_until = 0.0

    def set_quality_step(self, attempt: int, passed: bool) -> None:
        # Individual read attempts are retained in firmware audit events, but
        # the operator sees the one overall quality step in the checklist.
        return

    def toggle_debug_detail(self) -> None:
        self.debug_detail_visible = not self.debug_detail_visible
        if self.debug_detail_visible:
            self.debug_detail_frame.pack(fill="both", expand=True, pady=(2, 0))
            self.debug_detail_button.configure(text="Hide full map")
        else:
            self.debug_detail_frame.pack_forget()
            self.debug_detail_button.configure(text="Show full map")

    def refresh_debug_summary(self) -> None:
        total = self.debug_readable_blocks + self.debug_denied_blocks
        self.debug_card_summary.set(f"{total} blocks checked" if total else "Checking card...")
        if self.wallet_slot_state == "ready":
            self.debug_wallet_summary.set("Wallet Data and Card Identity ready")
        elif self.wallet_slot_state == "legacy_ready":
            self.debug_wallet_summary.set("Wallet Data ready · Card Identity blank for migration")
        elif self.wallet_slot_state == "already_used":
            self.debug_wallet_summary.set("Wallet Data and Card Identity already personalized")
        elif self.wallet_slot_state == "unavailable":
            self.debug_wallet_summary.set("Wallet Data and Card Identity unavailable")
        elif self.wallet_quality_ok is False:
            self.debug_wallet_summary.set("Quality must be 10/10")
        elif self.wallet_quality_ok is True:
            self.debug_wallet_summary.set("Checking Wallet Data and Card Identity")
        elif not self.debug_wallet_states:
            self.debug_wallet_summary.set("Waiting for 10/10 quality")
        elif all(state == "read_ok" for state in self.debug_wallet_states):
            self.debug_wallet_summary.set("Wallet readable")
        else:
            self.debug_wallet_summary.set("Wallet access required")
        self.debug_protection_summary.set(f"{self.debug_readable_blocks} data readable · {self.debug_denied_blocks} restricted")

    def begin_personalization_commit(self) -> bool:
        """Reserve ownership in the Database before sending the card write."""
        if self.wallet_slot_action != "confirm":
            messagebox.showerror("Card Personalization", "Card Precheck is not ready for writing.")
            return False
        if not self.active_run_id or self.active_run_customer_id != self.selected_customer_id:
            messagebox.showerror("Card Personalization", "The customer/run database link is missing. The card will not be changed.")
            return False
        if self.refresh_selected_customer_card_status():
            messagebox.showerror("Card Personalization", "This customer already has an active card. The card will not be changed.")
            return False
        if self.active_card_reference is None:
            messagebox.showerror("Card Personalization", "Card Number has not been allocated. The card will not be changed.")
            return False
        if not self.reserve_personalization_ownership():
            return False
        self.reset_personalization_process()
        self.personalization_active_step = 1
        self.set_personalization_process_step(1, True)
        self.wallet_slot_action = "writing"
        self.wallet_slot_button.configure(text="Personalizing card...", state="disabled")
        self.debug_status.set("Personalization 1/7: Database reservation saved. Starting card preparation...")
        self.send("perso_commit", card_reference=self.active_card_reference)
        commit_token = self.technical_reset_token
        self.after(3500, lambda token=commit_token: self.verify_commit_started(token))
        return True

    def fixed_slot_action(self) -> None:
        if self.wallet_slot_action == "confirm":
            migrating = self.wallet_slot_state == "legacy_ready"
            if messagebox.askyesno(
                "Confirm personalization",
                f"Assign this card to {self.selected_customer_name.get()} ({self.selected_customer_number.get()})?\n\n"
                + ("The existing Wallet Data will be preserved. Card Number, counter, and security data will be added to Card Identity."
                   if migrating else
                   "This will write Wallet Data plus Card Number, counter, and security data to Card Identity."),
            ):
                self.begin_personalization_commit()

    def begin_remove_personalization(self) -> None:
        """Request removal of Card Identity only; Wallet Data stays untouched."""
        if self.last_session_open is not True:
            self.debug_status.set("Remove personalization requires an active master session.")
            return
        if not self.debug_card_present or self.wallet_slot_state != "already_used":
            self.debug_status.set("Remove personalization is available only for the verified card currently on the reader.")
            return
        if self.wallet_slot_action in ("remove_arming", "removing"):
            return
        self.remove_request_token = getattr(self, "remove_request_token", 0) + 1
        remove_token = self.remove_request_token
        self.wallet_slot_action = "remove_arming"
        self.debug_status.set("Preparing the card for verified personalization removal. Keep it on the NFC Reader...")
        self.debug_last_event.set("Last event: remove personalization confirmed; Board review started.")
        # A background Technical Scan proves the blocks are readable, but the
        # firmware intentionally accepts mutation only from PersoReview.
        # Arm that dedicated review first; the precheck result below will
        # automatically issue the actual remove command for a secure card.
        self.send("perso_arm")
        self.after(6500, lambda token=remove_token: self.verify_remove_review_started(token))

    def verify_remove_review_started(self, token: int) -> None:
        if token != getattr(self, "remove_request_token", 0) or self.wallet_slot_action != "remove_arming":
            return
        self.wallet_slot_action = "remove_failed"
        self.debug_status.set("Board did not complete the removal review. Keep the card flat and retry.")
        self.debug_last_event.set("Last event: remove personalization review timed out.")

    def verify_remove_started(self, token: int) -> None:
        """Stop showing an endless removal state when the Board ignores the command."""
        if token != getattr(self, "remove_request_token", 0) or self.wallet_slot_action != "removing":
            return
        self.wallet_slot_action = "remove_failed"
        self.debug_status.set(
            "Board did not acknowledge remove personalization. The installed Board firmware may not support this command yet."
        )
        self.debug_last_event.set(
            "Last event: remove personalization command timed out before Board progress started."
        )

    def verify_commit_started(self, token: int) -> None:
        if token != self.technical_reset_token or self.wallet_slot_action != "writing":
            return
        if self.personalization_active_step > 1:
            return
        self.fail_or_cancel_personalization_run("failed", "perso_commit", "stm32_ack_timeout")
        self.wallet_slot_action = "failed_write"
        self.set_personalization_process_step(1, False)
        self.debug_status.set("Board did not acknowledge personalization. The card was not confirmed written; remove it and retry.")
        self.debug_last_event.set("Last event: personalization command timed out before Board progress started.")

    def start_final_slot_countdown(self) -> None:
        """Keep the UI visibly alive while the board performs its 3 s check."""
        self.final_check_seconds = 3
        self.final_check_zero_ticks = 0
        self.tick_final_slot_countdown()

    def tick_final_slot_countdown(self) -> None:
        if self.wallet_slot_action != "awaiting_check":
            return
        if self.final_check_seconds > 0:
            self.debug_status.set(f"Final check in progress — keep card on reader ({self.final_check_seconds}s)")
            self.final_check_seconds -= 1
        else:
            self.final_check_zero_ticks += 1
            if self.final_check_zero_ticks >= 5:
                # The UI timeout must also clear the board's ArmPerso state;
                # otherwise the next card tap is still treated as an old check.
                self.wallet_slot_action = ""
                self.send("cancel")
                self.clear_technical_scan()
                self.debug_status.set("Final check timed out — card was removed or not stable. Tap it again.")
                return
            self.debug_status.set("Final check finishing...")
        self.after(500, self.tick_final_slot_countdown)

    def confirm_technical_card_removed(self, token: int) -> None:
        """Accept removal only if no re-detection arrived during debounce."""
        if token != self.technical_reset_token or self.debug_card_present:
            return
        if self.personalization_completed or self.wallet_slot_action == "failed_write":
            self.begin_personalization_process_step(6)
            self.debug_status.set("Personalization 7/7: card removed — completing process.")
            self.debug_last_event.set("Last event: card removal confirmed; process reset follows.")
            self.after(1000, lambda current=token: self.finish_personalization_removal(current))
            return
        self.debug_status.set("Card removed — resetting the incomplete Card Precheck.")
        self.debug_last_event.set("Last event: card removal confirmed; incomplete Card Precheck reset follows.")
        self.after(1000, lambda current=token: self.reset_technical_debug_after_removal(current))

    def finish_personalization_removal(self, token: int) -> None:
        if token != self.technical_reset_token or self.debug_card_present:
            return
        self.set_personalization_process_step(7, True)
        self.after(1000, lambda current=token: self.reset_technical_debug_after_removal(current))

    def reset_technical_debug_after_removal(self, token: int) -> None:
        """Reset only after the operator can see the terminal removal step."""
        if token != self.technical_reset_token or self.debug_card_present:
            return
        completed = self.personalization_completed
        self.clear_technical_scan("Card was removed. The previous personalization process was reset.")
        self.debug_status.set("Waiting for a card...")
        self.active_run_id = None
        self.active_run_customer_id = None
        self.active_run_card_session = None
        self.active_card_reference = None
        if completed:
            self.clear_customer_form()
            self.load_customers()
            self.show_page("customers")

    def set_debug_scan_stability(self, stable: bool | None) -> None:
        if not hasattr(self, "debug_stability"):
            return
        if stable is None:
            text, color = "○  STABILITAS BELUM DIUJI", "#93a5aa"
        elif stable:
            text, color = "✓  SCAN STABIL", "#25d284"
        else:
            text, color = "!  KARTU TIDAK STABIL", "#ff5d68"
        self.debug_stability.set(text)
        if hasattr(self, "debug_stability_label"):
            self.debug_stability_label.configure(foreground=color)

    def set_debug_rf_link(self, stable: bool | None) -> None:
        """Operational RF-link estimate, never presented as calibrated RF power."""
        if not hasattr(self, "debug_rf_link"):
            return
        if stable is None:
            text, color = "○  RF LINK BELUM DINILAI", "#93a5aa"
        elif stable:
            text, color = "✓  RF LINK NORMAL (ESTIMASI)", "#25d284"
        else:
            text, color = "!  RF LINK INTERMITEN (ESTIMASI)", "#ff5d68"
        self.debug_rf_link.set(text)
        if hasattr(self, "debug_rf_link_label"):
            self.debug_rf_link_label.configure(foreground=color)

    def set_debug_card_quality(self, success: int | None, attempts: int = 10) -> None:
        if not hasattr(self, "debug_quality"):
            return
        if success is None:
            text, color = "○  CARD QUALITY NOT TESTED", "#93a5aa"
        elif success >= 9:
            text, color = f"✓  GOOD CARD ({success}/{attempts})", "#25d284"
        elif success >= 6:
            text, color = f"!  SUSPECT CARD ({success}/{attempts})", "#f0bd4f"
        else:
            text, color = f"✕  POOR CARD ({success}/{attempts})", "#ff5d68"
        self.debug_quality.set(text)
        if hasattr(self, "debug_quality_label"):
            self.debug_quality_label.configure(foreground=color)

    def start_technical_scan(self) -> None:
        if not self.last_session_open:
            return
        self.clear_technical_scan()
        self.technical_scan_active = True
        self.debug_status.set("Scanning the currently detected card...")
        self.send("technical_scan")

    def start_card_quality_test(self) -> None:
        if not self.last_session_open:
            return
        self.debug_quality.set("◌  TESTING CARD QUALITY...")
        self.debug_quality_label.configure(foreground="#55a7ff")
        self.send("card_quality_test")

    def start_coverage_test(self) -> None:
        """Guide a technician through five intentional placement checks."""
        if not self.last_session_open:
            return
        self.coverage_active = True
        self.coverage_index = 0
        self.coverage_scores = []
        self._prepare_coverage_position()

    def _prepare_coverage_position(self) -> None:
        position = self.coverage_positions[self.coverage_index]
        self.debug_quality.set(f"◌  COVERAGE {self.coverage_index + 1}/5: {position}")
        self.debug_quality_label.configure(foreground="#55a7ff")
        self.debug_status.set(f"Place the card at {position}, then click Test position.")
        self.coverage_button.configure(text=f"Test {position} position", command=self.run_coverage_position)

    def run_coverage_position(self) -> None:
        if not self.coverage_active:
            return
        self.debug_status.set("Testing this position: 10 reads without writing the card.")
        self.send("card_quality_test")

    def finish_coverage_test(self) -> None:
        good_positions = sum(1 for success, attempts in self.coverage_scores if attempts and success / attempts >= 0.9)
        if good_positions == 5:
            text, color = "✓  GOOD CARD COVERAGE (5/5)", "#25d284"
        elif good_positions >= 3:
            text, color = f"!  LIMITED COVERAGE ({good_positions}/5)", "#f0bd4f"
        else:
            text, color = f"✕  POOR CARD COVERAGE ({good_positions}/5)", "#ff5d68"
        self.debug_quality.set(text)
        self.debug_quality_label.configure(foreground=color)
        self.debug_status.set("Coverage test complete. It measures read area, not sector keys.")
        self.coverage_active = False
        self.coverage_button.configure(text="Run 5-point coverage test", command=self.start_coverage_test)

    def handle_technical_event(self, event: dict) -> None:
        code = event.get("code", "")
        if code == "wallet_slot":
            self.wallet_slot_state = event.get("state", "unavailable")
            slot_ready = self.wallet_slot_state in ("ready", "legacy_ready")
            self.update_personalization_run(
                result="ready" if slot_ready else "failed",
                failure_stage=None if slot_ready else "wallet_slot",
                failure_code=None if slot_ready else self.wallet_slot_state,
            )
            self.refresh_debug_summary()
            if slot_ready:
                self.queue_technical_steps_through(8, after=self.start_final_block_check)
            elif self.wallet_slot_state == "already_used":
                self.fail_or_cancel_personalization_run("failed", "wallet_slot", "already_used")
                self.wallet_slot_action = ""
                self.wallet_slot_button.configure(text="Wallet Data and Card Identity already used", state="disabled")
                self.wallet_slot_button.pack_forget()
                self.queue_technical_steps_through(
                    8, passed=False,
                    after=lambda: self.debug_status.set("This card already has valid Wallet Data and Card Identity. No overwrite is offered."),
                )
            else:
                self.fail_or_cancel_personalization_run("failed", "wallet_slot", self.wallet_slot_state)
                self.wallet_slot_action = ""
                self.wallet_slot_button.configure(text="Wallet Data and Card Identity unavailable", state="disabled")
                self.wallet_slot_button.pack_forget()
                self.queue_technical_steps_through(
                    8, passed=False,
                    after=lambda: self.debug_status.set("Wallet Data and Card Identity cannot be verified as authorized card storage."),
                )
        elif code == "scan_started":
            self.technical_scan_active = True
            self.queue_technical_steps_through(3)
            self.debug_card_summary.set("Scanning 16 sectors...")
        elif code == "scan_summary":
            self.debug_readable_blocks = int(event.get("readable", 0))
            self.debug_denied_blocks = int(event.get("restricted", 0))
            self.update_personalization_run(
                sectors_checked=16,
                readable_blocks=self.debug_readable_blocks,
                restricted_blocks=self.debug_denied_blocks,
            )
            self.refresh_debug_summary()
        elif code == "quality_started":
            self.queue_technical_steps_through(5)
            self.debug_quality.set("◌  TESTING CARD QUALITY...")
            self.debug_quality_label.configure(foreground="#55a7ff")
            self.debug_card_summary.set("Card detected")
        elif code == "quality_attempt":
            if event.get("source") == "auto":
                self.set_quality_step(int(event.get("attempt", 0)), bool(event.get("passed", False)))
        elif code == "card_quality":
            success, attempts = int(event.get("success", 0)), int(event.get("attempts", 10))
            if self.coverage_active and event.get("source") == "manual":
                self.coverage_scores.append((success, attempts))
                self.coverage_index += 1
                if self.coverage_index >= len(self.coverage_positions):
                    self.finish_coverage_test()
                else:
                    self._prepare_coverage_position()
            elif not self.coverage_active:
                self.update_personalization_run(quality_success=success, quality_attempts=attempts)
                self.set_debug_card_quality(success, attempts)
                if event.get("source") == "auto":
                    self.wallet_quality_ok = success == attempts
                    if self.wallet_quality_ok:
                        self.debug_wallet_summary.set("Checking Wallet Data and Card Identity")
                        self.queue_technical_steps_through(
                            6,
                            after=lambda: self.debug_status.set("Quality passed 10/10. Checking Wallet Data and Card Identity now..."),
                        )
                    else:
                        self.fail_or_cancel_personalization_run("failed", "card_quality", f"{success}/{attempts}")
                        self.wallet_slot_action = ""
                        self.wallet_slot_button.configure(text="Quality must be 10/10", state="disabled")
                        self.debug_wallet_summary.set("Quality must be 10/10")
                        self.queue_technical_steps_through(
                            6, passed=False,
                            after=lambda: self.debug_status.set("Wallet Data and Card Identity were not checked because card quality was below 10/10."),
                        )
                else:
                    self.debug_status.set(f"Quality test complete. Average response {int(event.get('average_ms', 0))} ms.")
        elif code == "scan_quality":
            # Scan quality is reflected by the dedicated card-quality test;
            # this event remains available for diagnostics but is not another
            # operator-facing indicator.
            pass
        elif code == "scan_block":
            state = event.get("state", "-")
            block = event.get("block", -1)
            if event.get("kind") == "data":
                if state == "read_ok":
                    self.debug_readable_blocks += 1
                elif state == "no_authorized_read":
                    self.debug_denied_blocks += 1
            if block in (8, 9, 10):
                self.debug_wallet_states.append(state)
            # A failed authentication has no trustworthy data payload.  The
            # firmware deliberately sends an empty/zero work buffer in that
            # case, so never render it as if it were card content.
            data_display = event.get("data", "") if state == "read_ok" else "—"
            self.debug_tree.insert("", "end", values=(
                event.get("sector", "-"), block,
                event.get("kind", "data"), state, data_display,
            ))
            self.refresh_debug_summary()
        elif code == "scan_complete":
            self.queue_technical_steps_through(4, after=self.begin_sequenced_quality_test)
            self.technical_scan_active = False
            self.debug_card_summary.set("16 sectors checked")
            self.debug_last_event.set("Last event: all 16 sectors scanned successfully.")

    def run_guided_action(self) -> None:
        if self.board_operation == "perso_review" and self.card_precheck == "blank":
            self.confirm_perso()
        elif self.last_session_open:
            self.send("perso_arm")

    def _metric_card(self, parent: ttk.Frame, column: int, icon: str, title: str, variable: tk.StringVar, subtitle: str | tk.StringVar, color: str) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(18, 16))
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 10, 0))
        ttk.Label(card, text=icon + "  " + title, style="MetricSub.TLabel", foreground=color).pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="Metric.TLabel").pack(anchor="w", pady=(8, 2))
        if isinstance(subtitle, tk.StringVar):
            ttk.Label(card, textvariable=subtitle, style="Card.TLabel", foreground="#8fa1a7").pack(anchor="w")
        else:
            ttk.Label(card, text=subtitle, style="Card.TLabel", foreground="#8fa1a7").pack(anchor="w")

    def update_master_ui(self, registered: bool) -> None:
        """Give the operator an immediate, actionable master-card state."""
        self.master_status.set("Registered" if registered else "Not registered")
        if hasattr(self, "master_badge"):
            self.master_badge.configure(
                text="MASTER: REGISTERED" if registered else "MASTER: NOT REGISTERED",
                fg="#20d889" if registered else "#f0bd4f",
            )
        self.master_hint.set(
            "Master ready — tap master to open session"
            if registered
            else "No master — register a master card"
        )
        if hasattr(self, "enroll"):
            self.enroll.configure(state="disabled" if registered else "normal")
        if hasattr(self, "reset"):
            self.reset.configure(state="normal" if registered else "disabled")
        self.refresh_operator_guide()

    def show_master_tapped(self) -> None:
        """Acknowledge a master-card tap without revealing any card identity."""
        self.card.set("Master card detected")
        if hasattr(self, "master_badge"):
            self.master_badge.configure(text="MASTER: DETECTED", fg="#55a7ff")
        if self.master_tap_after:
            self.after_cancel(self.master_tap_after)
        self.master_tap_after = self.after(1800, lambda: self.update_master_ui(True))

    def update_session_ui(self, open_session: bool) -> None:
        self.session.set("Open" if open_session else "Locked")
        if hasattr(self, "session_badge"):
            self.session_badge.configure(
                text="SESSION: OPEN" if open_session else "SESSION: LOCKED",
                fg="#20d889" if open_session else "#93a5aa",
            )
        if hasattr(self, "arm"):
            self.arm.configure(state="normal" if open_session else "disabled")
        if hasattr(self, "debug_scan_button"):
            self.debug_scan_button.configure(state="normal" if open_session else "disabled")
        if hasattr(self, "coverage_button"):
            self.coverage_button.configure(state="normal" if open_session else "disabled")
        self.apply_session_access(open_session)
        # Step 1 is shown with the rest of the ordered 10-step flow when a
        # new technical scan actually begins.  Do not pre-check it here.
        self.reset_technical_process()
        self.reset_personalization_process()
        self.refresh_operator_guide()

    def require_open_session(self, title: str) -> bool:
        if self.last_session_open is True:
            return True
        messagebox.showwarning(title, "Session is locked. Tap the registered master card to open the session first.")
        return False

    def apply_session_access(self, open_session: bool) -> None:
        """Make a locked master session a hard UI and customer-data boundary."""
        if hasattr(self, "nav_buttons"):
            for button in self.nav_buttons.values():
                button.configure(state="normal" if open_session else "disabled")
        if hasattr(self, "customer_session_widgets"):
            for widget, unlocked_state in self.customer_session_widgets:
                try:
                    widget.configure(state=unlocked_state if open_session else "disabled")
                except tk.TclError:
                    if open_session:
                        widget.state(["!disabled"])
                    else:
                        widget.state(["disabled"])
        if open_session:
            self.load_customers()
            return
        if self.customer_search_after:
            self.after_cancel(self.customer_search_after)
            self.customer_search_after = None
        if getattr(self, "current_page", "home") != "home":
            self.show_page("home")
        self.clear_customer_form()

    def refresh_ports(self, silent: bool = False) -> None:
        try:
            from serial.tools import list_ports  # type: ignore
            ports = [port.device for port in list_ports.comports()]
        except ImportError:
            ports = []
        self.port_selector.configure(values=ports)
        if not silent:
            self.status.set("COM list updated" if ports else "No COM ports detected")

    def connect(self) -> None:
        self.disconnect()
        if self.simulation.get():
            self.status.set("Simulation connected")
            self.write_log("Simulation active. Use virtual cards through the test menu.")
            self.send("status_request")
            return
        try:
            self.transport = SerialTransport(self.port.get().strip())
            self.status.set("Connected " + self.port.get().strip())
            self.send("status_request")
        except Exception as error:
            self.status.set("Connection failed")
            messagebox.showerror("Koneksi board", str(error))

    def disconnect(self) -> None:
        if self.transport:
            self.transport.close()
        self.transport = None
        self.verified_port = None

    def send(self, command: str, **parameters: Any) -> None:
        message = request(command, **parameters)
        try:
            events = self.simulator.send(message) if self.simulation.get() else self._send_real(message)
            for event in events:
                self.handle_event(event)
        except Exception as error:
            self.handle_event({"type": "error", "code": str(error)})

    def simulate_card(self, state: str) -> None:
        if not self.simulation.get():
            self.status.set("Simulasi harus aktif")
            return
        for event in self.simulator.present_card(state):
            self.handle_event(event)

    def simulate_remove(self) -> None:
        if not self.simulation.get():
            self.status.set("Simulasi harus aktif")
            return
        for event in self.simulator.remove_card():
            self.handle_event(event)

    def _send_real(self, message: dict) -> list[dict]:
        if not self.transport:
            raise RuntimeError("Board is not connected")
        self.transport.send(message)
        return []

    def begin_hold(self, kind: str) -> None:
        if self.hold_command:
            return
        if kind == "register_master" and not self.master_registration_card_present:
            return
        begin = kind + "_begin"
        commit = kind + "_commit"
        self.send(begin)
        self.hold_seconds = 0
        self.hold_command = commit
        if self.startup_phase == "master_registration" and kind == "register_master":
            self.set_loading("Mendaftarkan kartu master", "Tahan tombol dan kartu: 0 / 10 detik", done=False)
        self.hold_after = self.after(1000, self._tick_hold)

    def _tick_hold(self) -> None:
        if not self.hold_command:
            return
        self.hold_seconds += 1
        self.status.set(f"Tahan konfirmasi {self.hold_seconds}/10 detik")
        if self.startup_phase == "master_registration" and self.hold_command == "register_master_commit":
            self.set_loading(
                "Mendaftarkan kartu master",
                f"Tahan tombol dan kartu: {self.hold_seconds} / 10 detik",
                done=False,
            )
        if self.hold_seconds >= 10:
            command, self.hold_command = self.hold_command, None
            self.send(command)
            return
        self.hold_after = self.after(1000, self._tick_hold)

    def cancel_hold(self) -> None:
        if not self.hold_command:
            return
        if self.hold_after:
            self.after_cancel(self.hold_after)
        self.hold_after = None
        self.hold_command = None
        self.send("cancel")
        self.status.set("Konfirmasi tahan dibatalkan")
        if self.startup_phase == "master_registration":
            self.set_loading("Menunggu kartu master", "Pendaftaran dibatalkan. Tempel kartu dan tahan 10 detik.", done=False)

    def confirm_perso(self) -> None:
        if messagebox.askyesno("Konfirmasi Personalization", "Personalisasi kartu baru sebagai aktif, saldo 0 L, dan jadwal belum diatur?"):
            if self.active_card_reference is None:
                messagebox.showerror("Card Personalization", "Card Number has not been allocated. The card will not be changed.")
                return
            self.send("perso_commit", card_reference=self.active_card_reference)

    def poll(self) -> None:
        if self.transport:
            try:
                for event in self.transport.poll():
                    self.handle_event(event)
            except (OSError, ProtocolError) as error:
                self.disconnect()
                if self.dashboard_ready:
                    self.handle_event({"type": "error", "code": str(error)})
                elif self.startup_phase in ("device_discovery", "background_discovery"):
                    self.after(80, self.try_next_device_port)
        self.after(80, self.poll)

    def tick_liveness(self) -> None:
        """Small independent heartbeat: proves UI and STM32 event loop live."""
        self.liveness_phase = (self.liveness_phase + 1) % 2
        app_dot = "●" if self.liveness_phase else "◌"
        now = time.monotonic()
        age = now - self.last_stm_event_at
        if self.transport and age <= 2.5:
            stm_dot, state = ("●" if self.liveness_phase else "◌"), "BOARD alive"
        elif self.transport:
            stm_dot, state = "○", "BOARD checking"
        else:
            stm_dot, state = "○", "BOARD offline"
        self.debug_liveness.set(f"{app_dot} APP  |  {stm_dot} {state}")
        if self.transport and now - self.last_stm_status_request_at >= 2.0:
            self.last_stm_status_request_at = now
            self.send("status_request")
        # The STM32 is the sole PN532 I2C poller.  The desktop never starts a
        # second read, preventing serial-triggered probes from colliding with
        # the reader's continuous 100 ms presence check.
        self.after(350, self.tick_liveness)

    def handle_event(self, event: dict) -> None:
        if event.get("profile") == "smartdispenser_perso":
            self.last_stm_event_at = time.monotonic()
        event_type, code = event.get("type", "error"), event.get("code", "unknown")
        self.append_parsed_serial_event(event)
        # Keep the final result visible even if a brief NFC re-detection starts
        # a new background scan while the result hold is active.
        if time.monotonic() < self.final_result_hold_until:
            if event_type == "technical":
                return
            if event_type == "card" and code == "detected":
                return
        if not self.dashboard_ready:
            # Hanya balasan protokol yang tepat yang boleh melewati splash.
            # Data serial acak atau perangkat lain pada COM tidak dianggap alat.
            if self.startup_phase == "device_discovery" and is_perso_ready(event) and self.startup_wait_port:
                self.last_nfc_ready = event.get("nfc_ready")
                self.last_master_registered = event.get("master_registered")
                self.last_session_open = event.get("session_open")
                self.finish_startup_device(self.startup_wait_port)
            elif self.startup_phase == "master_registration":
                if "master_registered" in event:
                    self.last_master_registered = bool(event["master_registered"])
                if event_type == "card" and code == "detected":
                    self.master_registration_card_present = True
                    self.set_master_registration_button_enabled(True)
                    self.set_loading("Master card detected", "Keep the card on the reader and hold the button for 10 seconds.", done=False)
                elif event_type == "card" and code == "removed":
                    self.master_registration_card_present = False
                    self.set_master_registration_button_enabled(False)
                    if self.hold_command == "register_master_commit":
                        self.cancel_hold()
                    self.set_loading("Waiting for master card", "Tap the master card, then hold the button for 10 seconds.", done=False)
                elif event_type == "status" and code == "master_hold_ready":
                    self.set_loading("Master card ready", "Release the button to save registration.", done=False)
                elif event_type == "result" and code == "master_registered":
                    self.master_registration_card_present = False
                    self.set_master_registration_button_enabled(False)
                    self.loading_master_button.place_forget()
                    self.set_loading("Master card registered", "Opening workspace...", done=True)
                    self.after(700, self.show_dashboard)
                elif event_type == "error":
                    self.set_loading("Master registration did not complete", "Tap the card and hold the button for 10 seconds.", done=False)
            elif self.startup_phase == "session_open":
                if "session_open" in event:
                    self.last_session_open = bool(event["session_open"])
                if event_type == "card" and code == "detected":
                    self.session_gate_card_present = True
                    self.set_loading("Card detected", "Checking whether this is the registered master card...", done=False)
                    self.after(1000, self.show_unverified_session_card_feedback)
                elif event_type == "card" and code == "removed":
                    self.session_gate_card_present = False
                    self.set_loading("Activate Personalization session", "Tap the master card on the NFC Reader.", done=False)
                if self.last_session_open is True and not self.session_open_feedback_pending:
                    self.session_open_feedback_pending = True
                    # Some firmware revisions report only session_opened and do
                    # not emit a separate generic card-detected frame. Show the
                    # two truthful stages in order so neither result disappears.
                    if event_type == "master" and code == "session_opened":
                        self.session_gate_card_present = True
                        self.set_loading("Card detected", "Checking whether this is the registered master card...", done=False)
                        self.after(350, self.show_verified_master_feedback)
                    else:
                        self.show_verified_master_feedback()
            elif self.startup_phase == "session_lock":
                if "session_open" in event:
                    self.last_session_open = bool(event["session_open"])
                # The STM32 may answer with either the explicit lock event or
                # a regular status frame proving session_open is already false.
                if (event_type == "status" and code == "session_locked") or self.last_session_open is False:
                    self.complete_session_lock()
            return
        if self.background_scan and self.startup_phase == "background_discovery" and is_perso_ready(event) and self.startup_wait_port:
            self.finish_startup_device(self.startup_wait_port)
        if isinstance(event.get("operation"), str):
            self.board_operation = event["operation"]
        # Error/progress event yang ringkas boleh tidak membawa status global.
        # Jangan membuat status visual terlihat "terkunci" hanya karena field
        # tersebut memang tidak dikirim pada satu event.
        if "master_registered" in event:
            master_registered = bool(event["master_registered"])
            if master_registered != self.last_master_registered:
                self.last_master_registered = master_registered
                self.update_master_ui(master_registered)
        if "session_open" in event:
            session_open = bool(event["session_open"])
            # A compact board event may repeat session_open on every scan
            # update.  Only a real session transition may reset the staged UI.
            if session_open != self.last_session_open:
                self.last_session_open = session_open
                self.update_session_ui(session_open)
        if "nfc_ready" in event:
            self.last_nfc_ready = bool(event["nfc_ready"])
        if event_type == "technical":
            self.handle_technical_event(event)
        elif event_type == "card_test":
            self.confirm_card_test_start()
            if code == "detected":
                self.card_test_detection_count += 1
                self.card_test_status.set("Card detected — NFC reader is working.")
                self.card_test_count.set(f"{self.card_test_detection_count} card detection{'s' if self.card_test_detection_count != 1 else ''}")
            elif code == "removed":
                self.card_test_status.set("Card removed — waiting for another card.")
        elif event_type == "owner_lookup":
            self.confirm_owner_lookup_start()
            if code == "identified":
                try:
                    reference = int(event.get("card_reference", 0))
                except (TypeError, ValueError):
                    reference = 0
                if reference > 0:
                    self.show_card_owner(reference)
                else:
                    self.owner_lookup_status.set("Card response did not contain a valid reference.")
            elif code == "legacy_card":
                self.owner_lookup_record = {}
                self.owner_lookup_status.set("Legacy card detected — no compact owner reference.")
                self.owner_lookup_reference.set("Card Number: —")
                self.owner_lookup_customer.set("Owner: cannot be identified from this card")
                self.owner_lookup_details.set("Migrate/personalize this card first. The card was not changed.")
            elif code == "unrecognized":
                self.owner_lookup_record = {}
                self.owner_lookup_status.set("Card detected, but it is not a valid personalized project card.")
                self.owner_lookup_reference.set("Card Number: —")
                self.owner_lookup_customer.set("Owner: unknown")
                self.owner_lookup_details.set("Security/format verification or Sector 2 read failed. The card was not changed.")
            elif code == "removed":
                self.owner_lookup_record = {}
                self.owner_lookup_status.set("Card removed — waiting for another personalized card.")
                self.owner_lookup_reference.set("Card Number: —")
                self.owner_lookup_customer.set("Owner: —")
                self.owner_lookup_details.set("Reader remains active and read-only.")
        elif event_type == "status" and code == "card_test_ready":
            self.confirm_card_test_start()
            self.card_test_status.set("Waiting for any card.")
        elif event_type == "status" and code == "card_test_stopped":
            self.card_test_confirmed = False
        elif event_type == "status" and code == "owner_lookup_ready":
            self.confirm_owner_lookup_start()
        elif event_type == "status" and code == "owner_lookup_stopped":
            self.owner_lookup_confirmed = False
        if event.get("nfc_ready") is False:
            self.card.set("NFC board not ready")
            self.set_card_indicator(False)
            self.set_nfc_controls(False)
        elif event.get("nfc_ready") is True:
            self.set_nfc_controls(True)
        # A card event also carries nfc_ready=true. Readiness and card payload
        # must be handled independently; an elif here swallowed every
        # non-master detected/removed event before Technical Debug saw it.
        if event_type == "card":
            self.debug_card_present = code == "detected"
            if code == "detected":
                self.final_result_token += 1
                self.technical_reset_token += 1
                if (getattr(self, "current_page", "") == "debug"
                        and self.last_session_open and self.selected_customer_id is not None
                        and not self.active_run_id and not self.technical_scan_active
                        and self.wallet_slot_action not in (
                            "awaiting_check", "result_pending", "confirm", "failed", "writing",
                            "completed", "failed_write", "remove_arming", "removing", "removed", "remove_failed"
                        )):
                    # Steps 1 and 2 are a deliberate preflight.  The STM32
                    # scan is not sent until their two 1-second holds
                    # have finished.
                    if not self.start_personalization_run(event):
                        self.debug_status.set("Personalization blocked: select an eligible customer and verify the Database.")
                        return
                    self.clear_technical_scan("New card detected. Starting the ordered Card Precheck.")
                    self.debug_card_present = True
                    self.debug_card_summary.set("Card detected")
                    self.queue_technical_steps_through(2, after=self.begin_sequenced_technical_scan)
            if code != "detected":
                if self.active_run_id and not self.personalization_completed and self.wallet_slot_action != "failed_write":
                    self.fail_or_cancel_personalization_run("cancelled", "card_presence", "card_removed")
                if time.monotonic() < self.final_result_hold_until:
                    if self.wallet_slot_action == "confirm":
                        self.wallet_slot_action = ""
                        self.wallet_slot_button.pack_forget()
                        self.send("cancel")
                    self.set_card_indicator(False)
                    return
                # Technical Debug represents the card currently on the reader.
                # Clear its prior decision as soon as that card is removed.
                if self.wallet_slot_action in ("awaiting_check", "result_pending", "confirm", "failed"):
                    self.wallet_slot_action = ""
                    self.send("cancel")
                # A PN532 authentication transition can briefly resemble a
                # removal. Confirm absence before Step 10; re-detection of the
                # same physical card invalidates this token.
                self.technical_reset_token += 1
                reset_token = self.technical_reset_token
                self.after(800, lambda token=reset_token: self.confirm_technical_card_removed(token))
                self.debug_status.set("Checking whether the card was really removed...")
                self.debug_last_event.set("Last event: possible card removal; waiting for confirmation.")
            self.set_card_indicator(code == "detected")
            if self.master_gate_card_label:
                self.master_gate_card_label.configure(
                    text="●  CARD DETECTED" if code == "detected" else "○  WAITING FOR CARD",
                    fg="#25d284" if code == "detected" else "#93a5aa",
                )
            if code == "detected" and event.get("operation") in ("perso_armed", "master_enroll"):
                self.card.set("Detected — waiting for stable card")
            else:
                self.card.set("Detected" if code == "detected" else "No card")
        elif event_type == "master" and code == "tapped":
            self.show_master_tapped()
        elif event_type == "status" and code == "nfc_unavailable":
            self.card.set("NFC board not ready")
        elif event_type == "status" and code == "nfc_recovered":
            self.card.set("NFC recovered — tap a card")
        elif event_type == "precheck":
            self.card_precheck = code
            if self.wallet_slot_action == "remove_arming":
                labels = {"already_personalized": "Sudah dipersonalisasi", "blank": "Card Identity already blank", "legacy_personalized": "Legacy card", "foreign_or_invalid": "Kartu tidak dapat diverifikasi"}
                self.card.set(labels.get(code, code))
                self.commit.configure(state="disabled")
                if code == "already_personalized":
                    self.wallet_slot_action = "removing"
                    self.debug_status.set("Removal review passed. Removing Card Identity while preserving Wallet Data...")
                    self.debug_last_event.set("Last event: verified personalized card; removal started.")
                    self.send("perso_remove")
                    remove_token = getattr(self, "remove_request_token", 0)
                    self.after(3500, lambda token=remove_token: self.verify_remove_started(token))
                else:
                    self.wallet_slot_action = "remove_failed"
                    self.debug_status.set(f"Remove personalization rejected after card review: {code}.")
                    self.debug_last_event.set("Last event: Card Identity was not removed.")
                self.status.set(f"{event_type}: {code}")
                if event.get("nfc_ready") is True:
                    self.set_connection_connected(self.port.get())
                self.refresh_operator_guide()
                self.write_log(f"{event_type}: {code}")
                self.audit(event_type, code, event)
                return
            precheck_ready = code in ("blank", "legacy_personalized")
            self.update_personalization_run(precheck_result=code, result="ready" if precheck_ready else "failed")
            labels = {"blank": "Kartu baru siap", "legacy_personalized": "Kartu lama siap dimigrasikan", "already_personalized": "Sudah dipersonalisasi", "foreign_or_invalid": "Kartu tidak dapat diperso"}
            self.card.set(labels.get(code, code))
            self.commit.configure(state="normal" if precheck_ready else "disabled")
            if self.wallet_slot_action == "awaiting_check":
                # The STM32 has returned the real result. Stop the UI timeout
                # immediately; the final visible step may still take one second
                # to render, but
                # that display delay must never cancel a successful precheck.
                self.wallet_slot_action = "result_pending"
                if precheck_ready:
                    self.queue_technical_steps_through(10, after=lambda: self.finish_final_block_check(True))
                else:
                    self.queue_technical_steps_through(10, passed=False, after=lambda: self.finish_final_block_check(False))
        elif event_type == "progress":
            if code in self.step_state:
                self.step_state[code].configure(fg="#78e08f")
            if self.wallet_slot_action == "writing":
                progress_steps = {
                    "start": (1, "Personalization command accepted by the Board."),
                    "write_protection": (2, "Writing Sector 2 protection..."),
                    "preserve_wallet": (2, "Preserving the existing Wallet Data..."),
                    "write_wallet": (3, "Writing Wallet Data..."),
                    "write_metadata": (4, "Writing Card Number, counter, and security data to Card Identity..."),
                    "verify_wallet": (5, "Reading Wallet Data and Card Identity back and running Security Verification..."),
                }
                if code in progress_steps:
                    step, message = progress_steps[code]
                    if step == 1:
                        self.set_personalization_process_step(1, True)
                    else:
                        self.begin_personalization_process_step(step)
                    self.debug_status.set(f"Personalization {step}/7: {message}")
                    if code in ("write_protection", "preserve_wallet"):
                        self.update_personalization_run(protection_written=True)
                    elif code == "write_wallet":
                        self.update_personalization_run(protection_written=True)
                    elif code == "verify_wallet":
                        self.update_personalization_run(wallet_written=True)
            elif self.wallet_slot_action == "removing" and code == "remove_metadata":
                self.debug_status.set("Removing Card Identity. Wallet Data is not being changed...")
            elif self.wallet_slot_action == "removing" and code == "verify_removed":
                self.debug_status.set("Verifying that Card Identity is blank...")
        elif event_type == "result":
            self.commit.configure(state="disabled")
            self.card_precheck = ""
            if code == "master_registered":
                self.card.set("Master terdaftar — sesi terbuka")
                self.close_master_registration_gate()
                self.status.set("Master terdaftar — Personalization siap digunakan")
            elif code == "perso_success":
                database_saved = False
                if self.wallet_slot_action == "writing":
                    if self.personalization_active_step:
                        self.set_personalization_process_step(self.personalization_active_step, True)
                    self.set_personalization_process_step(6, True)
                    self.personalization_active_step = 6
                    self.personalization_completed = True
                    self.wallet_slot_action = "completed"
                    self.debug_wallet_summary.set("Wallet Data and Card Identity personalized")
                    self.wallet_slot_button.configure(text="Card personalized", state="disabled")
                    self.wallet_slot_button.pack_forget()
                    database_saved = self.record_personalization_success()
                    self.debug_status.set(
                        "Wallet Data and Card Identity were written and verified; customer ownership saved. Remove the card."
                        if database_saved else
                        "CARD VERIFIED, DATABASE SYNC REQUIRED. Do not personalize this card again."
                    )
                self.card.set("Personalization berhasil — angkat kartu")
                if self.selected_customer_id is not None and self.database:
                    self.load_customers()
                messagebox.showinfo(
                    "Personalization complete",
                    "The card was written and verified with an active 0 L wallet. Customer ownership was recorded in the Database."
                    if database_saved else
                    "The card was written and verified, but its customer record needs manual database reconciliation.",
                )
            elif code == "perso_failed":
                self.fail_or_cancel_personalization_run("failed", "firmware_result", code)
                if self.wallet_slot_action == "writing":
                    failed_step = max(2, self.personalization_active_step)
                    self.set_personalization_process_step(failed_step, False)
                    self.wallet_slot_action = "failed_write"
                    self.debug_status.set("Personalization FAILED — remove the card after reviewing the error.")
                messagebox.showerror("Personalization gagal", "Penulisan atau verifikasi kartu gagal.")
            elif code == "perso_removed":
                try:
                    reference = int(event.get("card_reference", 0))
                except (TypeError, ValueError):
                    reference = 0
                database_result = self.record_personalization_removal(reference)
                self.wallet_slot_action = "removed"
                self.wallet_slot_state = "legacy_ready"
                self.debug_wallet_summary.set("Card Identity removed · Wallet Data preserved")
                if database_result == "updated":
                    message = "Card Identity was removed and its active Database ownership was closed. Remove the card."
                elif database_result == "not_found":
                    message = "Card Identity was removed. No matching active ownership existed in this Database. Remove the card."
                else:
                    message = "CARD CLEARED, DATABASE SYNC REQUIRED. Record this Card Number for manual reconciliation."
                self.debug_status.set(message)
                self.debug_last_event.set("Last event: " + message)
            elif code == "perso_remove_failed":
                self.wallet_slot_action = "remove_failed"
                self.debug_status.set("Remove personalization FAILED. Card Identity was not confirmed blank.")
                self.debug_last_event.set("Last event: Board could not remove and verify Card Identity.")
        elif event_type == "error":
            if self.wallet_slot_action == "writing":
                self.fail_or_cancel_personalization_run("failed", "firmware_error", code)
                failed_step = max(1, self.personalization_active_step)
                self.set_personalization_process_step(failed_step, False)
                self.wallet_slot_action = "failed_write"
                self.debug_status.set(f"Personalization rejected: {code}. Remove the card and try again.")
            elif self.wallet_slot_action in ("remove_arming", "removing"):
                self.wallet_slot_action = "remove_failed"
                self.debug_status.set(f"Remove personalization rejected: {code}.")
        self.status.set(f"{event_type}: {code}")
        if event_type == "error" or code == "nfc_unavailable" or event.get("nfc_ready") is False:
            if self.background_scan:
                self.set_connection_searching()
            else:
                self.connection_spinner.pack_forget()
                self.connection_badge.configure(text="PERLU CEK ALAT", fg="#ef5b5b")
        elif event.get("nfc_ready") is True:
            # PN532 dapat pulih setelah kabel/modul diperbaiki tanpa reboot.
            # Status header harus ikut pulih, bukan hanya tombol yang aktif.
            self.set_connection_connected(self.port.get())
        elif is_perso_ready(event):
            self.set_connection_connected(self.port.get())
        self.refresh_operator_guide()
        # A full scan emits one event per block. Keep MySQL audit concise and
        # never store the returned block content there.
        if not (event_type == "technical" and code == "scan_block"):
            self.write_log(f"{event_type}: {code}")
            self.audit(event_type, code, event)

    def write_log(self, text: str) -> None:
        event_type, _, code = text.partition(": ")
        operation = "simulasi" if self.simulation.get() else "board"
        self.log_entries.append((format_wib_datetime(datetime.now(WIB)), event_type.upper(), code or "-", operation))
        self.log_entries = self.log_entries[-50:]
        self.render_recent_logs()

    def load_recent_logs(self) -> None:
        """Muat audit aman yang tersimpan; tidak ada UID, key, atau block mentah."""
        if not self.database:
            return
        cursor = self.database.cursor()
        cursor.execute("SELECT created_at, event_type, status, operation FROM audit_log ORDER BY id DESC LIMIT 50")
        rows = cursor.fetchall()
        cursor.close()
        self.log_entries = []
        for created_at, event_type, status, operation in reversed(rows):
            waktu = format_wib_datetime(created_at, "-")
            self.log_entries.append((waktu, str(event_type).upper(), str(status or "-"), str(operation or "board")))
        self.render_recent_logs()

    def render_recent_logs(self) -> None:
        if not hasattr(self, "log"):
            return
        for item in self.log.get_children():
            self.log.delete(item)
        entries = reversed(self.log_entries) if self.log_descending else iter(self.log_entries)
        for entry in entries:
            self.log.insert("", "end", values=entry)
        children = self.log.get_children()
        if children:
            self.log.see(children[0] if self.log_descending else children[-1])

    def toggle_log_order(self) -> None:
        self.log_descending = not self.log_descending
        self.log_order_button.configure(text="Newest ↓" if self.log_descending else "Oldest ↑")
        self.render_recent_logs()

    def clear_logs(self) -> None:
        if not messagebox.askyesno(
            "Clear logs",
            "Hapus seluruh Activity Logs dari tampilan dan Database?\n\nTindakan ini tidak dapat dibatalkan.",
        ):
            return
        try:
            if self.database:
                cursor = self.database.cursor()
                cursor.execute("DELETE FROM audit_log")
                cursor.close()
                self.database.commit()
        except Exception as error:
            messagebox.showerror("Clear logs gagal", str(error))
            return
        self.log_entries.clear()
        self.render_recent_logs()
        self.status.set("Database activity cleared")

    def audit(self, event_type: str, code: str, event: dict) -> None:
        if self.database:
            cursor = self.database.cursor()
            cursor.execute(
                "INSERT INTO audit_log (created_at, event_type, status, operation, card_session) VALUES (%s, %s, %s, %s, %s)",
                (datetime.now().astimezone().isoformat(), event_type, code, event.get("operation"), event.get("card_session")),
            )
            cursor.close()
            self.database.commit()


if __name__ == "__main__":
    PersoApp().mainloop()
