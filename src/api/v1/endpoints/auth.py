import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from firebase_admin import auth
from google.oauth2 import id_token as google_id_token             # валидация ID-токена Google
from google.auth.transport import requests as google_auth_requests # HTTP-транспорт для google-auth
from starlette import status

from src.config import config
from src.core.security import get_supabase_user
from src.redis.utils import add_token_to_redis, get_token_from_redis
from src.repositories.user import get_user_by_email, create_new_user
from src.schemas import UserCreate, TokenResponse, IDTokenRequest
from src.services.auth import get_auth_service, generate_tokens

logger = logging.getLogger(config.app.service_name)

router = APIRouter()

OAUTH_PASSWORD_PLACEHOLDER = "!OAUTH_NO_PASSWORD!"


@router.post("/", summary="Авторизация через Firebase или Supabase")
async def auth_callback(id_token: str, lang: Optional[str] = "en"):
    """
    Унифицированная точка входа для авторизации.
    Поддерживает Firebase и Supabase токены.
    """
    logger.debug(f"id_token: {id_token}")

    try:
        service = get_auth_service(id_token)
        if not service:
            raise HTTPException(status_code=400, detail="Unknown authentication service")

        if service == "Firebase":
            # Проверяем в Redis
            claims = await get_token_from_redis(id_token)
            if not claims:
                claims = auth.verify_id_token(id_token)
                await add_token_to_redis(id_token, claims)

            email = claims.get("email")
            avatar_url = claims.get("picture")
            full_name = claims.get("name")

        elif service == "Supabase":
            claims = get_supabase_user(token=id_token)

            email = claims.get("email") or claims.get("user_metadata", {}).get("email")
            avatar_url = claims.get("user_metadata", {}).get("avatar_url")
            full_name = claims.get("user_metadata", {}).get("full_name")

        else:
            raise HTTPException(status_code=400, detail="Unsupported service")

        logger.debug(f"auth user: {email}, {avatar_url}")

        # Ищем пользователя в БД
        user = await get_user_by_email(email)
        if not user:
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
        logger.error(f"Invalid token: {e}")
        raise HTTPException(status_code=400, detail="Invalid token")
    except Exception as e:
        logger.error(f"Unexpected error during authentication: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication failed")


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


@router.post(
    "/google",
    summary="Авторизация по Google ID Token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Invalid Google ID token"},
        500: {"description": "Internal server error"},
    },
)
async def login_google_token(request: IDTokenRequest, lang: Optional[str] = "en"):
    """
    Принимает **Google ID Token** (OIDC), валидирует его и возвращает нашу пару токенов.
    """
    logger.debug("Начата авторизация через Google ID Token")

    try:
        # Верификация токена
        claims = google_id_token.verify_oauth2_token(
            request.id_token,
            google_auth_requests.Request(),
            config.auth.google_client_id.get_secret_value()
        )

        # Валидация обязательных полей
        email = claims.get('email')
        if not email:
            logger.warning("Токен не содержит email")
            raise HTTPException(
                status_code=401,
                detail="Email not found in token"
            )

        # Проверка верификации email
        if not claims.get('email_verified', False):
            logger.warning(f"Email не верифицирован: {email}")
            raise HTTPException(
                status_code=401,
                detail="Email not verified by Google"
            )

        logger.debug(f"Успешная верификация токена для email: {email}")

        # Поиск или создание пользователя
        user = await get_user_by_email(email)
        if not user:
            logger.info(f"Создание нового пользователя: {email}")
            user = await create_new_user(
                user_data=UserCreate(
                    email=email,
                    password=OAUTH_PASSWORD_PLACEHOLDER
                ),
                profile_data={
                    "nickname": claims.get("name", ""),
                    "language": lang,
                    "avatar_url": claims.get("picture")
                }
            )

        # Генерация токенов
        tokens = await generate_tokens(user.email, user.id)
        logger.info(f"Успешная авторизация пользователя: {email}")
        return {
            "access_token": tokens.get("id_token"),
            "refresh_token": tokens.get("refresh_token")
        }

    except ValueError as e:
        # Ошибка верификации токена Google
        logger.warning(f"Невалидный Google ID token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Google ID token"
        )
    except HTTPException:
        # Пробрасываем HTTP исключения как есть
        raise
    except Exception as e:
        # Неожиданные ошибки
        logger.error(f"Ошибка при Google аутентификации: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal authentication error"
        )
