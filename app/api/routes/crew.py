"""Authentification, mission et statut de l'équipage (§7, §10, F1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentCmo, CurrentMember, DbSession, is_cmo, visible_member
from app.core.config import get_settings
from app.core.security import create_token, verify_pin
from app.models import ContactWindow, CrewMember, Mission
from app.models.enums import MissionDestination
from app.schemas.crew import (
    CrewProfile,
    CrewStatus,
    CrewSummary,
    LoginRequest,
    MemberOut,
    MissionOut,
    TokenResponse,
)
from app.schemas.ground import MissionPatch
from app.schemas.telemetry import CrewVitalsLatest
from app.services import audit
from app.services.views import as_utc, crew_profiles, crew_status, crew_summary, mission_now
from app.services.vitals import crew_vitals_latest

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(body: LoginRequest, db: DbSession) -> TokenResponse:
    """Déverrouiller un profil local avec son PIN et obtenir un jeton de session."""
    member = db.scalars(select(CrewMember).where(CrewMember.code == body.code)).first()
    if member is None or not member.is_active or not verify_pin(body.pin, member.pin_hash):
        audit.record(db, "auth.failed", actor_label=body.code[:64])
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiant ou PIN incorrect")
    settings = get_settings()
    ttl = settings.token_ttl_hours * 3600
    audit.record(db, "auth.login", actor=member, entity=member)
    db.commit()
    return TokenResponse(
        access_token=create_token(member.id, settings.secret_key, ttl),
        expires_in=ttl,
        member=MemberOut.model_validate(member),
    )


@router.get("/auth/me", response_model=MemberOut, tags=["auth"])
def me(member: CurrentMember) -> CrewMember:
    return member


@router.get("/mission", response_model=MissionOut, tags=["mission"])
def mission(db: DbSession, _: CurrentMember) -> MissionOut:
    current = db.scalars(select(Mission).where(Mission.is_active.is_(True))).first()
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune mission configurée")
    now = mission_now(db)
    next_window = db.scalars(
        select(ContactWindow)
        .where(ContactWindow.mission_id == current.id, ContactWindow.ends_at >= now)
        .order_by(ContactWindow.starts_at)
    ).first()
    next_start = as_utc(next_window.starts_at) if next_window else None
    day = (now.date() - current.start_date).days
    return MissionOut.model_validate(
        {
            **{k: getattr(current, k) for k in MissionOut.model_fields if hasattr(current, k)},
            "mission_day": day,
            "mission_time": now,
            "clock": f"J+{day} · {now:%H:%M}",
            "next_contact_at": next_start,
            "next_contact_time": next_start.strftime("%H:%M:%S") if next_start else None,
            "next_contact_in_s": max(int((next_start - now).total_seconds()), 0)
            if next_start
            else None,
        }
    )


LATENCY_BY_DESTINATION = {
    # Temps de lumière aller plus relais, arrondi (secondes).
    "low_earth_orbit": 2,
    "moon": 3,
    "mars_transit": 12 * 60,
    "mars_surface": 22 * 60,
}


@router.patch("/mission", response_model=MissionOut, tags=["mission"])
def update_mission(body: MissionPatch, db: DbSession, cmo: CurrentCmo) -> MissionOut:
    """Choisir le profil de mission (ISS, Lune, Mars) ; fixe le délai de communication."""
    current = db.scalars(select(Mission).where(Mission.is_active.is_(True))).first()
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aucune mission configurée")
    current.destination = MissionDestination(body.destination)
    current.one_way_latency_s = LATENCY_BY_DESTINATION[body.destination]
    current.day_length_min = 1477 if body.destination == "mars_surface" else 1440
    audit.record(db, "mission.update", actor=cmo, entity=current, destination=body.destination)
    db.commit()
    return mission(db, cmo)


@router.get("/crew", response_model=list[CrewSummary], tags=["crew"])
def crew(db: DbSession, viewer: CurrentMember) -> list[CrewSummary]:
    """Équipage et statut global de chaque membre. Un astronaute ne reçoit que sa ligne."""
    members = db.scalars(
        select(CrewMember).where(CrewMember.is_active.is_(True)).order_by(CrewMember.code)
    )
    return [crew_summary(db, m) for m in members if is_cmo(viewer) or m.id == viewer.id]


@router.get("/crew/{code}/status", response_model=CrewStatus, tags=["crew"])
def status_of(code: str, db: DbSession, viewer: CurrentMember) -> CrewStatus:
    """Statut actuel, scores par domaine, facteurs explicatifs et alertes actives (§10.1)."""
    return crew_status(db, visible_member(db, viewer, code))


@router.get(
    "/profiles", response_model=list[CrewProfile], response_model_by_alias=True, tags=["auth"]
)
def list_profiles(db: DbSession) -> list[CrewProfile]:
    """Public : profils affichés sur l'écran de verrouillage (aucune donnée de santé)."""
    return crew_profiles(db)


@router.get("/crew/{code}/vitals/latest", response_model=CrewVitalsLatest, tags=["vitals"])
def get_crew_vitals_latest(code: str, db: DbSession, viewer: CurrentMember) -> CrewVitalsLatest:
    """Dernière valeur, niveau, tendance, plage normale et 36 derniers points par constante."""
    # visible_member applique le RBAC : un astronaute ne lit que ses constantes (§7).
    return crew_vitals_latest(db, visible_member(db, viewer, code))
