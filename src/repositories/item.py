# src/repositories/item.py
import logging
import math
from typing import Dict, Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.models import Check, CheckItem
from src.repositories.user_selection import delete_item_from_user_selections
from src.utils.check import recalculate_check_totals, to_int, to_float

logger = logging.getLogger(config.app.service_name)


async def get_items_by_check_uuid(session: AsyncSession, check_uuid: str) -> list[CheckItem]:
    """
    Получение всех позиций чека по его UUID.

    Args:
        session: AsyncSession - сессия базы данных
        check_uuid: str - UUID чека

    Returns:
        list[CheckItem]: Список объектов CheckItem с атрибутами id, name, quantity, sum

    Raises:
        Exception: Если чек не найден или произошла ошибка при запросе
    """
    try:
        # Получаем все позиции чека
        stmt = select(CheckItem).where(CheckItem.check_uuid == check_uuid)
        result = await session.execute(stmt)
        items = result.scalars().all()

        # Если позиций нет, проверяем существование чека
        if not items:
            stmt_check = select(Check).where(Check.uuid == check_uuid)
            result_check = await session.execute(stmt_check)
            check = result_check.scalars().first()
            if not check:
                raise Exception(f"Check with UUID {check_uuid} not found")

        logger.debug(f"Retrieved {len(items)} items for check {check_uuid}")

        return list(items)  # Возвращаем список объектов CheckItem

    except Exception as e:
        logger.error(f"Error retrieving items for check {check_uuid}: {e}")
        raise


# refac
async def remove_item_from_check(session: AsyncSession, check_uuid: str, item_id: int) -> dict:
    """
    Удаление элемента из чека по его id

    Args:
        session: AsyncSession - сессия базы данных
        check_uuid: str - UUID чека
        item_id: int - ID позиции для удаления

    Returns:
        dict: Удаленная позиция

    Raises:
        Exception: Если чек не найден или позиция не найдена
    """

    try:
        # 1. Найти и удалить нужный элемент
        stmt = select(CheckItem).where(
            CheckItem.check_uuid == check_uuid,
            CheckItem.item_id == item_id
        )
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()

        if not item:
            raise ValueError(f"Item with item_id={item_id} not found in check {check_uuid}")

        removed_item = {
            "item_id": item.item_id,
            "name": item.name,
            "quantity": item.quantity,
            "sum": item.sum
        }

        await session.delete(item)
        # await session.flush()  # удаляем до перенумерации
        #
        # # 2. Перенумерация оставшихся позиций
        # stmt = select(CheckItem).where(CheckItem.check_uuid == check_uuid).order_by(CheckItem.item_id)
        # result = await session.execute(stmt)
        # items = result.scalars().all()
        #
        # for new_index, item in enumerate(items, start=1):
        #     item.item_id = new_index

        await session.commit()

        # Пересчитываем все поля
        await recalculate_check_totals(session, check_uuid)

        await delete_item_from_user_selections(session, check_uuid, item_id)

        return removed_item
    except Exception as e:
        logger.error(f"Ошибка при удалении позиции: {e}")
        raise


async def add_item_to_check(session: AsyncSession, check_uuid: str, item_data: dict) -> dict:
    """Добавление элемента в чек и возврат обновленного объекта Check"""
    try:
        # Проверяем существование чека
        stmt = select(Check).where(Check.uuid == check_uuid)
        result = await session.execute(stmt)
        check = result.scalars().first()
        if not check:
            raise Exception(f"Check with UUID {check_uuid} not found")

        logger.debug(f"Adding item to check {check_uuid}: {item_data}")

        # Извлекаем данные элемента
        item_id = item_data.get("id")

        if item_id is None:
            # Получаем максимальный item_id в данном чеке
            stmt = select(func.max(CheckItem.item_id)).where(CheckItem.check_uuid == check_uuid)
            result = await session.execute(stmt)
            max_item_id = result.scalar() or 0
            item_id = max_item_id + 1
        else:
            item_id = to_int(item_id)

        name = item_data.get("name")
        float_quantity = to_float(item_data.get("quantity"))
        if float_quantity < 1:
            float_quantity = 1
        if float_quantity.is_integer():
            quantity = int(float_quantity)
        else:
            name = f"{name} {float_quantity}"
            # Округляем в большую сторону
            quantity = math.ceil(float_quantity)
        sum_value = to_float(item_data.get("sum"))

        if item_id is None or quantity is None or sum_value is None or not name:
            raise ValueError(f"Invalid item data for check {check_uuid}: {item_data}")

        # Создаем новый элемент чека
        new_item = CheckItem(
            check_uuid=check_uuid,
            item_id=item_id,
            name=name,
            quantity=quantity,
            sum=sum_value
        )
        session.add(new_item)
        await session.flush()


        logger.debug(f"Item added to check {check_uuid}: {item_data}")

        # Возвращаем данные добавленного элемента
        item_response = {
            "id": new_item.item_id,
            "name": new_item.name,
            "quantity": new_item.quantity,
            "sum": new_item.sum
        }

        await session.commit()
        return item_response

    except Exception as e:
        await session.rollback()
        logger.error(f"Error adding item to check {check_uuid}: {e}")
        raise


# refac
async def edit_item_in_check(session: AsyncSession, check_uuid: str, item_data: dict) -> Dict[str, Any]:
    """Редактирование элемента в чеке
    Args:
        session: AsyncSession - сессия базы данных
        check_uuid: str - UUID чека
        item_data: dict - данные для редактирования

    Returns:
        dict: Обновленные данные check_data чека

    Raises:
        Exception: Если чек не найден или позиция не найдена
    """

    try:
        item_id = item_data.get("id")
        if item_id is None:
            raise ValueError("Item 'id' is required to edit a check item")

        # 1. Найти элемент по check_uuid и item_id
        stmt = select(CheckItem).where(
            CheckItem.check_uuid == check_uuid,
            CheckItem.item_id == item_id
        )
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()

        if not item:
            raise ValueError(f"Item with id={item_id} not found in check {check_uuid}")

        # 2. Обновить поля
        if "name" in item_data:
            item.name = item_data["name"]

        if "quantity" in item_data:
            quantity = to_float(item_data["quantity"])
            if quantity <= 0:
                raise ValueError("Quantity must be > 0")
            item.quantity = math.ceil(quantity) if not quantity.is_integer() else int(quantity)

        if "sum" in item_data:
            item.sum = to_float(item_data["sum"])
        elif "price" in item_data:
            item.sum = round(item.quantity * to_float(item_data["price"]), 2)

        await session.commit()

        # Пересчитываем все поля
        await recalculate_check_totals(session, check_uuid)

        await delete_item_from_user_selections(session, check_uuid, item.item_id)

        return {
            "item_id": item.item_id,
            "name": item.name,
            "quantity": item.quantity,
            "sum": item.sum
        }
    except Exception as e:
        await session.rollback()
        logger.error(f"Error adding item to check {check_uuid}: {e}")
        raise


# refac
async def update_item_quantity(session: AsyncSession, check_uuid: str, item_id: int, quantity: int):
    try:
        # 1. Найти нужный элемент по item_id и check_uuid
        stmt = select(CheckItem).where(
            CheckItem.check_uuid == check_uuid,
            CheckItem.item_id == item_id
        )
        result = await session.execute(stmt)
        item: CheckItem = result.scalar_one_or_none()

        if not item:
            logger.error(f"Элемент с item_id={item_id} не найден в чеке {check_uuid}")
            raise ValueError("Item not found")

        # 2. Обновить quantity
        if quantity <= 0:
            raise ValueError("Quantity must be > 0")

        item.quantity = quantity

        await session.commit()

        await delete_item_from_user_selections(session, check_uuid, item.item_id)

    except Exception as e:
        logger.error(f"Ошибка при обновлении количества элемента: {e}")
        raise e
