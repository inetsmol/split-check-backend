import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from firebase_admin import auth

from src.config import config
from src.redis.utils import add_token_to_redis, get_token_from_redis
from src.repositories.user import get_user_by_email, create_new_user
from src.schemas import UserCreate

from src.core.security import verify_supabase_token

logger = logging.getLogger(config.app.service_name)

router = APIRouter()


@router.post("/firebase", summary="Авторизация через Firebase")
async def auth_callback(id_token, lang: Optional[str] = "en"):
    """
    Обрабатывает OAuth авторизацию для мобильных приложений (Google, другие провайдеры).
    """
    logger.debug(f"id_token: {id_token}")
    try:
        claims = await get_token_from_redis(id_token)
        if not claims:
            claims = auth.verify_id_token(id_token)
            await add_token_to_redis(id_token, claims)
        email = claims.get('email')
        logger.debug(f"user: {claims}")

        user = await get_user_by_email(email)
        if not user:
            # Создаем нового пользователя
            user = await create_new_user(
                user_data=UserCreate(
                    email=email,
                    password=uuid.uuid4().hex
                ),
                profile_data={
                    "nickname": claims.get("name"),
                    "language": lang,
                    "avatar_url": claims.get('picture')
                }
            )

        return {"user_id": user.id}

    except ValueError as e:
        # Ошибка верификации токена
        logger.error(f"Invalid token: {e}")
        raise HTTPException(
            status_code=400,
            detail="Invalid token"
        )
    except Exception as e:
        # Логируем неожиданные ошибки
        logger.error(f"Unexpected error during Google authentication: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Authentication failed"
        )


@router.post("/supabase", summary="Авторизация через Supabase")
async def auth_callback(id_token, lang: Optional[str] = "en"):
    """
    Обрабатывает OAuth авторизацию для мобильных приложений (Google, другие провайдеры).
    """
    logger.debug(f"supabase id_token: {id_token}")
    try:
        email, user_id, avatar_url, full_name = await verify_supabase_token(token=id_token)

        logger.debug(f"auth sb user: {email} {user_id}, {avatar_url}")

        user = await get_user_by_email(email)
        if not user:
            # Создаем нового пользователя
            user = await create_new_user(
                user_data=UserCreate(
                    email=email,
                    password=uuid.uuid4().hex
                ),
                profile_data={
                    "nickname": full_name,
                    "language": lang,
                    "avatar_url": avatar_url
                }
            )

        return {"user_id": user.id}

    except ValueError as e:
        # Ошибка верификации токена
        logger.error(f"Invalid token: {e}")
        raise HTTPException(
            status_code=400,
            detail="Invalid token"
        )
    except Exception as e:
        # Логируем неожиданные ошибки
        logger.error(f"Unexpected error during Google authentication: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Authentication failed"
        )