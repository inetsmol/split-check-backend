from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, EmailStr, constr


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    lang: Optional[str] = "en"
    model_config = ConfigDict(from_attributes=True)


class User(BaseModel):
    id: int
    email: str
    model_config = ConfigDict(from_attributes=True)


class UserProfileBase(BaseModel):
    nickname: Optional[constr(strip_whitespace=True, min_length=1, max_length=50)] = Field(
        None, description="Никнейм пользователя"
    )
    language: Optional[constr(strip_whitespace=True, pattern=r"^[a-z]{2}$")] = Field(
        None, description="Код языка в формате ISO 639-1 (например, 'en' или 'ru')"
    )
    avatar_url: Optional[str] = Field(
        None, description="URL аватара пользователя"
    )

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "nickname": "JohnDoe",
                    "language": "en",
                    "avatar_url": "https://example.com/avatar.jpg"
                }
            ]
        }
    )


class UserProfileUpdate(UserProfileBase):
    """Схема для обновления профиля пользователя."""


class UserProfileResponse(UserProfileBase):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class UserDeleteResponse(BaseModel):
    detail: str