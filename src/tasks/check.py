import json
import logging
import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.config.type_events import Events
from src.repositories.check import get_check_data_from_database, get_all_checks_for_user, get_main_page_checks, \
    add_check_to_database, edit_check_name_to_database, edit_check_status_to_database, delete_association_by_check_uuid, \
    is_check_author, get_check_data
from src.repositories.user import get_users_by_check_uuid, get_user_by_id
from src.repositories.user_selection import delete_user_selection_by_user_id
from src.services.user import join_user_to_check
from src.utils.exchange import get_exchange_rate, round_half_up
from src.utils.notifications import create_event_message, create_event_status_message
from src.websockets.manager import ws_manager

logger = logging.getLogger(config.app.service_name)


# refac
async def send_check_data_task(user_id: int, check_uuid: str, session: AsyncSession):

    check_data = await get_check_data(session, user_id, check_uuid)

    msg = create_event_message(
        message_type=Events.BILL_DETAIL_EVENT,
        payload=check_data
    )
    logger.debug(f"Отправлена check_data {check_data}")

    await ws_manager.send_personal_message(
        message=json.dumps(msg),
        user_id=user_id
    )


# refac
async def send_all_checks_task(user_id: int, page: int, page_size: int, session: AsyncSession, check_name: Optional[str] = None, check_status: Optional[str] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
    checks_data = await get_all_checks_for_user(session, user_id=user_id, page=page, page_size=page_size,
                                                check_name=check_name, check_status=check_status, start_date=start_date,
                                                end_date=end_date)
    msg = create_event_message(
        message_type=Events.ALL_BILL_EVENT,
        payload={
            "checks": checks_data["items"],
            "pagination": {
                "total": checks_data["total"],
                "page": checks_data["page"],
                "pageSize": checks_data["page_size"],
                "totalPages": checks_data["total_pages"]
            }
        }
    )
    logger.debug(f"Страница все чеки: {msg}")

    await ws_manager.send_personal_message(
        message=json.dumps(msg),
        user_id=user_id
    )


# refac
async def send_main_page_checks_task(user_id: int, session: AsyncSession):

    checks_data = await get_main_page_checks(session, user_id)

    msg = create_event_message(
        message_type=Events.MAIN_PAGE_EVENT,
        payload={
            "checks": checks_data["items"],
            "total_open": checks_data["total_open"],
            "total_closed": checks_data["total_closed"],
        }
    )
    logger.debug(f"Главная страница: {msg}")
    await ws_manager.send_personal_message(
        message=json.dumps(msg),
        user_id=user_id
    )


# refac
async def add_empty_check_task(user_id: int, session: AsyncSession):
    check_uuid = str(uuid.uuid4())

    await add_check_to_database(session, check_uuid, user_id)

    msg = create_event_message(
        message_type=Events.CHECK_ADD_EVENT,
        payload={"uuid": check_uuid}
    )
    await ws_manager.send_personal_message(
        message=json.dumps(msg),
        user_id=user_id
    )


# refac
async def edit_check_name_task(user_id: int, check_uuid: str, check_name: str, session: AsyncSession):

    new_name_status = await edit_check_name_to_database(session, user_id, check_uuid, check_name)
    users = await get_users_by_check_uuid(session, check_uuid)

    if new_name_status == "Check name updated successfully.":
        msg_for_author = create_event_status_message(
            message_type=Events.CHECK_NAME_EVENT_STATUS,
            status="success"
        )

        msg_for_all = create_event_message(
            message_type=Events.CHECK_NAME_EVENT,
            payload={"check_uuid": check_uuid, "check_name": check_name},
        )
        all_user_ids = {user.id for user in users}
        logger.debug(f"Все пользователи для отправки: {all_user_ids}")

        # Отправка сообщений всем пользователям
        for uid in all_user_ids:
            msg = msg_for_author if uid == user_id else msg_for_all
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=uid
                )
            except Exception as e:
                logger.warning(f"Ошибка отправки сообщения пользователю {uid}: {str(e)}")


# refac
async def edit_check_status_task(user_id: int, check_uuid: str, check_status: str, session: AsyncSession):

    status = await edit_check_status_to_database(session, user_id, check_uuid, check_status)
    users = await get_users_by_check_uuid(session, check_uuid)

    if status == "Check status updated successfully.":
        msg_for_author = create_event_status_message(
            message_type=Events.CHECK_STATUS_EVENT_STATUS,
            status="success"
        )

        msg_for_all = create_event_message(
            message_type=Events.CHECK_STATUS_EVENT,
            payload={"check_uuid": check_uuid, "check_status": check_status},
        )

        all_user_ids = {user.id for user in users}
        logger.debug(f"Все пользователи для отправки: {all_user_ids}")

        # Отправка сообщений всем пользователям
        for uid in all_user_ids:
            msg = msg_for_author if uid == user_id else msg_for_all
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=uid
                )
            except Exception as e:
                logger.warning(f"Ошибка отправки сообщения пользователю {uid}: {str(e)}")


# refac
async def join_check_task(user_id: int, check_uuid: str, session: AsyncSession):
    try:
        await join_user_to_check(user_id, check_uuid)
        joined_user = await get_user_by_id(session, user_id)
        users = await get_users_by_check_uuid(session, check_uuid)

        msg_for_author = create_event_status_message(
            message_type=Events.JOIN_BILL_EVENT_STATUS,
            status="success"
        )

        msg_for_all = create_event_message(
            message_type=Events.USER_JOIN_EVENT,
            payload={"uuid": check_uuid, "user": {"user_id": joined_user.id,
                     "nickname": joined_user.profile.nickname,
                     "avatar_url": joined_user.profile.avatar_url}
                     },
        )

        all_user_ids = {user.id for user in users}
        logger.debug(f"Все пользователи для отправки: {all_user_ids}")

        # Отправка сообщений всем пользователям
        for uid in all_user_ids:
            msg = msg_for_author if uid == user_id else msg_for_all
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=uid
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения пользователю {uid}: {str(e)}")

    except Exception as e:
        logger.error(f"Error in {Events.USER_JOIN_EVENT}: {str(e)}", extra={"current_user_id": user_id})

        error_message = create_event_status_message(
            message_type=Events.USER_JOIN_EVENT,
            status="error",
            message=str(e)
        )
        await ws_manager.send_personal_message(
            message=json.dumps(error_message),
            user_id=user_id
        )


# refac
async def delete_check_task(user_id: int, check_uuid: str, session: AsyncSession):
    try:
        users = await get_users_by_check_uuid(session, check_uuid)
        await delete_association_by_check_uuid(session, check_uuid, user_id)

        msg_for_author = create_event_status_message(
            message_type=Events.CHECK_DELETE_EVENT_STATUS,
            status="success"
        )

        msg_for_all = create_event_message(
            message_type=Events.CHECK_DELETE_EVENT,
            payload={"check_uuid": check_uuid},
        )

        all_user_ids = {user.id for user in users}
        # Отправка сообщений всем пользователям
        for uid in all_user_ids:
            msg = msg_for_author if uid == user_id else msg_for_all
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=uid
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения пользователю {uid}: {str(e)}", extra={"current_user_id": user_id})
    except Exception as e:
        logger.error(f"Error in {Events.CHECK_DELETE_EVENT}: {str(e)}", extra={"current_user_id": user_id})

        error_message = create_event_status_message(
            message_type=Events.CHECK_DELETE_EVENT,
            status="error",
            message=str(e)
        )
        await ws_manager.send_personal_message(
            message=json.dumps(error_message),
            user_id=user_id
        )


# refac
async def user_delete_from_check_task(check_uuid: str, user_id_for_delete: int, current_user_id: int, session: AsyncSession):
    """
    Удаляет ассоциацию пользователя с чеком. Только автор чека может выполнить это действие.

    Args:
        check_uuid (str): UUID чека
        user_id_for_delete (int): ID пользователя, которого нужно удалить из чека
        current_user_id (int): ID текущего пользователя (автора)
        session:

    Returns:
        bool: True если удаление успешно, False если текущий пользователь не автор

    Raises:
        SQLAlchemyError: При ошибках работы с базой данных
    """
    try:
        # Проверяем права автора
        if not await is_check_author(session, current_user_id, check_uuid):
            logger.warning(
                f"User {current_user_id} attempted to delete user {user_id_for_delete} "
                f"from check {check_uuid} without author rights"
            )
        # Получаем участников и пользователей, связанных с чеком до удаления. что-бы отправить удаленному тоже
        users = await get_users_by_check_uuid(session, check_uuid)
        # Удаляем ассоциацию пользователя с чеком и его селекшены
        await delete_association_by_check_uuid(session, check_uuid, user_id_for_delete)
        await delete_user_selection_by_user_id(session, user_id_for_delete, check_uuid)

        msg_for_all = create_event_message(
            message_type=Events.USER_DELETE_FROM_CHECK_EVENT,
            payload={"uuid": check_uuid, "user_id_for_delete": user_id_for_delete}
        )

        msg_for_author = create_event_status_message(
            message_type=Events.USER_DELETE_FROM_CHECK_EVENT_STATUS,
            status="success"
        )

        all_user_ids = {user.id for user in users}
        logger.debug(f"Все пользователи для отправки: {all_user_ids}")

        # Отправка сообщений всем пользователям
        for uid in all_user_ids:
            msg = msg_for_author if uid == current_user_id else msg_for_all
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=uid
                )
            except Exception as e:
                logger.warning(f"Ошибка отправки сообщения пользователю {uid}: {str(e)}",
                               extra={"current_user_id": current_user_id})

        logger.debug(
            f"User {user_id_for_delete} was removed from check {check_uuid} "
            f"by author {current_user_id}", extra={"current_user_id": current_user_id}
        )

    except Exception as e:
        logger.error(f"Error in {Events.USER_DELETE_FROM_CHECK_EVENT}: {str(e)}", extra={"current_user_id": current_user_id})

        error_message = create_event_status_message(
            message_type=Events.USER_DELETE_FROM_CHECK_EVENT,
            status="error",
            message=str(e)
        )
        await ws_manager.send_personal_message(
            message=json.dumps(error_message),
            user_id=current_user_id
        )


async def convert_check_currency_task(check_uuid: str, target_currency: str, user_id: int, session: AsyncSession) -> None:
    """
    Конвертирует данные чека из его валюты в целевую валюту.

    Args:
        check_uuid: str - UUID чека
        target_currency: str - Целевая валюта (например, "USD", "EUR")
        user_id: int - ИД пользователя
        session: AsyncSession
    Raises:
        Exception: Если чек не найден или произошла ошибка при конвертации
    """
    try:
        # Получаем данные чека из базы
        check_data = await get_check_data_from_database(session, check_uuid)

        # Валюта чека
        check_currency = check_data["currency"]

        # Получаем курс обмена
        exchange_rate = await get_exchange_rate(check_currency, target_currency)
        if exchange_rate is None:
            raise Exception(f"Не удалось получить курс обмена между {check_currency} и {target_currency}")

        # Создаем копию данных чека для изменений
        converted_check_data = check_data.copy()

        # Конвертируем основные суммы
        converted_check_data["subtotal"] = round_half_up(converted_check_data["subtotal"] / exchange_rate)
        converted_check_data["total"] = round_half_up(converted_check_data["total"] / exchange_rate)

        # Конвертируем дополнительные суммы (service_charge, vat, discount), если они есть
        if converted_check_data["service_charge"]:
            converted_check_data["service_charge"]["amount"] = round_half_up(
                converted_check_data["service_charge"]["amount"] / exchange_rate
                if converted_check_data["service_charge"]["amount"] is not None else None
            )

        if converted_check_data["vat"]:
            converted_check_data["vat"]["amount"] = round_half_up(
                converted_check_data["vat"]["amount"] / exchange_rate
                if converted_check_data["vat"]["amount"] is not None else None
            )

        if converted_check_data["discount"]:
            converted_check_data["discount"]["amount"] = round_half_up(
                converted_check_data["discount"]["amount"] / exchange_rate
                if converted_check_data["discount"]["amount"] is not None else None
            )

        # Конвертируем суммы для каждой позиции в чеке
        for item in converted_check_data["items"]:

            item["sum"] = round_half_up(item["sum"] / exchange_rate)
            item["price"] = round_half_up(item["sum"] / item["quantity"])

        # Обновляем валюту чека
        converted_check_data["currency"] = target_currency

        logger.debug(f"converted_check_data :{converted_check_data}")

        msg = create_event_message(Events.CHECK_CONVERT_CURRENCY_EVENT, converted_check_data)

        await ws_manager.send_personal_message(
            message=json.dumps(msg),
            user_id=user_id
        )

    except Exception as e:
        logger.error(f"Error while converting check currency: {e}")
        raise