"""Shared foundation of the SQLAlchemy models: declarative base, conventions, mixins.

Every column carries a ``comment``: it is written into the database schema and is the
single source of the generated data dictionary (``python -m app.docs``).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, TypeDecorator
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable constraint names (ready for future Alembic migrations).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes on every database.

    SQLite does not store time zones and returns naive datetimes; every datetime of the
    schema is UTC, so values are normalised to UTC on write and tagged UTC on read. The API
    then always serialises ``...+00:00`` and clients never misread a time as local.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    """Declarative base of every Astro Assistant model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
        datetime: UTCDateTime(),
    }


def enum_type[E: StrEnum](enum_cls: type[E]) -> SAEnum:
    """Enum stored as VARCHAR (value, not name) plus a CHECK constraint (SQLite/Postgres)."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        default=utcnow, comment="Date de création de la ligne (UTC)"
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, comment="Date de dernière modification (UTC)"
    )
