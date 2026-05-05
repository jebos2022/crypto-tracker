from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"
_LOADED = False


def load_env() -> bool:
    """Load the project-root .env once, independent of Streamlit's cwd."""
    global _LOADED
    if _LOADED:
        return ENV_PATH.exists()
    loaded = load_dotenv(ENV_PATH, override=False)
    _LOADED = True
    return loaded
