import shutil
from datetime import datetime
from pathlib import Path

from core.db import DB_PATH

BACKUP_DIR = DB_PATH.parent / "backups"
MAX_BACKUPS = 30


def create_backup() -> Path | None:
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = BACKUP_DIR / f"portfolio_{timestamp}.bak"
    shutil.copy2(DB_PATH, dest)
    _rotate_backups()
    return dest


def _rotate_backups() -> None:
    backups = sorted(BACKUP_DIR.glob("portfolio_*.bak"))
    for old in backups[:-MAX_BACKUPS]:
        old.unlink()
