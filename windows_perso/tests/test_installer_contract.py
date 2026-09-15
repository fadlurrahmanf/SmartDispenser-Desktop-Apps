import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class InstallerContractTests(unittest.TestCase):
    def test_setup_fails_closed_until_database_is_verified(self):
        script = (ROOT / "installer" / "configure_database.ps1").read_text(encoding="utf-8")
        prerequisites = (ROOT / "installer" / "install_prerequisites.ps1").read_text(encoding="utf-8")
        setup = (ROOT / "installer" / "SmartDispenserPerso.iss").read_text(encoding="utf-8")

        self.assertIn("Wait-ForDatabase", script)
        self.assertIn("Perso application account verification failed", script)
        self.assertIn("DataProtectionScope]::LocalMachine", script)
        self.assertIn('$env:ProgramData "SmartDispenser\\Perso"', script)
        self.assertIn("database-ready", script)
        self.assertIn("AfterInstall: VerifyDatabaseProvisioning", setup)
        self.assertIn("perso-database-ready.marker", setup)
        self.assertIn("RaiseException", setup)
        self.assertIn("perso-prerequisites-ready.marker", setup)
        self.assertIn("AfterInstall: VerifyPrerequisiteInstallation", setup)
        self.assertIn("msedgewebview2.exe", prerequisites)
        self.assertIn("ch341ser\\.inf", prerequisites)
        self.assertIn("if (-not $webViewReady)", prerequisites)
        self.assertIn("__SMARTDISPENSER_EMPTY_PASSWORD__", setup)
        self.assertIn("__SMARTDISPENSER_EMPTY_PASSWORD__", script)
        self.assertIn("Add-Type -AssemblyName System.Security", script)
        self.assertIn("perso-installer-database.log", script)

    def test_setup_recognizes_xampp_and_explains_blank_password(self):
        setup = (ROOT / "installer" / "SmartDispenserPerso.iss").read_text(encoding="utf-8")
        self.assertIn("xampp\\mysql\\bin\\mysql.exe", setup)
        self.assertIn("XAMPP masih memakai root tanpa password", setup)
        self.assertIn('#define AppVersion "1.0.2"', setup)


if __name__ == "__main__":
    unittest.main()
