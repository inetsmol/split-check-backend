import json
import logging
from typing import Optional, Any, Dict

from redis import asyncio as aioredis

from src.config import config

logger = logging.getLogger(config.app.service_name)


class RedisClient:
    def __init__(self, host: str, port: int, db: int = 1, password: Optional[str] = None):
        self.redis_url = f"redis://{host}:{port}/{db}"
        self.password = password
        self.client: Optional[aioredis.Redis] = None

    async def connect(self):
        try:
            self.client = await aioredis.from_url(
                self.redis_url,
                password=self.password,
                decode_responses=True
            )
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        if self.client:
            await self.client.close()
            logger.info("Disconnected from Redis")

    # ========== Queue: Task Producer/Consumer ==========

    async def push_task_json(self, queue_name: str, data: Dict[str, Any]):
        """Push task data as JSON string to Redis queue."""
        try:
            await self.client.lpush(queue_name, json.dumps(data))
        except Exception as e:
            logger.error(f"Error pushing task: {e}")

    async def pop_task_json(self, queue_name: str, timeout: int = 0) -> Optional[Dict[str, Any]]:
        """
        Pop task data from Redis queue and parse as JSON.
        timeout=0 => block until item is available
        """
        try:
            result = await self.client.brpop([queue_name], timeout=timeout)
            if result:
                _, payload = result
                return json.loads(payload)
        except Exception as e:
            logger.error(f"Error popping task: {e}")
        return None

    async def push_task(self, queue_name: str, task_data: str):
        await self.client.lpush(queue_name, task_data)

    async def pop_task(self, queue_name: str) -> list | None:
        try:
            task = await self.client.brpop([queue_name], timeout=0)
            return task
        except Exception as e:
            logger.error(f"Error popping task: {e}")
            return None

    # ========== Result Channels (result:<task_id>) ==========

    async def push_result(self, task_id: str, result: Dict[str, Any]):
        """Push result to unique channel based on task_id."""
        try:
            await self.client.lpush(f"result:{task_id}", json.dumps(result))
        except Exception as e:
            logger.error(f"Error pushing result: {e}")

    async def wait_for_result(self, task_id: str, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        Wait for result by task_id (blocking).
        Will timeout after `timeout` seconds.
        """
        try:
            result = await self.client.brpop([f"result:{task_id}"], timeout=timeout)
            if result:
                _, payload = result
                return json.loads(payload)
        except Exception as e:
            logger.error(f"Error waiting for result: {e}")
        return None

    # ========== Optional Direct Key Access ==========

    async def set(self, key: str, value: str, expire: int = None):
        await self.client.set(key, value, ex=expire)

    async def get(self, key: str) -> Optional[str]:
        return await self.client.get(key)

    async def delete(self, key: str):
        await self.client.delete(key)


