from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.models import Plan
from app.schemas.auth import PlanOut


router = APIRouter(
    prefix="/api/plans",
    tags=["Plans"]
)


@router.get("", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db)):
    return (
        db.query(Plan)
        .filter(Plan.is_active.is_(True))
        .order_by(Plan.sort_order)
        .all()
    )
