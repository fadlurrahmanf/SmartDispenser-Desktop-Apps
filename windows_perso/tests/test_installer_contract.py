import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerContractTests(unittest.TestCase):
    def test_setup_fails_closed_until_database_is_verified(self):
        script = (ROOT / "installer" / "configure_database.ps1").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SmartDispenserPerso.iss").read_text(encoding="utf-8")

        self.assertIn("Wait-ForDatabase", script)
        self.assertIn("Perso application account verification failed", script)
        self.assertIn("database-ready", script)
        self.assertIn("AfterInstall: VerifyDatabaseProvisioning", setup)
        self.assertIn("perso-database-ready.marker", setup)
        self.assertIn("RaiseException", setup)

    def test_setup_recognizes_xampp_and_explains_blank_password(self):
        setup = (ROOT / "installer" / "SmartDispenserPerso.iss").read_text(encoding="utf-8")
        self.assertIn("xampp\\mysql\\bin\\mysql.exe", setup)
        self.assertIn("XAMPP masih memakai root tanpa password", setup)
        self.assertIn('#define AppVersion "1.0.1"', setup)


if __name__ == "__main__":
    unittest.main()
