import unittest

from datetime import datetime, timezone

from app import customer_field_is_readonly, format_wib_datetime, mask_identity_number, validate_customer_fields


class CustomerDataTests(unittest.TestCase):
    def test_formats_iso_timestamp_as_requested_wib_display(self):
        self.assertEqual(
            format_wib_datetime("2026-09-14T02:38:33.03208+07:00"),
            "02:38 WIB - 14/09/2026",
        )

    def test_converts_utc_datetime_to_wib_display(self):
        self.assertEqual(
            format_wib_datetime(datetime(2026, 9, 13, 19, 38, tzinfo=timezone.utc)),
            "02:38 WIB - 14/09/2026",
        )

    def test_accepts_required_identity_fields(self):
        self.assertEqual(
            validate_customer_fields("3273010101010001", "3273010101019999", "Budi Santoso", "+62 812-3456-7890"),
            [],
        )

    def test_rejects_invalid_nik_kk_and_name(self):
        errors = validate_customer_fields("123", "not-a-kk", "")
        self.assertEqual(len(errors), 3)

    def test_masks_identity_except_last_four_digits(self):
        self.assertEqual(mask_identity_number("3273010101010001"), "••••••••••••0001")

    def test_active_card_locks_identity_but_keeps_contact_and_status_editable(self):
        locked = {field for field in ("number", "nik", "kk", "name", "phone", "address", "status") if customer_field_is_readonly(field, True)}
        self.assertEqual(locked, {"number", "nik", "kk", "name"})

    def test_customer_without_active_card_only_locks_generated_number(self):
        locked = {field for field in ("number", "nik", "kk", "name", "phone", "address", "status") if customer_field_is_readonly(field, False)}
        self.assertEqual(locked, {"number"})


if __name__ == "__main__":
    unittest.main()
