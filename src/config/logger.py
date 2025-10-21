import logging
import socket
import sys
import time
import uuid
from logging.handlers import SysLogHandler
from typing import Callable, Optional

import graypy
from fastapi import FastAPI, Request, Response
from rfc5424logging import Rfc5424SysLogHandler
from starlette.middleware.base import BaseHTTPMiddleware


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware для логирования всех HTTP-запросов и ответов."""
    def __init__(
            self,
            app: FastAPI,
            logger: logging.Logger
    ):
        super().__init__(app)
        self.logger = logger

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        EXCLUDED_PATHS = {"/metrics", "/api/health", "/api/4509195408244816/envelope/"}

        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        start_time = time.time()

        self.logger.info(
            f"Request started | ID: {request_id} | Method: {request.method} | "
            f"Path: {request.url.path} | Client: {request.client.host if request.client else 'Unknown'}"
        )

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            self.logger.info(
                f"Request completed | ID: {request_id} | Status: {response.status_code} | "
                f"Duration: {process_time:.4f}s"
            )

            response.headers["X-Request-ID"] = request_id
            return response

        except Exception as exc:
            process_time = time.time() - start_time
            self.logger.exception(
                f"Request failed | ID: {request_id} | Duration: {process_time:.4f}s | "
                f"Error: {str(exc)}"
            )
            raise


def setup_logging(
        app: Optional[FastAPI] = None,
        service_name: str = "fastapi-app",
        log_level: str = "INFO",
        syslog_enabled: bool = False,
        syslog_host: str = "localhost",
        syslog_port: int = 1514,
        syslog_facility: int = SysLogHandler.LOG_USER,
        graylog_enabled: bool = False,
        graylog_host: str = "localhost",
        graylog_port: int = 12201,
        add_middleware: bool = True
) -> logging.Logger:
    """
    Настраивает централизованное логирование для FastAPI-приложения в формате RFC5424.

    Args:
        app: Экземпляр FastAPI, если требуется middleware.
        service_name: Имя сервиса для логов.
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        syslog_enabled: Включение отправки логов в Syslog.
        syslog_host: Хост Syslog-сервера.
        syslog_port: Порт Syslog-сервера.
        syslog_facility: Facility для Syslog.
        graylog_enabled: Включение отправки логов в Graylog
        graylog_host: Хост Graylog-сервера.
        graylog_port: Порт Graylog-сервера.
        add_middleware: Добавить middleware для логирования запросов.

    Returns:
        Настроенный логгер.
    """

    logging.getLogger("tzlocal").setLevel(logging.WARNING)
    logging.getLogger("tzlocal").propagate = False
    logging.getLogger("zoneinfo").setLevel(logging.WARNING)
    logging.getLogger("zoneinfo").propagate = False

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(pathname)s:%(lineno)d | "
        f"service={service_name} | %(message)s"
    )

    # log_format = logging.Formatter(
    #     "%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | "
    #     f"service={service_name} | %(message)s"
    # )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    console_handler.stream.reconfigure(encoding="utf-8")
    root_logger.addHandler(console_handler)

    class UvicornAccessFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            message = record.getMessage()
            # Исключаем запросы к /metrics и к Sentry
            return "/metrics" not in message and "sentry.io" not in message

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.addFilter(UvicornAccessFilter())

    if graylog_enabled:
        graylog_handler = graypy.GELFUDPHandler(
            graylog_host,
            graylog_port,
            localname=service_name
        )
        root_logger.addHandler(graylog_handler)

    # Syslog обработчик
    if syslog_enabled:
        # Настройка обработчика syslog
        try:
            rfc5424handler = Rfc5424SysLogHandler(
                address=(syslog_host, syslog_port),
                socktype=socket.SOCK_STREAM,
                appname=service_name,
                msg_as_utf8=True,
                facility=syslog_facility
            )
            rfc5424handler.setLevel(logging.DEBUG)
            root_logger.addHandler(rfc5424handler)
        except Exception as e:
            print(f"Ошибка настройки обработчика: {e}")

    logger = logging.getLogger(service_name)

    if app and add_middleware:
        app.add_middleware(RequestLoggingMiddleware, logger=logger)

    return logger
