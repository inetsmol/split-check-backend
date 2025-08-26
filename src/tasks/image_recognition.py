# src/tasks/image_recognition.py
import logging
import os
from typing import Optional, Dict, Any, Union

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.models import RecognitionStatus
from src.repositories.check import add_check_to_database
from src.repositories.check_updates import set_recognition_status, update_check_from_json
from src.services.ai.api_anthropic import recognize_check_by_anthropic
from src.services.ai.recognized_json import static_recognized_json
from src.services.classifier.classifier_image import classifier_image
from src.utils.image_recognition import extract_json_from_response

logger = logging.getLogger(config.app.service_name)


# def calculate_price(json_data):
#     """
#     Вычисляет и записывает цену для каждого элемента в JSON.
#     Перезаписывает price, если он уже есть.
#     Считает quantity равным 1, если оно меньше 1.
#
#     Args:
#         json_data (dict): JSON данные.
#
#     Returns:
#         dict: JSON данные с добавленными ценами.
#     """
#
#     for item in json_data['items']:
#         # Проверяем quantity и устанавливаем значение 1, если оно меньше 1
#         quantity = item['quantity']
#         if quantity < 1:
#             quantity = 1
#
#         # Вычисляем и записываем цену
#         item['price'] = item['sum'] / quantity
#
#     return json_data


async def recognize_image_task(
    check_uuid: str,
    user_id: int,
    file_location_directory: str,
    file_name: str,
    session: AsyncSession,
) -> bool:
    """
    Асинхронная задача распознавания изображения чека.

    Логика:
    1) Создать пустую запись чека (скелет) со статусом распознавания NEW (по умолчанию в БД).
       - Если запись уже существует (повторный вызов), не падать — продолжаем.
    2) Перевести статус в RECOGNIZING.
    3) Запустить классификатор изображения (classifier_image).
       - Если вернулся недопустимый тип контента или ошибка классификатора — статус ERROR_HUGGING и выход.
    4) Запустить распознавание (Anthropic).
       - В production — реальный вызов API.
       - В dev — используем static_recognized_json (dict или str).
       - Если JSON получен — записать в БД (update_check_from_json) и проставить RECOGNIZED.
       - Если JSON не получен или возникла ошибка Anthropic — статус ERROR_ANTROPIC.
    5) Любая иная непредвиденная ошибка — общий статус ERROR.

    Параметры:
        check_uuid: UUID чека (PK).
        user_id: ID пользователя (будет автором чека и связан с ним).
        file_location_directory: Папка с файлом изображения.
        file_name: Имя файла изображения.
        session: Асинхронная сессия SQLAlchemy.

    Возвращает:
        True  — если чек распознан и статус проставлен RECOGNIZED.
        False — если был любой сбой (ERROR_HUGGING / ERROR_ANTROPIC / ERROR).

    Примечания по контрактам функций:
        - classifier_image(path) -> "Allowed Content" | <str-маркер-недопустимого-контента> | {"status": "error", "message": "..."}
        - recognize_check_by_anthropic(dir, check_uuid) -> Optional[Dict[str, Any]] | str (сырое сообщение, из которого надо извлечь JSON)
        - extract_json_from_response(text) -> Optional[Dict[str, Any]]
    """
    image_path = os.path.join(file_location_directory, file_name)
    logger.info("Начало обработки изображения %s для пользователя %s", image_path, user_id)

    try:
        # 1) Создаём пустую запись чека (идемпотентно: игнорируем конфликт PK).
        try:
            await add_check_to_database(session, check_uuid, user_id, check_data=None)
        except IntegrityError:
            # Если чек уже создан — откатываем текущую транзакцию и продолжаем.
            await session.rollback()
            logger.debug("Чек %s уже существует — продолжаю обработку.", check_uuid)

        # 2) Статус -> RECOGNIZING
        await set_recognition_status(session, check_uuid, RecognitionStatus.RECOGNIZING)

        # 3) Классификация изображения (HuggingFace/любой другой классификатор)
        classification_result: Union[str, Dict[str, Any]] = await classifier_image(image_path)

        # 3.1) Ошибка внутри классификатора: ожидаем dict {"status": "error", "message": "..."}
        if isinstance(classification_result, dict) and classification_result.get("status") == "error":
            err_msg = f"Классификация: {classification_result.get('message', 'unknown error')}"
            logger.error("%s (check_uuid=%s)", err_msg, check_uuid)
            await set_recognition_status(session, check_uuid, RecognitionStatus.ERROR_HUGGING, error_comment=err_msg)
            return False

        # 3.2) Контент запрещён (вернулась строка, но не "Allowed Content")
        if isinstance(classification_result, str) and classification_result != "Allowed Content":
            err_msg = f"Недопустимый тип контента от классификатора: {classification_result}"
            logger.error("%s (check_uuid=%s)", err_msg, check_uuid)
            await set_recognition_status(session, check_uuid, RecognitionStatus.ERROR_HUGGING, error_comment=err_msg)
            return False

        # 4) Распознавание (Anthropic)
        try:
            if config.app.is_production:
                # Продакшен: реальный запрос в провайдера
                response_payload: Optional[Union[str, Dict[str, Any]]] = await recognize_check_by_anthropic(
                    file_location_directory, check_uuid
                )
            else:
                # Dev-режим: статический ответ для быстрого цикла разработки
                response_payload = static_recognized_json
        except Exception as e:
            # Любая ошибка SDK/сети/ретраев на этапе Anthropic
            err_msg = f"Anthropic error: {e}"
            logger.error("%s (check_uuid=%s)", err_msg, check_uuid)
            await set_recognition_status(session, check_uuid, RecognitionStatus.ERROR_ANTROPIC, error_comment=err_msg)
            return False

        # 4.1) Нормализуем JSON из ответа
        response_json: Optional[Dict[str, Any]]
        if isinstance(response_payload, dict):
            response_json = response_payload
        elif isinstance(response_payload, str):
            response_json = extract_json_from_response(response_payload)
        else:
            response_json = None

        if not response_json:
            err_msg = "Не удалось извлечь JSON из ответа распознавания."
            logger.error("%s (check_uuid=%s)", err_msg, check_uuid)
            await set_recognition_status(session, check_uuid, RecognitionStatus.ERROR_ANTROPIC, error_comment=err_msg)
            return False

        # 4.2) Обновляем чек из JSON (перезапись полей + пересоздание позиций) и завершаем успехом
        await set_recognition_status(session, check_uuid, RecognitionStatus.RECOGNIZED)
        await update_check_from_json(session, check_uuid, response_json)
        return True

    except Exception as e:
        # 5) Непредвиденная ошибка верхнего уровня — общий ERROR
        err_msg = f"Ошибка при обработке изображения {check_uuid}: {e}"
        logger.exception(err_msg)
        try:
            await set_recognition_status(session, check_uuid, RecognitionStatus.ERROR, error_comment=err_msg)
        except Exception:
            logger.exception("Не удалось сохранить статус ERROR для чека %s", check_uuid)
        finally:
            return False
    finally:
        logger.info("Конец обработки изображения %s для пользователя %s", image_path, user_id)
