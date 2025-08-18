# src/repositories/user_selection.py
import json
import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from src.config import config
from src.models import UserSelection
from src.redis import redis_client

logger = logging.getLogger(config.app.service_name)


async def add_or_update_user_selection(session: AsyncSession, user_id: int, check_uuid: str, selection_data: dict):
    """
    Добавить или обновить запись в таблице user_selections.
    Если запись существует, она будет обновлена, если нет — будет создана новая запись.
    :param session: Сессионный объект базы данных
    :param user_id: Идентификатор пользователя
    :param check_uuid: UUID чека
    :param selection_data: Данные, которые нужно сохранить в формате JSON
    """
    logger.debug(f"Обновление записи selection_data={selection_data}")
    try:
        # Проверяем, существует ли запись с таким user_id и check_uuid
        stmt = select(UserSelection).filter_by(user_id=user_id, check_uuid=check_uuid)
        result = await session.execute(stmt)
        user_selection = result.scalars().first()

        # Обновляем или создаем новую запись
        if user_selection:
            user_selection.selection = selection_data
            logger.debug(f"Запись для user_id={user_id}, check_uuid={check_uuid} обновлена.")
        else:
            new_selection = UserSelection(
                user_id=user_id,
                check_uuid=check_uuid,
                selection=selection_data
            )
            session.add(new_selection)
            logger.debug(f"Создана новая запись для user_id={user_id}, check_uuid={check_uuid}.")

        # Сохраняем изменения в базе данных
        await session.commit()

        # После успешного сохранения в БД — добавляем данные в Redis
        redis_key = f"user_selection:{user_id}:{check_uuid}"
        await redis_client.set(redis_key, json.dumps(selection_data), expire=config.redis.expiration)
        logger.debug(f"Данные сохранены в Redis для ключа {redis_key}")

    except Exception as e:
        logger.error(f"Ошибка добавления или обновления записи: {e}")

        # Поднимаем общее исключение с деталями ошибки
        raise Exception(f"Ошибка при обновлении данных пользователя: {str(e)}")


async def get_user_selection_by_user(session: AsyncSession, user_id: int, check_uuid: str):
    stmt = select(UserSelection).filter_by(user_id=user_id, check_uuid=check_uuid)
    result = await session.execute(stmt)
    user_selections = result.scalars().first()
    return user_selections


async def delete_user_selection_by_user_id(session: AsyncSession, check_uuid: str, user_id: int):
    try:
        stmt = (
            delete(UserSelection)
            .where(UserSelection.user_id == user_id)
            .where(UserSelection.check_uuid == check_uuid)
        )
        await session.execute(stmt)
        await session.commit()

        # После успешного сохранения в БД — удаляем данные из Redis
        redis_key = f"user_selection:{user_id}:{check_uuid}"
        await redis_client.delete(redis_key)
        logger.debug(f"Данные удалены из Redis для ключа {redis_key}")

    except Exception as e:
        logger.error(e)


async def get_user_selection_by_check_uuid(session: AsyncSession, check_uuid: str):
    from src.repositories.user import get_users_by_check_uuid
    users = await get_users_by_check_uuid(session, check_uuid)
    logger.debug(f"Получили пользователей: {', '.join([str(user) for user in users])}")

    participants = []
    user_selections = []

    for user in users:
        redis_key = f"user_selection:{user.id}:{check_uuid}"

        # Пытаемся получить данные из Redis или БД
        selection_data = {}
        redis_data = await redis_client.get(redis_key)

        if redis_data:
            selection_data = json.loads(redis_data)
        else:
            user_selection = await get_user_selection_by_user(session=session,
                                                              user_id=user.id,
                                                              check_uuid=check_uuid)
            if user_selection:
                selection_data = user_selection.selection

        logger.debug(f"Получили selection_data: {selection_data}")

        # Создаем структуру для каждого участника
        participant = {
                "user_id": user.id,
                "nickname": user.profile.nickname,
                "avatar_url": user.profile.avatar_url,
            }
        all_user_selection = {
            "user_id": user.id,
            "selected_items": [
                {
                    "item_id": item["item_id"],
                    "quantity": item["quantity"]
                }
                for item in selection_data.get("selected_items", [])
            ]
        }

        participants.append(participant)
        user_selections.append(all_user_selection)

    logger.debug(f"Получили participants: {participants}")

    return json.dumps(participants), json.dumps(user_selections), users


async def delete_item_from_user_selections(session: AsyncSession, check_uuid: str, item_id: int):
    from src.repositories.user import get_users_by_check_uuid
    users = await get_users_by_check_uuid(session, check_uuid)
    changed = False

    for user in users:
        stmt = select(UserSelection).filter_by(user_id=user.id, check_uuid=check_uuid)
        result = await session.execute(stmt)
        user_selection = result.scalars().first()

        if not user_selection:
            continue

        items = user_selection.selection.get("selected_items", [])
        new_items = [item for item in items if item["item_id"] != item_id]

        if items != new_items:
            user_selection.selection["selected_items"] = new_items
            flag_modified(user_selection, "selection")
            logger.debug(f"Обновлён selection пользователя {user.id}: {new_items}")
            changed = True
            # Обновление кэша Redis
            redis_key = f"user_selection:{user.id}:{check_uuid}"
            await redis_client.set(
                redis_key,
                json.dumps(user_selection.selection),
                expire=config.redis.expiration
            )

    if changed:
        await session.commit()
