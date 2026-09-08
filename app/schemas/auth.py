from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    raison_sociale: str
    email: EmailStr
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"