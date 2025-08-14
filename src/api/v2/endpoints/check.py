import base64
import json
import logging
import os
import uuid
from datetime import date
from typing import Optional
from uuid import UUID

import aiofiles
from fastapi import APIRouter, UploadFile, File, Depends, Request, Query, HTTPException, Body, Path
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from src.api.deps import get_current_user
from src.config import config
from src.config.type_events import Events
from src.models import User, StatusEnum
from src.redis import redis_client
from src.redis.queue_processor import get_queue_processor
from src.repositories.check import get_all_checks_for_user, get_check_data, add_check_to_database, \
    edit_check_name_to_database, edit_check_status_to_database, delete_association_by_check_uuid, is_check_author
from src.repositories.user import get_users_by_check_uuid, get_user_by_id
from src.repositories.user_selection import add_or_update_user_selection, delete_user_selection_by_user_id
from src.schemas import CheckSelectionRequest
from src.services.user import join_user_to_check
from src.utils.db import get_session
from src.utils.notifications import create_event_message
from src.websockets.manager import ws_manager

queue_processor = get_queue_processor()


logger = logging.getLogger(config.app.service_name)

router = APIRouter()

# Имя очереди для заданий обработки изображений
IMAGE_PROCESSING_QUEUE = "image_processing_tasks"


@router.get("/", summary="Получить все чеки. Синхронный ответ")
async def get_all_check(
                        check_name: Optional[str] = None,
                        check_status: Optional[StatusEnum] = None,
                        start_date: Optional[date] = Query(None, description="Start date in YYYY-MM-DD format"),
                        end_date: Optional[date] = Query(None, description="End date in YYYY-MM-DD format"),
                        page: int = Query(default=1, ge=1),
                        page_size: int = Query(default=20, ge=1, le=100),
                        user: User = Depends(get_current_user),
                        session: AsyncSession = Depends(get_session)):
    try:
        checks_data = await get_all_checks_for_user(session, user_id=user.id, page=page, page_size=page_size,
                                                    check_name=check_name, check_status=check_status,
                                                    start_date=start_date, end_date=end_date)

        payload = {
            "checks": checks_data["items"],
            "total_open": checks_data.get("total_open", 0),
            "total_closed": checks_data.get("total_closed", 0),
            "pagination": {
                "total": checks_data["total"],
                "page": checks_data["page"],
                "pageSize": checks_data["page_size"],
                "totalPages": checks_data["total_pages"]
            }
        }
        logger.debug(f"Отправлены данные всех чеков для пользователя ИД {user.id}: {payload}")
        return payload
    except Exception as e:
        logger.error(f"Ошибка при отправке всех чеков: {e}")
        raise HTTPException(
            status_code=500,
            detail="Внутренняя ошибка сервера"
        )


@router.get("/{uuid}", summary="Получить чек по UUID. Синхронный ответ", response_model=dict)
async def get_check(
                    uuid: UUID = Path(..., description="UUID чека"),
                    user: User = Depends(get_current_user),
                    session: AsyncSession = Depends(get_session)
                    ):
    try:
        check_data = await get_check_data(session, user.id, str(uuid))

        logger.debug(f"Отправлены данные чека для пользователя ИД {user.id}: {check_data}")
        return check_data

    except HTTPException as e:
        # Пробрасываем заранее созданные HTTP-исключения (например, 404)
        raise e
    except SQLAlchemyError as db_error:
        logger.error(f"Ошибка базы данных: {db_error}")
        raise HTTPException(status_code=500, detail="Ошибка базы данных")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при отправке чека: {e}")
        raise HTTPException(
            status_code=500,
            detail="Внутренняя ошибка сервера"
        )


@router.post("/add", summary="Добавление пустого чека. Синхронный ответ", response_model=dict, status_code=200)
async def add_empty_check(
        request: Request,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Создает пустой чек и сохраняет его в базу данных.

    - **user**: Текущий авторизованный пользователь (получен через Depends).
    - **session**: Асинхронная сессия SQLAlchemy.

    Returns:
        dict: UUID созданного чека.
    """
    check_uuid = str(uuid.uuid4())

    try:
        await add_check_to_database(session, check_uuid, user.id)
        logger.debug(f"Пользователь {user.id} добавил чек {check_uuid}")
    except Exception as e:
        logger.error(f"Ошибка при добавлении чека: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось создать чек"
        )

    return {"uuid": check_uuid}


@router.post("/upload",
             summary="Загрузка изображения. Синхронный ответ",
             description="""
                    Принимает изображение чека, сохраняет его и инициирует фоновую обработку.
                    
                    **Основной поток обработки**:
                    - Изображение сохраняется на диск
                    - Кодируется в base64 и отправляется в очередь Redis (`image_processing_tasks`)
                    - Ожидается результат от `image_processor` (до 30 сек)
                    - Результат сохраняется в базу и Redis, пользователь получает уведомление через WebSocket
                    
                    **Ответ**:
                    - 200 OK: UUID задачи
                    - 504 Timeout: если результат не получен вовремя
                    - 500 Internal Error: при ошибке обработки
                """)
async def upload_image(
    request: Request,
    user: User = Depends(get_current_user),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session)
):
    check_uuid = str(uuid.uuid4())
    directory = os.path.join(config.app.upload_directory, check_uuid)
    os.makedirs(directory, exist_ok=True)

    file_path = os.path.join(directory, file.filename)

    try:
        async with aiofiles.open(file_path, "wb") as out_file:
            content = await file.read()
            await out_file.write(content)

        encoded_image = base64.b64encode(content).decode("utf-8")
        task_data = {
            "id": check_uuid,
            "type": "image_process",
            "image": encoded_image,
        }

        await queue_processor.push_task(task_data=task_data, queue_name=IMAGE_PROCESSING_QUEUE)
        result = await redis_client.wait_for_result(check_uuid, timeout=30)

        if not result:
            raise HTTPException(status_code=504, detail="Timeout: обработка заняла слишком много времени")
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("result"))

        check_data = result.get("result")
        check_data = await add_check_to_database(session, check_uuid, user.id, check_data)

        await redis_client.set(f"check_uuid:{check_uuid}", json.dumps(check_data), expire=config.redis.expiration)

        msg = create_event_message(
            message_type=Events.IMAGE_RECOGNITION_EVENT,
            payload={"uuid": check_uuid}
        )
        await ws_manager.send_personal_message(
            message=json.dumps(msg),
            user_id=user.id
        )

        return JSONResponse(status_code=status.HTTP_200_OK, content=check_data)

    except Exception as e:
        logger.error(f"Ошибка при загрузке изображения: {str(e)}")
        raise HTTPException(status_code=500, detail="Ошибка загрузки изображения")


@router.post("/{uuid}/select", summary="Выбор пользователя. Синхронный ответ")
async def user_selection(request: Request,
                         selection: CheckSelectionRequest,
                         uuid: UUID = Path(..., description="UUID чека"),
                         user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session)
                         ):
    check_uuid = str(uuid)
    selection_data = selection.model_dump()
    try:
        # Обновляем или добавляем выбор пользователя
        await add_or_update_user_selection(session, user_id=user.id, check_uuid=check_uuid,
                                           selection_data=selection_data)

        # Получаем участников и пользователей, связанных с чеком
        users = await get_users_by_check_uuid(session, check_uuid)

        selections = {
            "user_id": user.id,
            "selected_items": selection_data['selected_items']
        }

        logger.debug(f"selection_data: {selections}")

        all_user_ids = {user.id for user in users}

        # Формируем сообщения
        msg_for_all = create_event_message(
            message_type=Events.CHECK_SELECTION_EVENT,
            payload={"uuid": check_uuid, "participants": [selections]},
        )

        # Отправка сообщений всем пользователям
        for uid in all_user_ids:
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg_for_all),
                    user_id=uid)
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения пользователю {uid}: {str(e)}")

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"uuid": check_uuid, "participants": [selections]}
        )

    except Exception as e:
        logger.error(f"Ошибка при выполнении задачи выбора пользователя: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Внутренняя ошибка сервера"
        )


@router.put("/{uuid}/name",
            summary="Изменение названия чека. Синхронный ответ",
            status_code=200,
            response_model=dict)
async def edit_check_name(
        request: Request,
        uuid: UUID = Path(..., description="UUID чека"),
        check_name: str = Body(..., embed=True, min_length=1, max_length=100, description="Новое имя чека"),
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Обновляет название чека и уведомляет всех участников.

    - **uuid**: Идентификатор чека
    - **check_name**: Новое название
    """
    check_uuid = str(uuid)

    try:
        success = await edit_check_name_to_database(session, user.id, check_uuid, check_name)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Чек не найден или не удалось обновить название."
            )

        users = await get_users_by_check_uuid(session, check_uuid)

        msg = create_event_message(
            message_type=Events.CHECK_NAME_EVENT,
            payload={"check_uuid": check_uuid, "check_name": check_name}
        )
        all_user_ids = {u.id for u in users}

        for uid in all_user_ids:
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=uid
                )
            except Exception as e:
                logger.warning(f"Ошибка отправки WebSocket сообщения пользователю {uid}: {e}")

        logger.info(f"Пользователь {user.id} обновил название чека {check_uuid} на '{check_name}'")
        return {"check_uuid": check_uuid, "check_name": check_name}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Ошибка при изменении названия чека: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка сервера при изменении названия чека."
        )


@router.put("/{uuid}/status",
                summary="Изменение статуса чека. Синхронный ответ",
                description="Эндпоинт для изменения статуса чека. Допустимые значения: 'OPEN', 'CLOSE'.",
                response_model=dict,
                status_code=status.HTTP_200_OK)
async def edit_check_status(
        request: Request,
        uuid: UUID = Path(..., description="UUID чека"),
        check_status: StatusEnum = Body(..., embed=True, description="Новый статус чека: 'OPEN' или 'CLOSE'"),
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session)
):
    """
    Обновляет статус чека и уведомляет участников через WebSocket.
    """
    check_uuid = str(uuid)
    check_status = check_status.value

    try:
        success = await edit_check_status_to_database(session, user.id, check_uuid, check_status)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Чек не найден или вы не авторизованы для изменения."
            )

        users = await get_users_by_check_uuid(session, check_uuid)
        all_user_ids = {u.id for u in users}

        msg = create_event_message(
            message_type=Events.CHECK_STATUS_EVENT,
            payload={"check_uuid": check_uuid, "check_status": check_status}
        )

        logger.debug(f"Подготовка отправки статуса {check_status} для чека {check_uuid} пользователям: {all_user_ids}")

        for uid in all_user_ids:
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=uid
                )
            except Exception as e:
                logger.warning(f"Ошибка WebSocket отправки пользователю {uid}: {e}")

        logger.info(f"Пользователь {user.id} установил статус '{check_status}' для чека {check_uuid}")
        return {"check_uuid": check_uuid, "check_status": check_status}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Серверная ошибка при обновлении статуса чека: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка сервера при обновлении статуса чека."
        )


@router.post(
    "/{uuid}/join",
    summary="Присоединение пользователя к чеку. Синхронный ответ",
    response_description="Информация о присоединившемся пользователе",
    response_model=dict,
    status_code=status.HTTP_200_OK
)
async def join_check(
    request: Request,
    uuid: UUID = Path(..., description="UUID чека, к которому присоединяется пользователь"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Присоединяет пользователя к чеку. Уведомляет всех участников через WebSocket.
    """
    check_uuid = str(uuid)

    try:
        await join_user_to_check(user.id, check_uuid)

        joined_user = await get_user_by_id(session, user.id)
        users = await get_users_by_check_uuid(session, check_uuid)

        event_payload = {"uuid": check_uuid,
                         "user": {"user_id": joined_user.id,
                                 "nickname": joined_user.profile.nickname,
                                 "avatar_url": joined_user.profile.avatar_url}
                                 }

        msg_for_all = create_event_message(
            message_type=Events.USER_JOIN_EVENT,
            payload={"uuid": check_uuid,
                     "user": {"user_id": joined_user.id,
                             "nickname": joined_user.profile.nickname,
                             "avatar_url": joined_user.profile.avatar_url}
                             },
        )

        all_user_ids = {u.id for u in users}
        logger.debug(f"Пользователь {user.id} присоединился к чеку {check_uuid}. Уведомляем: {all_user_ids}")

        for uid in all_user_ids:
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg_for_all),
                    user_id=uid
                )
            except Exception as e:
                logger.warning(f"WebSocket ошибка для пользователя {uid}: {e}")

        logger.info(f"Пользователь {user.id} успешно присоединился к чеку {check_uuid}")
        return event_payload

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Ошибка в {Events.USER_JOIN_EVENT} при присоединении пользователя {user.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Серверная ошибка при присоединении к чеку."
        )


@router.delete(
    "/{uuid}",
    summary="Удаление чека. Синхронный ответ",
    response_description="UUID удалённого чека",
    status_code=status.HTTP_200_OK,
    response_model=dict
)
async def delete_check(
    request: Request,
    uuid: UUID = Path(..., description="UUID чека для удаления"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Удаляет чек и уведомляет участников через WebSocket.
    """
    check_uuid = str(uuid)

    if not is_check_author(session, user.id, check_uuid):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Вы не можете удалить чек, если не являетесь его автором."
        )

    try:
        users = await get_users_by_check_uuid(session, check_uuid)
        if not users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Не найдено пользователей для чека с UUID {check_uuid}."
            )
        msg_for_all = create_event_message(
            message_type=Events.CHECK_DELETE_EVENT,
            payload={"check_uuid": check_uuid},
        )
        for u in users:
            await delete_user_selection_by_user_id(session, check_uuid, u.id)
            await delete_association_by_check_uuid(session, check_uuid, u.id)
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg_for_all),
                    user_id=u.id
                )
            except Exception as e:
                logger.warning(f"WebSocket ошибка при отправке пользователю {u.id}: {e}")

        logger.debug(f"Чек {check_uuid} удалён пользователем {user.id}.")

        return {"check_uuid": check_uuid}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Ошибка при удалении чека {check_uuid}", extra={"user_id": user.id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Серверная ошибка при удалении чека."
        )


@router.delete(
    "/{uuid}/users/{user_id_for_delete}",
    summary="Удаление пользователя из чека. Синхронный ответ",
    description="Удаляет указанного пользователя из чека (только автор может выполнить).",
    response_description="UUID чека и ID удалённого пользователя",
    status_code=status.HTTP_200_OK,
    response_model=dict
)
async def user_delete_from_check(
    request: Request,
    uuid: UUID = Path(..., description="UUID чека"),
    user_id_for_delete: int = Path(..., title="ID пользователя для удаления из чека"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Удаляет пользователя из чека. Только автор чека может это сделать.
    Отправляет уведомления через WebSocket всем участникам.

    - **uuid**: UUID чека.
    - **user_id_for_delete**: ID пользователя, которого нужно удалить.
    - **user**: Аутентифицированный пользователь (предположительно автор чека).
    """
    check_uuid = str(uuid)

    try:
        # Проверка авторских прав
        if not await is_check_author(session, user.id, check_uuid):
            logger.warning(
                f"User {user.id} попытался удалить user {user_id_for_delete} из чека {check_uuid} без прав автора.",
                extra={"initiator": user.id, "target_user": user_id_for_delete, "check_uuid": check_uuid}
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Только автор чека может удалять пользователей."
            )

        # Сохраняем участников до удаления
        users = await get_users_by_check_uuid(session, check_uuid)

        # Удаление
        await delete_user_selection_by_user_id(session, check_uuid, user_id_for_delete)
        await delete_association_by_check_uuid(session, check_uuid, user_id_for_delete)

        msg_for_all = create_event_message(
            message_type=Events.USER_DELETE_FROM_CHECK_EVENT,
            payload={"uuid": check_uuid, "user_id_for_delete": user_id_for_delete}
        )

        all_user_ids = {u.id for u in users}

        for uid in all_user_ids:
            try:
                await ws_manager.send_personal_message(
                    message=json.dumps(msg_for_all),
                    user_id=uid
                )
            except Exception as e:
                logger.warning(
                    f"Ошибка WebSocket отправки участнику {uid}: {str(e)}",
                    extra={"check_uuid": check_uuid, "user_id_for_delete": user_id_for_delete}
                )

        logger.info(
            f"Пользователь {user_id_for_delete} удалён из чека {check_uuid} автором {user.id}.",
            extra={"check_uuid": check_uuid, "initiator": user.id}
        )

        return {"uuid": check_uuid, "user_id_for_delete": user_id_for_delete}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            f"Непредвиденная ошибка при удалении пользователя {user_id_for_delete} из чека {check_uuid}.",
            extra={"initiator": user.id, "check_uuid": check_uuid}
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Серверная ошибка при удалении пользователя из чека."
        )


@router.get("/{uuid}/images", summary="Получить список ссылок на изображения. Синхронный ответ")
async def get_images(uuid: UUID = Path(..., description="UUID чека"), user: User = Depends(get_current_user)):
    """
    Возвращает список URL-ов на изображения из папки UUID.
    """
    folder_path = os.path.join(config.app.upload_directory, str(uuid))
    try:
        image_files = [f for f in os.scandir(folder_path) if f.is_file() and f.name.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.gif'))]
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Папка с изображениями не найдена")

    if not image_files:
        raise HTTPException(status_code=404, detail="Изображения не найдены")

    base_url = f"{config.app.base_url}/images/{uuid}/"

    return {
        "uuid": str(uuid),
        "images": [base_url + f.name for f in image_files]
    }
