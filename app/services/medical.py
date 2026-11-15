from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models import Alert, ConsultationNote, CrewMember, InventoryItem, InventoryUsage
from app.models.enums import AccessRole
from app.schemas.care import ConsultationIn, ConsultationOut, UsageLogOut


def _ensure_cmo(member: CrewMember) -> None:
    """Vérifie que l'utilisateur connecté possède le rôle actif CMO."""
    is_cmo = member.access_role is AccessRole.CMO
    if not is_cmo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé au Médecin de bord (CMO)",
        )


def _get_patient(db: Session, code: str) -> CrewMember:
    patient = db.scalars(
        select(CrewMember).where(CrewMember.code == code, CrewMember.is_active.is_(True))
    ).first()
    if patient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Membre d'équipage '{code}' introuvable",
        )
    return patient


def _to_consultation_out(note: ConsultationNote) -> ConsultationOut:
    return ConsultationOut(
        id=note.id,
        patient_code=note.patient.code,
        author_code=note.author.code if note.author else None,
        author_name=note.author.full_name if note.author else None,
        alert_id=note.alert_id,
        written_at=note.written_at,
        title=note.title,
        body=note.body,
    )


def list_consultations(
    db: Session,
    current: CrewMember,
    patient_code: str,
) -> list[ConsultationOut]:
    """Retourne le journal médical complet d'un astronaute (du plus récent au plus ancien)."""
    _ensure_cmo(current)
    patient = _get_patient(db, patient_code)

    notes = db.scalars(
        select(ConsultationNote)
        .options(
            joinedload(ConsultationNote.patient),
            joinedload(ConsultationNote.author),
        )
        .where(ConsultationNote.patient_id == patient.id)
        .order_by(ConsultationNote.written_at.desc())
    ).all()

    return [_to_consultation_out(n) for n in notes]


def create_consultation(
    db: Session,
    current: CrewMember,
    patient_code: str,
    payload: ConsultationIn,
) -> ConsultationOut:
    """Ajoute une note de consultation rédigée par le CMO dans le journal médical."""
    _ensure_cmo(current)
    patient = _get_patient(db, patient_code)

    if payload.alert_id is not None:
        alert = db.scalars(
            select(Alert).where(
                Alert.id == payload.alert_id,
                Alert.crew_member_id == patient.id,
            )
        ).first()
        if alert is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Alerte #{payload.alert_id} introuvable pour le patient '{patient_code}'",
            )

    note = ConsultationNote(
        patient_id=patient.id,
        author_id=current.id,
        alert_id=payload.alert_id,
        title=payload.title,
        body=payload.body,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    # Recharge les relations patient/author pour la réponse
    note.patient = patient
    note.author = current
    return _to_consultation_out(note)

def _ensure_cmo(member: CrewMember) -> None:
    is_cmo = member.access_role is AccessRole.CMO
    if not is_cmo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès au registre de la pharmacie réservé au Médecin de bord (CMO)",
        )


def list_inventory_usages(
    db: Session,
    current: CrewMember,
    item_code: str | None = None,
    patient_code: str | None = None,
    limit: int = 100,
) -> list[UsageLogOut]:
    _ensure_cmo(current)

    stmt = (
        select(InventoryUsage)
        .options(
            joinedload(InventoryUsage.item),
            joinedload(InventoryUsage.patient),
            joinedload(InventoryUsage.recorded_by),
        )
        .order_by(InventoryUsage.used_at.desc())
        .limit(limit)
    )

    if item_code:
        stmt = stmt.join(InventoryUsage.item).where(InventoryItem.code == item_code)

    if patient_code:
        stmt = stmt.join(InventoryUsage.patient).where(CrewMember.code == patient_code)

    usages = db.scalars(stmt).all()

    return [
        UsageLogOut(
            id=u.id,
            item_code=u.item.code,
            item_name=u.item.name,
            unit=u.item.unit,
            quantity=u.quantity,
            patient_code=u.patient.code if u.patient else None,
            recorded_by_code=u.recorded_by.code,
            protocol_run_id=u.protocol_run_id,
            emergency_id=u.emergency_id,
            used_at=u.used_at,
            note=u.note,
        )
        for u in usages
    ]
