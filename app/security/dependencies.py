from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.database import get_db, set_rls_user
from app.database.models import User
from app.security.security import SECRET_KEY, ALGORITHM


security = HTTPBearer()


def renouveler_credits_si_echus(db: Session, user: User):
    """
    Recharge mensuelle : à chaque échéance, les crédits repartent
    au quota de la formule (pas de report).
    """

    if user.subscription_status != "active" or not user.credits_renew_at:
        return

    result = db.execute(
        text(
            """
            UPDATE users u SET
                credits = p.monthly_credits,
                credits_renew_at = u.credits_renew_at + make_interval(months =>
                    (extract(year FROM age(now(), u.credits_renew_at)) * 12
                     + extract(month FROM age(now(), u.credits_renew_at)))::int + 1)
            FROM plans p
            WHERE u.id = :uid
              AND p.id = u.plan_id
              AND u.subscription_status = 'active'
              AND u.credits_renew_at <= now()
            """
        ),
        {"uid": user.id},
    )

    if result.rowcount:
        db.commit()
        db.refresh(user)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")

        if not user_id or payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalide"
            )

        user_id = int(user_id)

    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré"
        )

    # Toutes les requêtes suivantes de la session sont filtrées par le RLS
    set_rls_user(db, user_id)

    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur introuvable"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé"
        )

    renouveler_credits_si_echus(db, user)

    return user


def require_active_subscription(user: User = Depends(get_current_user)):
    if user.subscription_status == "pending":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Votre abonnement est en attente d'activation par un administrateur."
        )

    if user.subscription_status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Votre abonnement est suspendu. Contactez le support."
        )

    return user


def require_admin(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé aux administrateurs."
        )

    return user
