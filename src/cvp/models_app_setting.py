"""Runtime-configurable settings stored in the DB, edited via System Admin UI."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from cvp.models import Base


class AppSetting(Base):
    """A single runtime-tunable key/value pair.

    `value_json` stores the value as a JSON-encoded string so we can keep ints,
    floats, bools, and strings in one column without per-type tables. Defaults
    for missing keys come from `cvp.config.Settings` (env vars at startup).
    """

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
