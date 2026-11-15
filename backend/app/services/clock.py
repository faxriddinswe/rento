from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings


def today_local() -> date:
    """'Today' in the business timezone (Asia/Tashkent by default)."""
    return datetime.now(ZoneInfo(get_settings().timezone)).date()
