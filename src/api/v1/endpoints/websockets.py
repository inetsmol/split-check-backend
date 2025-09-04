# src/api/v1/endpoints/websockets.py
import logging
from typing import Annotated

from fastapi import Depends, APIRouter, HTTPException
from jose import JWTError
from starlette.websockets import WebSocket, WebSocketDisconnect

from src.api.deps import get_current_user_for_websocket
from src.config import config
from src.models import User
from src.websockets.manager import ws_manager

logger = logging.getLogger(config.app.service_name)

router = APIRouter()


@router.websocket("/ws", name="websocket_endpoint")
async def websocket_endpoint(websocket: WebSocket,
                             user: Annotated[User, Depends(get_current_user_for_websocket)]):
    logger.debug("websocket.headers: %s", websocket.headers, extra={"current_user_id": user.id})
    user_id = user.id
    try:
        await ws_manager.connect(user_id, websocket)
        try:
            while True:
                data = await websocket.receive_text()
                logger.debug("Received message from %s: %s", user_id, data, extra={"current_user_id": user_id})
        except WebSocketDisconnect:
            await ws_manager.disconnect(user_id)
            logger.debug("User %s disconnected", user_id, extra={"current_user_id": user_id})

    except JWTError as e:
        logger.error("JWT error: %s", e)
        await websocket.accept()
        await websocket.send_json({"error": "unauthorized", "message": "Invalid token. Redirect to login page."})
        await websocket.close()
    except HTTPException as e:
        logger.error("HTTP error: %s", e.detail)
        await websocket.accept()
        await websocket.send_json({"error": "unauthorized", "message": f"{e.detail}. Redirect to login page."})
        await websocket.close()
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        await websocket.close()