import logging
from datetime import timedelta
from typing import Dict, Optional

from fastapi import HTTPException
from fastapi_mail import FastMail, MessageSchema
from jose import jwt
from starlette import status

from src.config import config
from src.core.security import async_verify_password
from src.core.security import create_token
from src.repositories.user import get_user_by_email

logger = logging.getLogger(config.app.service_name)



def get_auth_service(token: str) -> Optional[str]:
    """
    Определяет источник (сервис) токена по полю 'iss' в claims.

    Args:
        token (str): JWT токен

    Returns:
        Optional[str]: Название сервиса ("Supabase", "Firebase") или None, если сервис не определён
    """
    claims = jwt.get_unverified_claims(token)
    iss = claims.get("iss")

    if not iss:
        return None

    if ".supabase.co/auth/v1" in iss:
        return "Supabase"

    if iss.startswith("https://securetoken.google.com/"):
        return "Firebase"

    return None


async def authenticate_user(email: str, password: str):
    user = await get_user_by_email(email)
    if not user or not await async_verify_password(password, user.hashed_password):
        return False
    return user


async def generate_tokens(email: str, user_id: int) -> Dict[str, str]:
    """Генерация access и refresh токенов"""
    access_token = await create_token(
        data={"email": email, "user_id": user_id},
        expires_delta=timedelta(minutes=config.auth.access_token_expire_minutes),
        secret_key=config.auth.access_secret_key.get_secret_value()
    )

    refresh_token = await create_token(
        data={"email": email, "user_id": user_id},
        expires_delta=timedelta(days=config.auth.refresh_token_expire_days),
        secret_key=config.auth.refresh_secret_key.get_secret_value()
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


async def send_password_reset_email(email: str, reset_token: str, fastmail: FastMail):
    reset_url = f"{config.app.base_url}/reset-password?token={reset_token}"

    message = MessageSchema(
        subject="Сброс пароля",
        recipients=[email],
        template_body={
            "reset_url": reset_url,
            "expire_minutes": config.auth.access_token_expire_minutes
        }
    )

    # Используем шаблон для письма
    template_name = "password_reset.html"

    try:
        await fastmail.send_message(message, template_name=template_name)
        logger.info(f"Password reset email sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send password reset email"
        )
