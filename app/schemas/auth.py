from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    raison_sociale: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(max_length=128)
    confirm_password: str = Field(max_length=128)
    plan_code: str = Field(max_length=30)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class PlanOut(BaseModel):
    code: str
    name: str
    price_ttc: Decimal
    monthly_credits: int

    model_config = {"from_attributes": True}


class MeOut(BaseModel):
    id: int
    raison_sociale: str
    email: str
    credits: int
    role: str
    subscription_status: str
    subscription_activated_at: datetime | None
    credits_renew_at: datetime | None
    plan: PlanOut | None

    model_config = {"from_attributes": True}


class ConversionOut(BaseModel):
    id: int
    filename: str
    pages: int
    credits_used: int
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserOut(MeOut):
    is_active: bool
    created_at: datetime
    conversions_count: int = 0


class ActivateRequest(BaseModel):
    plan_code: str | None = Field(default=None, max_length=30)
