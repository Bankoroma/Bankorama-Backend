from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.database.database import get_db
from app.database.models import User
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse

from app.security.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_email_verification_token,
    SECRET_KEY,
    ALGORITHM,
)

from app.services.email_service import send_verification_email



router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)


@router.post("/register")
def register(user_data: RegisterRequest, db: Session = Depends(get_db)):

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

    existing_user = db.query(User).filter(
        User.email == user_data.email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un utilisateur avec cet email existe déjà."
        )

    new_user = User(
        raison_sociale=user_data.raison_sociale,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    verification_token = create_email_verification_token(new_user.email)

    send_verification_email(
        new_user.email,
        verification_token,
        new_user.raison_sociale
    )

    return {
        "message": "Compte créé avec succès",
        "user": {
            "id": new_user.id,
            "email": new_user.email,
        }
    }
@router.post("/login", response_model=TokenResponse)
def login(user_data: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()

    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect.",
        )

    if not user.is_verified:
        raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Veuillez vérifier votre adresse email avant de vous connecter.",
    )

    access_token = create_access_token(data={"sub": str(user.id)})

    return {
        "access_token": access_token,
        "token_type": "bearer",
    }

@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        email = payload.get("email")
        token_type = payload.get("type")

        if not email or token_type != "email_verification":
            raise HTTPException(
                status_code=400,
                detail="Token de vérification invalide."
            )

    except JWTError:
        raise HTTPException(
            status_code=400,
            detail="Token de vérification invalide ou expiré."
        )

    user = db.query(User).filter(User.email == email).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="Utilisateur introuvable."
        )

    user.is_verified = True
    db.commit()

    return {
        "message": "Adresse email vérifiée avec succès."
    }