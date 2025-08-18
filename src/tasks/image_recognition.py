import json
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import config
from src.config.type_events import Events
from src.redis import redis_client
from src.repositories.check import add_check_to_database
from src.services.ai.api_anthropic import recognize_check_by_anthropic
from src.services.ai.recognized_json import static_recognized_json
from src.services.classifier.classifier_image import classifier_image
from src.utils.notifications import create_event_message
from src.utils.system import get_memory_usage
from src.websockets.manager import ws_manager

logger = logging.getLogger(config.app.service_name)


def calculate_price(json_data):
    """
    Вычисляет и записывает цену для каждого элемента в JSON.
    Перезаписывает price, если он уже есть.
    Считает quantity равным 1, если оно меньше 1.

    Args:
        json_data (dict): JSON данные.

    Returns:
        dict: JSON данные с добавленными ценами.
    """

    for item in json_data['items']:
        # Проверяем quantity и устанавливаем значение 1, если оно меньше 1
        quantity = item['quantity']
        if quantity < 1:
            quantity = 1

        # Вычисляем и записываем цену
        item['price'] = item['sum'] / quantity

    return json_data


async def recognize_image_task(
        check_uuid: str,
        user_id: int,
        file_location_directory: str,
        file_name: str,
        session: AsyncSession
):
    """ Обработка изображения: классификация и распознавание. """

    image_path = os.path.join(file_location_directory, file_name)
    logger.info(f"Начало обработки изображения {image_path} для пользователя  {user_id}, память: {get_memory_usage():.2f} MB")

    try:
        # Классификация изображения
        classification_result = await classifier_image(image_path)
        if classification_result == "Allowed Content":
            # Распознавание чека
            if config.app.is_production:
                recognized_json = await recognize_check_by_anthropic(file_location_directory, check_uuid)
            else:
                # recognized_json = await recognize_check_by_anthropic(file_location_directory)
                recognized_json = static_recognized_json

            if recognized_json:

                check_data = await add_check_to_database(session, check_uuid, user_id, recognized_json)

                redis_key = f"check_uuid:{check_uuid}"

                await redis_client.set(redis_key, json.dumps(check_data), expire=config.redis.expiration)

                msg = create_event_message(
                    message_type=Events.IMAGE_RECOGNITION_EVENT,
                    payload={"uuid": check_uuid}
                )

                await ws_manager.send_personal_message(
                    message=json.dumps(msg),
                    user_id=user_id
                )
            else:
                error_msg = {
                    "type": Events.IMAGE_RECOGNITION_EVENT_STATUS,
                    "status": "error",
                    "uuid": check_uuid,
                    "message": "Не удалось распознать изображение."
                }
                msg_to_ws = json.dumps(error_msg)
                await ws_manager.send_personal_message(msg_to_ws, user_id)

                logger.error(f"Не удалось распознать изображение для чека {check_uuid}")

        else:
            error_msg = {
                "type": Events.IMAGE_RECOGNITION_EVENT_STATUS,
                "status": "error",
                "uuid": check_uuid,
                "message": f"Сбой классификации изображения. Результат: {classification_result}"
            }
            msg_to_ws = json.dumps(error_msg)
            await ws_manager.send_personal_message(msg_to_ws, user_id)

            logger.error(
                f"Классификация изображения для check_uuid {check_uuid} завершилась с ошибкой: {classification_result}")
    except Exception as e:

        error_msg = {
            "type": Events.IMAGE_RECOGNITION_EVENT_STATUS,
            "status": "error",
            "uuid": check_uuid,
            "message": f"Ошибка при обработке изображения {check_uuid}: {e}"
        }
        msg_to_ws = json.dumps(error_msg)
        await ws_manager.send_personal_message(msg_to_ws, user_id)

        logger.error(f"Ошибка при обработке изображения {check_uuid}: {e}")
    logger.info(f"Конец обработки изображения {image_path} для пользователя  {user_id}, память: {get_memory_usage():.2f} MB")
