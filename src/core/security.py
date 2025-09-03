# src/core/security.py
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

import bcrypt
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from firebase_admin import auth
from jose import jwt, JWTError

from src.config import config

logger = logging.getLogger(config.app.service_name)

# Создаем пул потоков для выполнения блокирующих операций с ограничением
_executor = None

def get_executor():
    """Получить или создать ThreadPoolExecutor для bcrypt операций"""
    global _executor
    if _executor is None:
        # Для bcrypt операций достаточно небольшого пула
        max_workers = min(4, os.cpu_count() or 1)
        _executor = ThreadPoolExecutor(max_workers=max_workers)
        logger.info(f"Создан ThreadPoolExecutor для bcrypt с {max_workers} потоками")
    return _executor


def cleanup_executor():
    """Корректно завершить работу executor при остановке приложения"""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
        logger.info("ThreadPoolExecutor для bcrypt завершен")


# Функция для выполнения хеширования в пуле потоков
async def async_hash_password(password: str) -> str:
    loop = asyncio.get_running_loop()
    executor = get_executor()
    hashed = await loop.run_in_executor(executor, bcrypt.hashpw, password.encode('utf-8'), bcrypt.gensalt())
    return hashed.decode('utf-8')


# Функция для выполнения проверки пароля
async def async_verify_password(password: str, hashed_password: str) -> bool:
    loop = asyncio.get_running_loop()
    executor = get_executor()
    return await loop.run_in_executor(executor, bcrypt.checkpw, password.encode('utf-8'),
                                      hashed_password.encode('utf-8'))


# OAuth2 схема
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token")


async def create_token(
        data: Dict[str, Any],
        expires_delta: timedelta,
        secret_key: str
) -> str:
    """Создание JWT токена"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode.update({"exp": expire})

    try:
        return jwt.encode(
            to_encode,
            secret_key,
            algorithm=config.auth.algorithm
        )
    except Exception as e:
        logger.error(f"Token creation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create token"
        )


async def verify_token(secret_key: str, token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, secret_key, algorithms=[config.auth.algorithm])
        email: str = payload.get("email")
        user_id: int = payload.get("user_id")
        expires = payload.get("exp")
        if expires < datetime.now().timestamp():
            logger.debug("token expires")
            raise credentials_exception
        if email is None:
            logger.debug("not email")
            raise credentials_exception
        return email, user_id
    except JWTError:
        raise credentials_exception


async def verify_supabase_token(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid Supabase token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, config.supabase.jwt_secret.get_secret_value(), algorithms=[config.supabase.algorithm])
        email: str = payload.get("email")
        user_id: str = payload.get("sub")  # в sub у Supabase UUID пользователя
        avatar_url: str = payload.get("avatar_url")
        full_name: str = payload.get("full_name")
        exp = payload.get("exp")

        if exp < datetime.now().timestamp():
            raise credentials_exception
        if not email:
            raise credentials_exception

        return email, user_id, avatar_url, full_name

    except JWTError:
        raise credentials_exception


def get_firebase_user(token):
    """Get the user details from Firebase, based on TokenID in the request

    :param token: id_token
    """
    logger.debug(f"id_token: {token}")
    if not token:
        raise HTTPException(status_code=400, detail='TokenID must be provided')

    try:
        claims = auth.verify_id_token(token)
        return claims
    except Exception as e:
        logger.debug(e)
        raise HTTPException(status_code=401, detail='Unauthorized')


def get_supabase_user(token):
    if not token:
        raise HTTPException(status_code=400, detail='TokenID must be provided')
    header = jwt.get_unverified_header(token)

    kid = header.get("kid")

    # Получаем JWKS
    project_id = config.supabase.project_id
    # JWKS URL
    jwks_url = f"https://{project_id}.supabase.co/auth/v1/.well-known/jwks.json"
    resp = httpx.get(jwks_url, timeout=10)
    jwks = resp.json()

    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[key["alg"]],
            audience="authenticated",  # можно указать client_id или None
        )
        return claims
    except Exception as e:
        logger.debug(e)
        raise HTTPException(status_code=401, detail='Unauthorized')


if __name__ == "__main__":

    token = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwNmE5NTlhLWEyYTItNDk1Zi1hZWQyLTk1NDJmZmM5NmE4ZSIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2NmbmR6anBoamlrbnJtcHZtZXVtLnN1cGFiYXNlLmNvL2F1dGgvdjEiLCJzdWIiOiJjOTYwYzIwMy05OTk3LTQwZjMtYWJiMi1iNjFmZGZmNjEwMjkiLCJhdWQiOiJhdXRoZW50aWNhdGVkIiwiZXhwIjoxNzU2MzY3Mjg0LCJpYXQiOjE3NTYzNjM2ODQsImVtYWlsIjoiZWR1YXJkLmRlbWVyY2h5YW5AZ21haWwuY29tIiwicGhvbmUiOiIiLCJhcHBfbWV0YWRhdGEiOnsicHJvdmlkZXIiOiJnb29nbGUiLCJwcm92aWRlcnMiOlsiZ29vZ2xlIl19LCJ1c2VyX21ldGFkYXRhIjp7ImF2YXRhcl91cmwiOiJodHRwczovL2xoMy5nb29nbGV1c2VyY29udGVudC5jb20vYS9BQ2c4b2NMdzJtSFRYcExRemRMWGNZNmsyUXFadmdJemktOFByeXc0Y3djM3l0NkJwbjE2VHc9czk2LWMiLCJlbWFpbCI6ImVkdWFyZC5kZW1lcmNoeWFuQGdtYWlsLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjp0cnVlLCJmdWxsX25hbWUiOiLQrdC00YPQsNGA0LQg0JTQtdC80LXRgNGH0Y_QvSIsImlzcyI6Imh0dHBzOi8vYWNjb3VudHMuZ29vZ2xlLmNvbSIsIm5hbWUiOiLQrdC00YPQsNGA0LQg0JTQtdC80LXRgNGH0Y_QvSIsInBob25lX3ZlcmlmaWVkIjpmYWxzZSwicGljdHVyZSI6Imh0dHBzOi8vbGgzLmdvb2dsZXVzZXJjb250ZW50LmNvbS9hL0FDZzhvY0x3Mm1IVFhwTFF6ZExYY1k2azJRcVp2Z0l6aS04UHJ5dzRjd2MzeXQ2QnBuMTZUdz1zOTYtYyIsInByb3ZpZGVyX2lkIjoiMTAwNjI3OTI5ODQ0NTI5NTAyOTc4Iiwic3ViIjoiMTAwNjI3OTI5ODQ0NTI5NTAyOTc4In0sInJvbGUiOiJhdXRoZW50aWNhdGVkIiwiYWFsIjoiYWFsMSIsImFtciI6W3sibWV0aG9kIjoib2F1dGgiLCJ0aW1lc3RhbXAiOjE3NTYzNjM2ODR9XSwic2Vzc2lvbl9pZCI6Ijc2MzgzYmE1LTYyZTctNDQyNy04M2M2LTYzMDEzMThkNWRlZCIsImlzX2Fub255bW91cyI6ZmFsc2V9.9t3dv5zRHpse_NFDTEFzPpT_eC_LWFWbbJw-5WnAjLK0oQFL27Z9eBNptbBoeizYaLZikhDue3VRSOIQV_4C9A"
    # token = "eyJhbGciOiJSUzI1NiIsImtpZCI6ImVmMjQ4ZjQyZjc0YWUwZjk0OTIwYWY5YTlhMDEzMTdlZjJkMzVmZTEiLCJ0eXAiOiJKV1QifQ.eyJuYW1lIjoi0K3QtNGD0LDRgNC0INCU0LXQvNC10YDRh9GP0L0iLCJwaWN0dXJlIjoiaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2EvQUNnOG9jTHcybUhUWHBMUXpkTFhjWTZrMlFxWnZnSXppLThQcnl3NGN3YzN5dDZCcG4xNlR3PXM5Ni1jIiwiaXNzIjoiaHR0cHM6Ly9zZWN1cmV0b2tlbi5nb29nbGUuY29tL3NjYW5uc3BsaXQtZjhjNWYiLCJhdWQiOiJzY2FubnNwbGl0LWY4YzVmIiwiYXV0aF90aW1lIjoxNzU2MzU2NDUyLCJ1c2VyX2lkIjoiSVBja0JpNDBINWFXQ2VRN1dZdHh3cVRKQm1VMiIsInN1YiI6IklQY2tCaTQwSDVhV0NlUTdXWXR4d3FUSkJtVTIiLCJpYXQiOjE3NTYzNTY0NTIsImV4cCI6MTc1NjM2MDA1MiwiZW1haWwiOiJlZHVhcmQuZGVtZXJjaHlhbkBnbWFpbC5jb20iLCJlbWFpbF92ZXJpZmllZCI6dHJ1ZSwiZmlyZWJhc2UiOnsiaWRlbnRpdGllcyI6eyJnb29nbGUuY29tIjpbIjEwMDYyNzkyOTg0NDUyOTUwMjk3OCJdLCJlbWFpbCI6WyJlZHVhcmQuZGVtZXJjaHlhbkBnbWFpbC5jb20iXX0sInNpZ25faW5fcHJvdmlkZXIiOiJnb29nbGUuY29tIn19.e_wyBnXwrYY7HkhVczcY-GfUyeSfcju-yYzoyPivuhKAQLiy3Hw43NlA91Qx3gZKnVB9ZzBsntmGlOAj9HZuH7tJA-lQQ_z3wRnLyavymMKdIBMgQxCFlghRftcoEiMhasAOC2JWADLN8ReiaXKqhNLY_BORNxAF1mX412ea0RObKi2WfVXEcu3P-BKHyhfgqC7T642-oPRFZ_IBQniWLuL9nqAH-LluPfIFNOdQnGVF8_QFAzvrbQcdV40eDBxD_wHrtkqAFz_xM1zT6V9UCWOs6eqIspe8QfWaKtnzThFBNEga61JOIcxOclY7nVEcZtmqygugUnp7D7udMgb6tg"

    algorithm = "HS256"
    jwt_secret = ""

    header = jwt.get_unverified_header(token)
    claims = jwt.get_unverified_claims(token)
    print(f"claims: {claims}")

    iss: Optional[str] = claims.get("iss")
    alg: Optional[str] = header.get("alg")


    # === Heuristics ===
    # Supabase:
    #   iss: https://<ref>.supabase.co/auth/v1
    #   alg: HS256, kid обычно отсутствует
    if iss and ".supabase.co/auth/v1" in iss:
        print("Supabase")
        claims = get_supabase_user(token)
        print(f"claims: {claims}")

    # Firebase ID token:
    #   iss: https://securetoken.google.com/<project-id>
    #   aud: <project-id>
    #   alg: RS256, есть kid
    if iss and iss.startswith("https://securetoken.google.com/"):
        print("Firebase")

    # print(payload)