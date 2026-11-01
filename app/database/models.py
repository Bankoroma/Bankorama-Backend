from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.database import Base


class Plan(Base):
    __tablename__ = "plans"

    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False)
    name = Column(String(60), nullable=False)
    price_ttc = Column(Numeric(10, 2), nullable=False)
    monthly_credits = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    raison_sociale = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    credits = Column(Integer, nullable=False, default=0)

    # "user" | "admin"
    role = Column(String(20), nullable=False, default="user")

    plan_id = Column(Integer, ForeignKey("plans.id"), nullable=True)

    # "pending" | "active" | "suspended"
    subscription_status = Column(String(20), nullable=False, default="pending")
    subscription_activated_at = Column(DateTime(timezone=True), nullable=True)
    credits_renew_at = Column(DateTime(timezone=True), nullable=True)

    plan = relationship("Plan", lazy="joined")


class Conversion(Base):
    __tablename__ = "conversions"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=False)
    pages = Column(Integer, nullable=False, default=0)
    credits_used = Column(Integer, nullable=False, default=0)

    # "success" | "failed"
    status = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
