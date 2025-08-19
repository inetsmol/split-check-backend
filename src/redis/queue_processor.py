import asyncio
import json
import logging
import os
from typing import Callable, Dict, Set, Optional

from .redis_client import RedisClient
from ..config import config

logger = logging.getLogger(config.app.service_name)


class QueueProcessor:
    _instance = None

    def __new__(cls, redis_client: RedisClient, queue_name: str):
        if cls._instance is None:
            cls._instance = super(QueueProcessor, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, redis_client: RedisClient, queue_name: str):
        if self._initialized:
            return

        self.redis_client = redis_client
        self.queue_name = queue_name
        self.task_handlers: Dict[str, Callable] = {}
        self.running = False
        # Устанавливаем количество обработчиков на основе числа CPU ядер
        cpu_count = os.cpu_count() or 1  # Если os.cpu_count() вернёт None, используем 1
        self.queue_semaphore = asyncio.Semaphore(cpu_count * 2)  # Ограничиваем по числу ядер
        self.active_tasks: Set[int] = set()

        logger.info(f"Инициализирован QueueProcessor с {self.queue_semaphore._value} обработчиками (по числу CPU ядер)")
        print(f"Инициализирован QueueProcessor с {self.queue_semaphore._value} обработчиками (по числу CPU ядер)")
        self._initialized = True

    def register_handler(self, task_type: str, handler: Callable):
        self.task_handlers[task_type] = handler
        logger.debug(f"Зарегистрирован обработчик для задач типа '{task_type}'")

    async def process_queue(self):
        if self.running:
            logger.warning("QueueProcessor уже выполняется! Повторный запуск предотвращен.")
            return

        self.running = True
        logger.info(f"Запуск процесса обработки очереди '{self.queue_name}'")

        try:
            while True:
                try:
                    # Проверяем, не слишком ли много активных задач
                    if len(self.active_tasks) >= self.queue_semaphore._value * 2:
                        # Если слишком много задач в обработке, делаем паузу
                        await asyncio.sleep(0.5)
                        continue

                    # Получение задачи из очереди с таймаутом
                    try:
                        task = await asyncio.wait_for(
                            self.redis_client.pop_task(self.queue_name),
                            timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        # Если таймаут, продолжаем цикл
                        continue

                    if not task:
                        await asyncio.sleep(0.5)
                        continue

                    _, task_json = task  # Распаковка задачи
                    task_data = json.loads(task_json)

                    # Создаем и запускаем задачу асинхронно
                    task_type = task_data.get('type')
                    if task_type in self.task_handlers:
                        handler = self.task_handlers[task_type]

                        # Используем замыкание для отслеживания задачи
                        async def process_with_semaphore():
                            task_id = id(task_data)
                            self.active_tasks.add(task_id)
                            try:
                                async with self.queue_semaphore:
                                    logger.debug(f"Выполнение задачи типа '{task_type}' (ID: {task_id})")
                                    await asyncio.wait_for(handler(task_data), timeout=60)

                                    logger.debug(f"Выполнение задачи типа '{task_type}' (ID: {task_id}) закончено")
                            except asyncio.TimeoutError:
                                logger.error(
                                    f"Задача '{task_type}' (ID: {task_id}) превысила время ожидания (60 секунд)")
                            except Exception as e:
                                logger.error(f"Ошибка обработки задачи '{task_type}' (ID: {task_id}): {e}")
                            finally:
                                self.active_tasks.discard(task_id)

                        asyncio.create_task(process_with_semaphore())
                    else:
                        logger.warning(f"Неизвестный тип задачи: {task_type}")

                except Exception as e:
                    logger.error(f"Ошибка в процессоре очереди: {e}")
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.info("Процесс обработки очереди отменен")
            raise
        except Exception as e:
            logger.error(f"Неожиданная ошибка в процессоре очереди: {e}")
        finally:
            self.running = False
            logger.info("Процесс обработки очереди остановлен")

    async def push_task(self, task_data: dict, queue_name: Optional[str] = None) -> None:
        """Добавляет задачу в очередь Redis"""
        target_queue = queue_name or self.queue_name
        task_type = task_data.get('type', 'unknown')
        logger.debug(f"Добавление задачи типа '{task_type}' в очередь '{self.queue_name}'")
        await self.redis_client.push_task(target_queue, json.dumps(task_data))

    async def stop(self) -> None:
        """Корректная остановка обработчика очереди"""
        self.running = False
        logger.info("Запрошена остановка QueueProcessor")
        # Здесь можно добавить код для ожидания завершения всех активных задач
        while self.active_tasks:
            logger.info(f"Ожидание завершения {len(self.active_tasks)} активных задач...")
            await asyncio.sleep(0.5)


# Singleton фабрика для получения единственного экземпляра
_queue_processor_instance: Optional[QueueProcessor] = None


def get_queue_processor(redis_client: Optional[RedisClient] = None, queue_name: str = "task_queue") -> QueueProcessor:
    global _queue_processor_instance
    if _queue_processor_instance is None:
        if redis_client is None:
            raise ValueError("RedisClient должен быть предоставлен при первой инициализации")
        _queue_processor_instance = QueueProcessor(redis_client, queue_name)
    return _queue_processor_instance