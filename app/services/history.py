from typing import Any, TypeVar
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import CrewMember

ModelT = TypeVar("ModelT")


def resolve_authorized_member(
    db: Session,
    current: CrewMember,
    code: str,
) -> CrewMember:
    """Vérifie que l'utilisateur courant a le droit de lire l'historique du membre ciblé."""

    if current.code != code:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé aux historiques d'un autre membre d'équipage",
        )

    target = db.scalars(
        select(CrewMember).where(CrewMember.code == code, CrewMember.is_active.is_(True))
    ).first()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Membre d'équipage '{code}' introuvable",
        )
    return target


def paginate_member_history(
    db: Session,
    model: type[ModelT],
    member_id: int,
    order_col: InstrumentedAttribute[Any],
    limit: int,
    offset: int,
) -> tuple[list[ModelT], int]:
    """Retourne les enregistrements triés du plus récent au plus ancien ainsi que le total."""
    base_filter = model.crew_member_id == member_id  # type: ignore[attr-defined]

    total = db.scalar(select(func.count()).select_from(model).where(base_filter)) or 0
    rows = db.scalars(
        select(model)
        .where(base_filter)
        .order_by(order_col.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return list(rows), total
