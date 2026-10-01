"""Buat secret AES-CMAC lokal untuk format kartu compact.

File hasil berada di .private/ dan tidak boleh dicommit atau ditampilkan.
Jalankan sekali pada mesin build; salin secara aman ke mesin build resmi.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="ganti secret lokal yang sudah ada")
    args = parser.parse_args()

    project = Path(__file__).resolve().parents[1]
    target = project / ".private" / "compact_card_secret.h"
    if target.exists() and not args.force:
        print(f"Secret sudah tersedia: {target}")
        return

    mac_secret = ",".join(f"0x{byte:02X}" for byte in secrets.token_bytes(16))
    mifare_key_a = ",".join(f"0x{byte:02X}" for byte in secrets.token_bytes(6))
    mifare_key_b = ",".join(f"0x{byte:02X}" for byte in secrets.token_bytes(6))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "#pragma once\n#include <cstdint>\n"
        "namespace smartdispenser { namespace compact_card_private {\n"
        f"static const uint8_t kMacSecret[16] = {{{mac_secret}}};\n"
        f"static const uint8_t kMifareKeyA[6] = {{{mifare_key_a}}};\n"
        f"static const uint8_t kMifareKeyB[6] = {{{mifare_key_b}}};\n"
        "}}\n",
        encoding="ascii",
    )
    print(f"Secret kartu lokal dibuat: {target}")


if __name__ == "__main__":
    main()
