import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerContractTests(unittest.TestCase):
    def test_setup_fails_closed_until_database_is_verified(self):
        script = (ROOT / "installer" / "configure_database.ps1").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SmartDispenserTopup.iss").read_text(encoding="utf-8")

        self.assertIn("Wait-ForDatabase", script)
        self.assertIn("Topup application account verification failed", script)
        self.assertIn("operator_pin_secret", script)
        self.assertIn("config.json.new", script)
        self.assertIn("database-ready", script)
        self.assertIn("AfterInstall: VerifyDatabaseProvisioning", setup)
        self.assertIn("topup-database-ready.marker", setup)
        self.assertIn("RaiseException", setup)

    def test_setup_explains_existing_xampp_blank_password(self):
        setup = (ROOT / "installer" / "SmartDispenserTopup.iss").read_text(encoding="utf-8")
        self.assertIn("XAMPP masih memakai root tanpa password", setup)
        self.assertIn('#define AppVersion "1.0.1"', setup)


if __name__ == "__main__":
    unittest.main()
