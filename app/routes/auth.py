from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, MeOut

from app.security.dependencies import get_current_user
from app.security.rate_limit import client_ip, login_limiter, register_limiter

from app.security.security import (
    hash_password,
    verify_password,
    create_access_token,
)

from app.services.email_service import send_registration_email



router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)

# Hash factice : la vérification prend le même temps que l'email existe ou non
_DUMMY_HASH = hash_password("dummy-password-for-timing")


@router.post("/register")
def register(
    user_data: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    register_limiter.hit(client_ip(request))

    if user_data.password != user_data.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Les mots de passe ne correspondent pas."
        )

    if len(user_data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins 8 caractères."
        )

    if not any(c.isupper() for c in user_data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins une lettre majuscule."
        )

    if not any(c.islower() for c in user_data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins une lettre minuscule."
        )

    if not any(c.isdigit() for c in user_data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins un chiffre."
        )

    if not any(not c.isalnum() for c in user_data.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mot de passe doit contenir au moins un caractère spécial."
        )

    # Création via fonction SQL SECURITY DEFINER : le rôle applicatif
    # n'a aucun droit INSERT direct sur users (RLS)
    try:
        new_user_id = db.execute(
            text("SELECT auth_register_user(:rs, :email, :pwd, :plan)"),
            {
                "rs": user_data.raison_sociale.strip(),
                "email": user_data.email,
                "pwd": hash_password(user_data.password),
                "plan": user_data.plan_code,
            },
        ).scalar_one()
        db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un utilisateur avec cet email existe déjà."
        )

    except DBAPIError as e:
        db.rollback()
        if getattr(e.orig, "sqlstate", None) == "22023":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formule d'abonnement inconnue."
            )
        raise

    plan_name = db.execute(
        text("SELECT name FROM plans WHERE code = :c"),
        {"c": user_data.plan_code},
    ).scalar_one()

    background_tasks.add_task(
        send_registration_email,
        user_data.email,
        user_data.raison_sociale.strip(),
        plan_name,
    )

    return {
        "message": "Compte créé. Votre abonnement est en attente d'activation.",
        "user": {
            "id": new_user_id,
            "email": user_data.email.lower(),
        }
    }


@router.post("/login", response_model=TokenResponse)
def login(user_data: LoginRequest, request: Request, db: Session = Depends(get_db)):
    login_limiter.hit(f"{client_ip(request)}:{user_data.email.lower()}")

    row = db.execute(
        text("SELECT id, hashed_password, is_active FROM auth_find_user(:email)"),
        {"email": user_data.email},
    ).first()

    password_ok = verify_password(
        user_data.password,
        row.hashed_password if row else _DUMMY_HASH,
    )

    if not row or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect.",
        )

    if not row.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Compte désactivé.",
        )

    access_token = create_access_token(data={"sub": str(row.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=MeOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
