"""Core aplikasi Perso: framing bridge, simulasi, dan audit tanpa data NFC rahasia."""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MAX_FRAME = 256
PROTOCOL_VERSION = 1
PERSO_PROFILE = "smartdispenser_perso"
CARD_FORMAT = "compact_v1"
REQUEST_MAGIC = b"\xA5\x5A"


class ProtocolError(ValueError):
    pass


def encode_frame(message: dict[str, Any]) -> bytes:
    payload = json.dumps(message, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    if not payload or len(payload) > MAX_FRAME:
        raise ProtocolError("frame kosong atau terlalu besar")
    # Requests use a sync marker so USB noise or a stale terminal cannot be
    # mistaken for the two-byte length field by the ESP32.
    return REQUEST_MAGIC + struct.pack(">H", len(payload)) + payload


def decode_frames(buffer: bytearray) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    while len(buffer) >= 2:
        if buffer[:2] == REQUEST_MAGIC:
            del buffer[:2]
            continue
        size = struct.unpack(">H", buffer[:2])[0]
        if size == 0 or size > MAX_FRAME:
            buffer.clear()
            raise ProtocolError("panjang frame tidak sah")
        if len(buffer) < size + 2:
            break
        raw = bytes(buffer[2 : size + 2])
        del buffer[: size + 2]
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProtocolError("JSON bridge tidak sah") from error
        if not isinstance(value, dict) or value.get("v") != PROTOCOL_VERSION:
            raise ProtocolError("versi bridge tidak sah")
        messages.append(value)
    return messages


def decode_frames_resilient(buffer: bytearray) -> list[dict[str, Any]]:
    """Mengambil frame valid dari stream serial yang bisa diawali teks boot ESP32.

    Ini hanya dipakai pada serial fisik. Parser protokol ketat di atas tetap
    dipakai untuk unit-test kontrak frame dan menolak frame rusak.
    """
    messages: list[dict[str, Any]] = []
    while len(buffer) >= 2:
        if buffer[:2] == REQUEST_MAGIC:
            del buffer[:2]
            continue
        size = struct.unpack(">H", buffer[:2])[0]
        if size == 0 or size > MAX_FRAME:
            del buffer[0]
            continue
        if len(buffer) < size + 2:
            break
        raw = bytes(buffer[2 : size + 2])
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            del buffer[0]
            continue
        if not isinstance(value, dict) or value.get("v") != PROTOCOL_VERSION:
            del buffer[0]
            continue
        del buffer[: size + 2]
        messages.append(value)
    return messages


def request(command: str, **parameters: Any) -> dict[str, Any]:
    # STM32's UART receive buffer is intentionally small. Commands are
    # stateless and the desktop never consumes a request UUID, so omitting it
    # keeps every bridge request below the safe frame size.
    message = {"v": PROTOCOL_VERSION, "type": command}
    message.update(parameters)
    return message


def encode_stm32_compact_commit(card_reference: int) -> bytes:
    """Encode a bounded, reset-delimited STM32 commit command."""
    if not isinstance(card_reference, int) or not 1 <= card_reference <= 0xFFFFFFFF:
        raise ProtocolError("card_reference must be a non-zero uint32")
    return f"!P{card_reference:08X}\n".encode("ascii")


def is_perso_ready(event: dict[str, Any]) -> bool:
    """Terima hanya handshake dari firmware profil Perso yang tepat."""
    return (
        event.get("v") == PROTOCOL_VERSION
        and event.get("profile") == PERSO_PROFILE
        and event.get("card_format") == CARD_FORMAT
        and event.get("type") == "status"
        and event.get("code") == "perso_ready"
    )


def audit_record(event: str, **details: Any) -> dict[str, Any]:
    return {"at": datetime.now(timezone.utc).isoformat(), "event": event, **details}


@dataclass
class PersoSimulator:
    """Simulasi protokol; tidak menyentuh COM maupun data kartu nyata."""

    master_registered: bool = False
    session_open: bool = False
    operation: str = "idle"
    card_session: int = 0
    card_present: bool = False
    precheck: str | None = None

    def _event(self, event_type: str, code: str) -> dict[str, Any]:
        return {
            "v": 1,
            "profile": PERSO_PROFILE,
            "card_format": CARD_FORMAT,
            "type": event_type,
            "code": code,
            "master_registered": self.master_registered,
            "session_open": self.session_open,
            "operation": self.operation,
            "card_session": self.card_session,
        }

    def send(self, command: dict[str, Any]) -> list[dict[str, Any]]:
        kind = command.get("type")
        if kind == "status_request":
            return [self._event("status", "perso_ready")]
        if kind == "technical_scan" and self.session_open and self.card_present:
            return [self._event("technical", "scan_started"), self._event("technical", "scan_complete")]
        if kind == "session_lock":
            self.session_open = False
            self.operation = "idle"
            self.precheck = None
            return [self._event("status", "session_locked")]
        if kind == "register_master_begin" and not self.master_registered:
            self.operation = "master_enroll"
            return [self._event("status", "master_enroll_wait_card")]
        if kind == "register_master_commit" and self.operation == "master_enroll" and self.card_present:
            self.master_registered = self.session_open = True
            self.operation = "idle"
            return [self._event("result", "master_registered")]
        if kind == "reset_master_begin" and self.master_registered:
            self.operation = "master_reset"
            return [self._event("status", "master_reset_hold")]
        if kind == "reset_master_commit" and self.operation == "master_reset":
            self.master_registered = self.session_open = False
            self.operation = "idle"
            return [self._event("result", "master_reset")]
        if kind == "perso_arm" and self.session_open:
            self.operation = "perso_armed"
            return [self._event("status", "perso_wait_card")]
        if kind == "perso_commit" and self.operation == "perso_review" and self.precheck == "blank":
            self.operation = "idle"
            return [self._event("progress", "start"), self._event("progress", "write_protection"), self._event("progress", "write_wallet"), self._event("progress", "verify_wallet"), self._event("result", "perso_success")]
        if kind == "perso_remove" and self.operation == "perso_review" and self.precheck == "already_personalized":
            self.operation = "idle"
            self.precheck = "legacy_personalized"
            result = self._event("result", "perso_removed")
            result["card_reference"] = 297
            return [self._event("progress", "remove_metadata"), self._event("progress", "verify_removed"), result]
        if kind == "cancel":
            self.operation = "idle"
            return [self._event("status", "cancelled")]
        return [self._event("error", "command_not_allowed")]

    def present_card(self, state: str = "blank") -> list[dict[str, Any]]:
        self.card_present = True
        self.card_session += 1
        output = [self._event("card", "detected")]
        if self.operation == "perso_armed":
            self.precheck = state
            self.operation = "perso_review"
            output += [self._event("progress", "precheck"), self._event("precheck", state)]
        return output

    def remove_card(self) -> list[dict[str, Any]]:
        self.card_present = False
        return [self._event("card", "removed")]
