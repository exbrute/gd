import os

from dotenv import load_dotenv

load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")


def ensure_config() -> None:
    """
    Simple runtime check to make sure critical settings are provided.
    """
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not WEBAPP_URL:
        missing.append("WEBAPP_URL")

    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Missing required environment variables: {joined}. "
            "Создайте файл .env (можно на основе .env.example) и пропишите значения."
        )



