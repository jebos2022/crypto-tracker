import tempfile
import unittest
from datetime import datetime as real_datetime
from pathlib import Path

from core import backup


class BackupTests(unittest.TestCase):
    def test_create_backup_uses_utc_timestamp(self) -> None:
        tempdir = Path(tempfile.mkdtemp())
        db_path = tempdir / "portfolio.db"
        db_path.write_text("db", encoding="utf-8")

        class FakeDateTime:
            seen_tz = None

            @classmethod
            def now(cls, tz=None):
                cls.seen_tz = tz
                return real_datetime(2026, 5, 5, 12, 34, 56, tzinfo=tz)

        original_db_path = backup.DB_PATH
        original_backup_dir = backup.BACKUP_DIR
        original_datetime = backup.datetime
        backup.DB_PATH = db_path
        backup.BACKUP_DIR = tempdir / "backups"
        backup.datetime = FakeDateTime
        try:
            path = backup.create_backup()
        finally:
            backup.DB_PATH = original_db_path
            backup.BACKUP_DIR = original_backup_dir
            backup.datetime = original_datetime

        self.assertEqual(FakeDateTime.seen_tz, backup.timezone.utc)
        self.assertEqual(path.name, "portfolio_20260505_123456.bak")
        self.assertEqual(path.read_text(encoding="utf-8"), "db")


if __name__ == "__main__":
    unittest.main()
