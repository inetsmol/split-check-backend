import logging
import uuid
from typing import Dict, Optional

from fastapi import APIRouter, Depends, status, HTTPException, Response
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from jose import JWTError
from starlette.requests import Request

from fastapi import Body
from firebase_admin import auth

from src.config import config
from src.core.security import verify_token
from src.repositories.user import get_user_by_email, create_new_user
from src.schemas import RefreshTokenRequest, TokenResponse, UserCreate
from src.services.auth import authenticate_user, generate_tokens

logger = logging.getLogger(config.app.service_name)

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")


@router.post(
    "/google",
    summary="Авторизация по Google ID Token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Bad request"},
        401: {"description": "Invalid Google ID token"},
        404: {"description": "User not found and cannot be created"},
    },
)
async def login_google_token(id_token: str, lang: Optional[str] = "en"):
    """
    Принимает **Google ID Token** (OIDC), валидирует его и возвращает нашу пару токенов.
    """
    logger.debug("Получен Google id_token (обрезано в логах)")

    try:

        claims = auth.verify_id_token(id_token)
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
        tokens = await generate_tokens(user.email, user.id)

        return tokens

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


# Эндпоинт для получения access_token и refresh_token
@router.post(
    "",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Incorrect username or password"},
        429: {"description": "Too many login attempts"},
    }
)
async def login_for_access_token(request: Request,
                                 response: Response,
                                 form_data: OAuth2PasswordRequestForm = Depends()
                                 ) -> Dict[str, str]:
    """Login endpoint to obtain access and refresh tokens."""
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tokens = await generate_tokens(user.email, user.id)

    # Установить refresh token в HTTP-only cookie
    response.set_cookie(
        key="refresh_token",
        value=tokens["refresh_token"],
        httponly=False,
        secure=False,  # для HTTPS
        samesite="strict",
        max_age=config.auth.refresh_token_expire_minutes * 60
    )

    # Также сохраним access_token в куки
    response.set_cookie(
        key="access_token",
        value=tokens["access_token"],
        httponly=False,
        secure=False,
        samesite="strict",
        max_age=config.auth.access_token_expire_minutes * 60
    )

    return tokens


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"description": "Invalid refresh token"}
    }
)
async def refresh_access_token(request: RefreshTokenRequest, response: Response) -> Dict[str, str]:
    """Refresh access token using either cookie or request body."""
    token = request.refresh_token

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is missing"
        )

    try:
        email, user_id = await verify_token(
            secret_key=config.auth.refresh_secret_key.get_secret_value(),
            token=token
        )
        tokens = await generate_tokens(email, user_id)

        # Обновляем куки с новыми токенами
        response.set_cookie(
            key="refresh_token",
            value=tokens["refresh_token"],
            httponly=False,
            secure=False,
            samesite="strict",
            max_age=config.auth.refresh_token_expire_minutes * 60
        )

        response.set_cookie(
            key="access_token",
            value=tokens["access_token"],
            httponly=False,
            secure=False,
            samesite="strict",
            max_age=config.auth.access_token_expire_minutes * 60
        )

        return tokens
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token"
        )


@router.post("/logout")
async def logout(response: Response):
    """Clear all token cookies."""
    response.delete_cookie(
        key="refresh_token",
        secure=False,
        httponly=False
    )
    response.delete_cookie(
        key="access_token",
        secure=False,
        httponly=False
    )

    return {"message": "Successfully logged out"}


@router.get("/ping")
async def token_ping(token: str = Depends(oauth2_scheme)):
    return {"status": "ok"}
