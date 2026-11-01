from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Conversion, Plan, User
from app.schemas.auth import ActivateRequest, AdminUserOut
from app.security.dependencies import require_admin
from app.services.email_service import send_activation_email


router = APIRouter(
    prefix="/api/admin",
    tags=["Administration"]
)

STATUSES = {"pending", "active", "suspended"}


def _serialize(user: User, conversions_count: int) -> AdminUserOut:
    data = AdminUserOut.model_validate(user)
    data.conversions_count = conversions_count
    return data


def _get_user(db: Session, user_id: int) -> User:
    # Le RLS n'autorise la lecture d'un autre compte qu'aux administrateurs
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilisateur introuvable."
        )

    return user


@router.get("/users", response_model=list[AdminUserOut])
def list_users(
    subscription_status: str | None = Query(default=None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    counts = (
        db.query(Conversion.user_id, func.count(Conversion.id).label("n"))
        .group_by(Conversion.user_id)
        .subquery()
    )

    query = (
        db.query(User, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.user_id == User.id)
        .order_by(User.created_at.desc())
    )

    if subscription_status:
        if subscription_status not in STATUSES:
            raise HTTPException(status_code=400, detail="Statut inconnu.")
        query = query.filter(User.subscription_status == subscription_status)

    return [_serialize(user, n) for user, n in query.all()]


@router.post("/users/{user_id}/activate", response_model=AdminUserOut)
def activate_subscription(
    user_id: int,
    payload: ActivateRequest,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)

    if payload.plan_code:
        plan = db.query(Plan).filter(
            Plan.code == payload.plan_code,
            Plan.is_active.is_(True),
        ).first()

        if not plan:
            raise HTTPException(status_code=400, detail="Formule inconnue.")

        user.plan_id = plan.id
        db.flush()
        db.refresh(user)

    if not user.plan:
        raise HTTPException(
            status_code=400,
            detail="Choisissez une formule avant d'activer l'abonnement."
        )

    # Activation : crédits du mois chargés, prochaine recharge dans un mois
    db.execute(
        text(
            """
            UPDATE users SET
                subscription_status = 'active',
                subscription_activated_at = now(),
                credits = :credits,
                credits_renew_at = now() + interval '1 month'
            WHERE id = :uid
            """
        ),
        {"credits": user.plan.monthly_credits, "uid": user.id},
    )
    db.commit()
    db.refresh(user)

    background_tasks.add_task(
        send_activation_email,
        user.email,
        user.raison_sociale,
        user.plan.name,
        user.plan.monthly_credits,
    )

    return _serialize(user, _count_conversions(db, user.id))


@router.post("/users/{user_id}/suspend", response_model=AdminUserOut)
def suspend_subscription(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Vous ne pouvez pas suspendre votre propre compte."
        )

    user = _get_user(db, user_id)
    user.subscription_status = "suspended"
    db.commit()
    db.refresh(user)

    return _serialize(user, _count_conversions(db, user.id))


def _count_conversions(db: Session, user_id: int) -> int:
    return db.query(func.count(Conversion.id)).filter(
        Conversion.user_id == user_id
    ).scalar()
