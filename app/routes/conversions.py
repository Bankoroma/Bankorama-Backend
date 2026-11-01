from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Conversion, User
from app.schemas.auth import ConversionOut
from app.security.dependencies import get_current_user


router = APIRouter(
    prefix="/api/conversions",
    tags=["Conversions"]
)


@router.get("", response_model=list[ConversionOut])
def list_my_conversions(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Le RLS limite déjà aux conversions de l'utilisateur ;
    # le filtre explicite évite qu'un admin voie celles des autres ici
    return (
        db.query(Conversion)
        .filter(Conversion.user_id == current_user.id)
        .order_by(Conversion.created_at.desc())
        .limit(limit)
        .all()
    )
