# src/repositories/check_updates.py
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.models import Check, CheckItem, RecognitionStatus
from src.repositories.check import get_check_data_from_database
from src.repositories.item import add_item_to_check
from src.utils.check import to_float

logger = logging.getLogger(config.app.service_name)


async def set_recognition_status(
    session: AsyncSession,
    check_uuid: str,
    new_status: RecognitionStatus,
    error_comment: Optional[str] = None,
) -> None:
    """
    Атомарно меняет статус распознавания (и при необходимости error_comment).

    Args:
        session: асинхронная сессия БД
        check_uuid: идентификатор чека
        new_status: новый статус распознавания
        error_comment: текст ошибки (перезапишет существующий)
    """
    status_value = int(new_status)  # безопасно для IntEnum и int
    values = {"recognition_status": status_value, "updated_at": datetime.now()}
    if error_comment is not None:
        values["error_comment"] = error_comment

    await session.execute(
        update(Check).where(Check.uuid == check_uuid).values(**values)
    )
    await session.commit()


async def update_check_from_json(
    session: AsyncSession,
    check_uuid: str,
    check_data: Dict[str, Any],
):
    """
    Обновляет существующий чек данными распознавания:
    - Перезаписывает основные поля;
    - Полностью пересоздаёт позиции (items) для простоты и детерминизма;
    - Выполняет валидацию сумм и пишет предупреждения в error_comment.

    Возвращает словарь чека (как get_check_data_from_database).
    """
    # Загружаем чек; предполагается, что запись уже создана ранее
    check: Check | None = await session.get(Check, check_uuid)
    if check is None:
        raise ValueError(f"Check {check_uuid} not found for update")

    # --- Заполнение основных полей из JSON ---
    currency_raw = check_data.get("currency")
    currency = currency_raw if currency_raw and len(str(currency_raw)) <= 3 else None

    check.check_data = check_data
    check.name = check_data.get("restaurant") or check.name or "check"

    check.restaurant = check_data.get("restaurant") or None
    check.address = check_data.get("address") or None
    check.phone = check_data.get("phone") or None
    check.table_number = check_data.get("table_number") or None
    check.order_number = check_data.get("order_number") or None
    check.date = check_data.get("date") or check.date
    check.time = check_data.get("time") or check.time
    check.waiter = check_data.get("waiter") or None

    check.subtotal = to_float(check_data.get("subtotal"), 0.0)
    check.total = to_float(check_data.get("total"), 0.0)
    check.currency = currency

    # Сервисный сбор
    service_charge = check_data.get("service_charge")
    check.service_charge_name = (service_charge or {}).get("name")
    check.service_charge_percentage = to_float((service_charge or {}).get("percentage"))
    check.service_charge_amount = to_float((service_charge or {}).get("amount"))

    # НДС
    vat = check_data.get("vat")
    check.vat_rate = to_float((vat or {}).get("rate"))
    check.vat_amount = to_float((vat or {}).get("amount"))

    # Скидка
    discount = check_data.get("discount")
    check.discount_percentage = to_float((discount or {}).get("percentage"))
    check.discount_amount = to_float((discount or {}).get("amount"))

    # --- Пересоздание позиций ---
    # Удаляем все старые позиции
    await session.execute(
        delete(CheckItem).where(CheckItem.check_uuid == check_uuid)
    )
    await session.flush()

    items_added: List[dict] = []
    for item in check_data.get("items", []):
        item_response = await add_item_to_check(session, check_uuid, item)
        items_added.append(item_response)

    # --- Валидация сумм ---
    error_comments: list[str] = []

    items_total = sum(to_float(i.get("sum"), 0.0) for i in items_added)
    subtotal = to_float(check_data.get("subtotal"), 0.0)
    if abs(items_total - subtotal) > 0.01:
        error_comments.append(
            f"Сумма всех позиций ({items_total}) не совпадает с subtotal ({subtotal})"
        )

    service_charge_amount = to_float((service_charge or {}).get("amount"), 0.0)
    vat_amount = to_float((vat or {}).get("amount"), 0.0)
    discount_amount = to_float((discount or {}).get("amount"), 0.0)
    expected_total = subtotal + service_charge_amount + vat_amount - discount_amount
    total = to_float(check_data.get("total"), 0.0)
    if abs(expected_total - total) > 0.01:
        error_comments.append(
            f"Итого ({total}) не совпадает с рассчитанным итогом ({expected_total}) "
            f"(промежуточный итог: {subtotal}, плата за обслуживание: {service_charge_amount}, "
            f"НДС: {vat_amount}, скидка: {discount_amount})"
        )

    # Если нашли проблемы — сохраним в error_comment (перезаписываем)
    check.error_comment = "; ".join(error_comments) if error_comments else None

    await session.commit()
    #
    # # Возвращаем агрегированные данные (учтёт кеш/редис, если есть)
    # check_dict = await get_check_data_from_database(session, check_uuid)
    # return check_dict
