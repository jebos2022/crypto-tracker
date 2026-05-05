import os
import tempfile
import unittest
from pathlib import Path

from core import env


class EnvLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_path = env.ENV_PATH
        self.original_loaded = env._LOADED
        self.original_value = os.environ.get("ETHERSCAN_API_KEY")

    def tearDown(self) -> None:
        env.ENV_PATH = self.original_path
        env._LOADED = self.original_loaded
        if self.original_value is None:
            os.environ.pop("ETHERSCAN_API_KEY", None)
        else:
            os.environ["ETHERSCAN_API_KEY"] = self.original_value

    def test_load_env_uses_explicit_path_without_overriding_existing_env(self) -> None:
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("ETHERSCAN_API_KEY=from_file\n", encoding="utf-8")
        env.ENV_PATH = path
        env._LOADED = False
        os.environ["ETHERSCAN_API_KEY"] = "already_set"

        loaded = env.load_env()

        self.assertTrue(loaded)
        self.assertEqual(os.environ["ETHERSCAN_API_KEY"], "already_set")

    def test_load_env_populates_missing_value(self) -> None:
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("ETHERSCAN_API_KEY=from_file\n", encoding="utf-8")
        env.ENV_PATH = path
        env._LOADED = False
        os.environ.pop("ETHERSCAN_API_KEY", None)

        loaded = env.load_env()

        self.assertTrue(loaded)
        self.assertEqual(os.environ["ETHERSCAN_API_KEY"], "from_file")


if __name__ == "__main__":
    unittest.main()
