"""Journal d'audit horodaté, en ajout seul (F14.1, §7, §9 audit_log).

Chaque entrée est chaînée à la précédente par SHA-256 (``prev_hash`` → ``entry_hash``) ;
sous SQLite, des triggers refusent UPDATE et DELETE sur la table.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, ForeignKey, Index, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow

if TYPE_CHECKING:
    from app.models.crew import CrewMember

GENESIS_HASH = "0" * 64


class AuditLog(Base):
    """Journal d'audit non modifiable : chaque entrée est chaînée à la précédente par SHA-256."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, comment="Identifiant technique (ordre de la chaîne)"
    )
    at: Mapped[datetime] = mapped_column(
        default=utcnow, index=True, comment="Horodatage de l'action (UTC)"
    )
    # Pas de ON DELETE : un profil référencé par le journal d'audit ne peut pas être supprimé.
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id"),
        index=True,
        comment="Membre auteur de l'action (vide pour le système)",
    )
    actor_label: Mapped[str] = mapped_column(
        String(64), comment="Libellé de l'acteur (AV-04, Moteur IA, Système)"
    )
    action: Mapped[str] = mapped_column(
        String(64), comment="Action réalisée (ex. alert.acknowledge)"
    )
    entity_type: Mapped[str | None] = mapped_column(String(64), comment="Type d'objet concerné")
    entity_id: Mapped[int | None] = mapped_column(comment="Identifiant de l'objet concerné")
    details: Mapped[dict[str, Any]] = mapped_column(
        default=dict, comment="Détails de l'action (JSON)"
    )
    prev_hash: Mapped[str] = mapped_column(String(64), comment="Empreinte de l'entrée précédente")
    entry_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="Empreinte SHA-256 de cette entrée"
    )

    actor: Mapped[CrewMember | None] = relationship()

    @staticmethod
    def compute_hash(
        prev_hash: str,
        *,
        at: datetime,
        actor_label: str,
        action: str,
        entity_type: str | None,
        entity_id: int | None,
        details: dict[str, Any],
    ) -> str:
        """Empreinte d'une entrée, chaînée à la précédente (chaîne vérifiable).

        L'horodatage est ramené en UTC naïf : SQLite renvoie des dates naïves, donc
        l'empreinte ne doit pas dépendre de la présence d'un fuseau dans ``at``.
        """
        if at.tzinfo is not None:
            at = at.astimezone(UTC).replace(tzinfo=None)
        payload = json.dumps(
            {
                "prev": prev_hash,
                "at": at.isoformat(),
                "actor": actor_label,
                "action": action,
                "entity": [entity_type, entity_id],
                "details": details,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()


for _op in ("UPDATE", "DELETE"):
    event.listen(
        AuditLog.__table__,
        "after_create",
        DDL(
            f"CREATE TRIGGER audit_logs_no_{_op.lower()} BEFORE {_op} ON audit_logs "
            "BEGIN SELECT RAISE(ABORT, 'audit_logs is append-only'); END"
        ).execute_if(dialect="sqlite"),
    )
