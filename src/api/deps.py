import logging
from typing import Optional

from fastapi import Request, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from starlette.websockets import WebSocket

from src.config import config
from src.core.security import verify_token, get_firebase_user, get_supabase_user
from src.redis.utils import get_token_from_redis, add_token_to_redis
from src.repositories.user import get_user_by_email, unmark_user_as_deleted
from src.services.auth import get_auth_service

logger = logging.getLogger(config.app.service_name)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


# === УТИЛИТЫ ===

async def resolve_email_from_token(token: str, service: str) -> str:
    """
    Определяет email по токену (Supabase/Firebase).
    Данные Firebase кэшируются в Redis.
    """
    if service == "Supabase":
        claims = get_supabase_user(token=token)
        return claims.get("email")

    if service == "Firebase":
        claims = await get_token_from_redis(token)
        if not claims:
            claims = get_firebase_user(token)
            await add_token_to_redis(token, claims)
        return claims.get("email")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Сервис не поддерживается")


async def get_user_or_401(email: Optional[str]):
    """
    Достаёт пользователя по email.
    Если нет — кидает 401.
    """
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Email не найден в токене")

    user = await get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Пользователь не найден")

    if user.is_soft_deleted:
        await unmark_user_as_deleted(user)

    return user


async def get_email_from_request(
    request: Request,
    oauth2_token: Optional[str],
    http_auth: Optional[HTTPAuthorizationCredentials]
) -> str:
    """
    Унифицированная логика выбора источника email (cookie, OAuth2, Firebase, Authorization header).
    """
    # 0. Cookie
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        logger.debug("Приоритет 0: access_token из cookie")
        email, _ = await verify_token(config.auth.access_secret_key.get_secret_value(), cookie_token)
        return email

    # 1. OAuth2
    if oauth2_token:
        logger.debug("Приоритет 1: OAuth2 токен")
        email, _ = await verify_token(config.auth.access_secret_key.get_secret_value(), oauth2_token)
        return email

    # 2. Firebase Bearer
    if http_auth:
        logger.debug("Приоритет 2: Firebase токен (Bearer)")
        return await resolve_email_from_token(http_auth.credentials, "Firebase")

    # 3. Authorization header вручную
    auth_header = request.headers.get("Authorization")
    if auth_header:
        logger.debug("Приоритет 3: Authorization header")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header
        service = get_auth_service(token)
        return await resolve_email_from_token(token, service)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Не предоставлен токен авторизации",
                        headers={"WWW-Authenticate": "Bearer"})


# === ЗАВИСИМОСТИ ===

async def get_current_user(
    request: Request,
    oauth2_token: Optional[str] = Depends(oauth2_scheme),
    http_auth: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
):
    try:
        email = await get_email_from_request(request, oauth2_token, http_auth)
        return await get_user_or_401(email)

    except (HTTPException, JWTError) as e:
        if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
            return None
        raise e if isinstance(e, HTTPException) else HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        if request.url.path in ["/docs", "/redoc", "/openapi.json"]:
            return None
        logger.exception(e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Не удалось проверить учетные данные",
                            headers={"WWW-Authenticate": "Bearer"})


async def get_current_user_for_websocket(websocket: WebSocket):
    try:
        token = websocket.query_params.get("token")      # OAuth2
        id_token = websocket.query_params.get("id_token")  # Supabase/Firebase

        if token:
            email, _ = await verify_token(config.auth.access_secret_key.get_secret_value(), token)
        elif id_token:
            service = get_auth_service(id_token)
            logger.debug(f"get_current_user_for_websocket auth service: {service}")
            email = await resolve_email_from_token(id_token, service)
            logger.debug(f"get_current_user_for_websocket email: {service}")
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Не предоставлен токен авторизации")

        return await get_user_or_401(email)

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Не удалось проверить учетные данные")
