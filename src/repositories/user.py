# src/repositories/user.py
import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError, DatabaseError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.config import config
from src.core.security import async_hash_password
from src.models import User, user_check_association, Check, UserProfile
from src.schemas import UserCreate
from src.services.exemple_checks import pick_exemple_check_by_locale
from src.utils.db import with_db_session

logger = logging.getLogger(config.app.service_name)


@with_db_session()
async def create_new_user(
        session: AsyncSession,
        user_data: UserCreate,
        profile_data: Optional[dict] = None
) -> User:
    """
    Создает нового пользователя и его профиль в базе данных.

    Args:
        session (AsyncSession): Асинхронная сессия базы данных.
        user_data (UserCreate): Модель с данными для создания пользователя.
        profile_data (dict, optional): Данные для создания профиля пользователя.

    Returns:
        User: Объект нового пользователя, если успешно создан.

    Raises:
        DatabaseError: Ошибка при создании пользователя.
    """
    # получаем локаль
    if profile_data and profile_data.get("language"):
        locale = profile_data.get("language")
    else:
        locale = user_data.lang
        # нормализуем профиль и гарантируем наличие ключа "language"
        profile_data = dict(profile_data or {})  # создаём копию, чтобы не мутировать входной словарь
        profile_data["language"] = locale  # фиксируем язык в profile_data
    try:
        # Проверка на существование пользователя с таким email
        existing_user = (await session.execute(
            select(User).where(User.email == user_data.email)
        )).scalars().first()

        if existing_user:
            raise ValueError(f"User with email {user_data.email} already exists")

        # Хешируем пароль
        hashed_password = await async_hash_password(user_data.password)

        # Создаем профиль с данными, если они предоставлены
        profile = UserProfile(**(profile_data or {}))


        # Создаём пользователя с вложенным профилем
        new_user = User(
            email=user_data.email,
            hashed_password=hashed_password,
            profile=profile
        )
        session.add(new_user)
        # Сохраняем изменения в базе данных

        await session.commit()
        await session.refresh(new_user)

        # создаем пробный чек

        # Берем подходящий шаблон чека
        check_data = pick_exemple_check_by_locale(locale)
        # Добавляем его для нашего пользователя
        from src.repositories.check import add_check_to_database

        check_uuid = str(uuid.uuid4())
        await add_check_to_database(session, check_uuid, new_user.id, check_data)

        return new_user

    except IntegrityError as e:
        logger.error(f"Integrity error while creating user: {e}")
        await session.rollback()
        raise DatabaseError(
            "Failed to create user due to integrity constraint",
            params={"email": user_data.email},
            orig=e
        ) from e
    except Exception as e:
        logger.error(f"Unexpected error while creating user: {e}")
        await session.rollback()
        raise DatabaseError(
            "Failed to create user due to unexpected error",
            params={"email": user_data.email},
            orig=e
        ) from e


@with_db_session()
async def get_user_by_email(session, email: str) -> Optional[User]:
    """Получение пользователя по email."""
    try:
        stmt = select(User).filter_by(email=email)
        result = await session.execute(stmt)
        return result.scalars().first()
    except SQLAlchemyError as e:
        logger.error(f"Database error while fetching user with email {email}: {str(e)}")
        return None


async def get_user_by_id(session, user_id: int) -> Optional[User]:
    """Получение пользователя по ID."""
    stmt = (select(User)
            .options(joinedload(User.checks))
            .options(joinedload(User.profile))
            .filter_by(id=user_id))
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_users_by_check_uuid(session, check_uuid: str) -> List[User]:
    """Получение списка пользователей по UUID чека."""
    query = (
        select(User)
        .options(joinedload(User.profile))
        .join(user_check_association, User.id == user_check_association.c.user_id)
        .join(Check, Check.uuid == user_check_association.c.check_uuid)
        .where(Check.uuid == check_uuid)
    )
    result = await session.execute(query)
    return result.scalars().all()


@with_db_session()
async def mark_user_as_deleted(session: AsyncSession, user_id: int) -> None:
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(
            is_soft_deleted=True,
            soft_deleted_at=datetime.now()
        )
    )
    await session.execute(stmt)
    await session.commit()


@with_db_session()
async def unmark_user_as_deleted(session: AsyncSession, user: User) -> None:
    """
    Снимает отметку об удалении пользователя

    Args:
        session: Сессия базы данных
        user: Пользователь, с которого нужно снять отметку об удалении
    """
    try:
        # Вместо прямого изменения объекта, используем SQL-запрос для обновления
        stmt = (
            update(User)
            .where(User.id == user.id)
            .values(
                is_soft_deleted=False,
                soft_deleted_at=None
            )
        )
        await session.execute(stmt)

        # Обновляем объект user в текущей сессии
        user.is_soft_deleted = False
        user.soft_deleted_at = None

        logger.debug(f"email: {user.email} is_soft_deleted: {user.is_soft_deleted}")

        await session.commit()
    except SQLAlchemyError as e:
        logger.error(f"Database error : {str(e)}")
        # Здесь также можно добавить откат транзакции, если его нет в декораторе
        await session.rollback()


@with_db_session()
async def user_delete(session: AsyncSession) -> None:
    cutoff_date = datetime.now() - timedelta(days=30)

    # Выбираем пользователей, помеченных на удаление более 30 дней назад
    stmt = (
        select(User)
        .options(joinedload(User.profile))
        .where(
            User.is_soft_deleted == True,
            User.soft_deleted_at < cutoff_date,
            User.is_deleted == False  # ещё не были физически удалены
        )
    )
    result = await session.execute(stmt)
    users = result.scalars().all()

    for user in users:
        # Анонимизируем email
        masked_email = f"{uuid.uuid4()}@masked_domain.ru"
        user.email = masked_email
        user.is_deleted = True

        # Очистка профиля
        if user.profile:
            user.profile.nickname = None
            user.profile.avatar_url = None

    await session.commit()