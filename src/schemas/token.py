from datetime import datetime

from pydantic import BaseModel, EmailStr


class TokenResponse(BaseModel):
    """Модель токена"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Полезная нагрузка токена"""
    email: EmailStr
    user_id: int
    exp: datetime


class RefreshTokenRequest(BaseModel):
    """Запрос на обновление токена"""
    refresh_token: str


class IDTokenRequest(BaseModel):
    """Запрос на получение токенов"""
    id_token: str


class PasswordReset(BaseModel):
    token: str
    new_password: str


# Модель для входящих данных
class AuthRequest(BaseModel):
    token: str
    platform: str  # ios/android
    type: str
