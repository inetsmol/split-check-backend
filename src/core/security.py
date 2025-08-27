# src/core/security.py
import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
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