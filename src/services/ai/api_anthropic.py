import logging
import time
from typing import Optional, Dict, Any

import httpx
from anthropic import Anthropic

from src.config import config
from src.services.ai.prompt import prompt
from src.utils.image_recognition import is_valid_json_response, extract_json_from_response
from .message import message_for_anthropic

logger = logging.getLogger(config.app.service_name)

if config.app.is_production:
    client = Anthropic(api_key=config.ai.anthropic_api_key.get_secret_value())
else:
    # Создание HTTP клиента с настроенным прокси
    http_client = httpx.Client(proxy="http://127.0.0.1:12334")

    client = Anthropic(http_client=http_client, api_key=config.ai.anthropic_api_key.get_secret_value())


async def send_request_to_anthropic(message: list, check_uuid, max_retries: int = 2) -> Optional[str]:
    """
    Отправляет запрос к Anthropic API с повторными попытками.

    Args:
        message: Подготовленное сообщение для API
        check_uuid
        max_retries: Максимальное количество попыток (по умолчанию 2)

    Returns:
        Текст ответа или None в случае ошибки
    """
    for attempt in range(max_retries):
        try:
            # Start timer
            start_time = time.time()

            response = client.messages.create(
                model=config.ai.anthropic_model_name,
                max_tokens=2048,
                messages=message
            )

            # End timer
            end_time = time.time()
            elapsed_time = end_time - start_time

            response_text = response.content[0].text
            logger.info(f"Попытка {attempt + 1} для чека {check_uuid}: Время ответа: {elapsed_time:.2f} секунд. Получен ответ от API: {response_text}")

            # Проверяем, содержит ли ответ JSON
            if is_valid_json_response(response_text):
                return response_text
            else:
                logger.warning(f"Попытка {attempt + 1} для чека {check_uuid}: Ответ не содержит валидный JSON")
                if attempt < max_retries - 1:
                    logger.info(f"Повторная отправка запроса для чека {check_uuid} (попытка {attempt + 2})")
                    continue
                else:
                    logger.error(f"Исчерпаны все попытки получения валидного JSON для чека {check_uuid}. response_text: {response_text}")
                    return None

        except Exception as e:
            logger.error(f"Попытка {attempt + 1} для чека {check_uuid}: Ошибка при отправке запроса: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Повторная отправка запроса (попытка {attempt + 2}) для чека {check_uuid}")
                continue
            else:
                logger.error(f"Исчерпаны все попытки отправки запроса для чека {check_uuid}")
                return None

    return None


async def recognize_check_by_anthropic(file_location_directory: str, check_uuid) -> Optional[Dict[Any, Any]]:
    """
    Распознаёт чек с помощью Anthropic API.

    Args:
        file_location_directory: Путь к файлу чека
        check_uuid:

    Returns:
        Словарь с данными чека или None в случае ошибки
    """
    try:
        # Формируем сообщение для API
        message = await message_for_anthropic(file_location_directory, prompt=prompt)

        # Отправляем запрос с повторными попытками
        response_text = await send_request_to_anthropic(message, check_uuid, max_retries=2)

        if response_text is None:
            logger.error(f"Не удалось получить ответ от API для чека {check_uuid}")
            return None

        # Извлекаем и парсим JSON из ответа
        data = extract_json_from_response(response_text)

        if data:
            logger.info(f"Чек {check_uuid} успешно распознан")
            return data
        else:
            logger.error(f"Не удалось извлечь данные чека {check_uuid}")
            return None

    except Exception as e:
        logger.error(f"Неожиданная ошибка при распознавании чека {check_uuid}: {e}")
        return None
    finally:
        # Очищаем переменные
        if 'message' in locals():
            del message


if __name__ == '__main__':
    # Start timer
    start_time = time.time()

    completion = recognize_check_by_anthropic("../images/d783c1e1-6802-4a4c-ad82-a0de3907fd9c", "d783c1e1-6802-4a4c-ad82-a0de3907fd9c")

    # End timer
    end_time = time.time()
    elapsed_time = end_time - start_time

    # Output result and time taken
    print("🧠 Recognition Output:")
    print(completion)
    print(f"\n⏱️ Time taken for recognition: {elapsed_time:.2f} seconds")
