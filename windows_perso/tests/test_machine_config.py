import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import read_machine_database_config


class MachineConfigTests(unittest.TestCase):
    def test_installer_config_can_be_read_by_application(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "host": "127.0.0.1",
                        "port": 3306,
                        "app_user": "perso_console_app",
                        "scope": "machine",
                        "app_secret": base64.b64encode(b"encrypted").decode(),
                    }
                ),
                encoding="utf-8",
            )
            with patch("app.unprotect_machine_secret", return_value="app-password"):
                config = read_machine_database_config(path)
        self.assertEqual(config["user"], "perso_console_app")
        self.assertEqual(config["password"], "app-password")


if __name__ == "__main__":
    unittest.main()
