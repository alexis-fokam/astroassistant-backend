"""FastAPI dependencies: database session, authenticated member, role checks (spec §7)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import read_token
from app.models import CrewMember
from app.models.enums import AccessRole

DbSession = Annotated[Session, Depends(get_db)]

_bearer = HTTPBearer(auto_error=False, description="Token returned by POST /api/v1/auth/login")


def current_member(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> CrewMember:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise")
    member_id = read_token(credentials.credentials, get_settings().secret_key)
    member = db.get(CrewMember, member_id) if member_id else None
    if member is None or not member.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide ou expirée")
    return member


CurrentMember = Annotated[CrewMember, Depends(current_member)]


def require_cmo(member: CurrentMember) -> CrewMember:
    if member.access_role is not AccessRole.CMO:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Réservé au médecin de bord")
    return member


CurrentCmo = Annotated[CrewMember, Depends(require_cmo)]


def is_cmo(member: CrewMember) -> bool:
    return member.access_role is AccessRole.CMO


def get_crew_member(db: Session, code: str) -> CrewMember:
    member = db.scalars(select(CrewMember).where(CrewMember.code == code)).first()
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Membre {code} introuvable")
    return member


def visible_member(db: Session, viewer: CrewMember, code: str) -> CrewMember:
    """Un astronaute ne voit que ses propres données ; le CMO voit tout l'équipage (§7)."""
    target = get_crew_member(db, code)
    if target.id != viewer.id and not is_cmo(viewer):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès limité à vos propres données")
    return target


def subject_member(db: Session, viewer: CrewMember, code: str | None) -> CrewMember:
    """Membre concerné par une écriture : soi-même par défaut, n'importe qui pour le CMO."""
    return viewer if code is None or code == viewer.code else visible_member(db, viewer, code)
