"""Socle commun des modèles SQLAlchemy : base déclarative, conventions, mixins.

Chaque colonne porte un ``comment`` : il est écrit dans le schéma de la base et sert de
source unique au dictionnaire de données généré (``python -m app.docs``).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, MetaData, TypeDecorator
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Noms de contraintes stables (prêts pour de futures migrations Alembic).
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
    """Dates UTC avec fuseau sur toutes les bases.

    SQLite ne stocke pas les fuseaux et renvoie des dates naïves ; toutes les dates du
    schéma sont en UTC : elles sont ramenées en UTC à l'écriture et marquées UTC à la
    lecture. L'API sérialise donc toujours ``...+00:00`` et aucun client ne lit une heure
    locale par erreur.
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
    """Base déclarative de tous les modèles d'Astro Assistant."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
        datetime: UTCDateTime(),
    }


def enum_type[E: StrEnum](enum_cls: type[E]) -> SAEnum:
    """Énumération stockée en VARCHAR (valeur, pas nom) avec une contrainte CHECK."""
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
