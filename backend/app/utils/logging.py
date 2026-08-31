import logging
import sys
from ..config import settings


def setup_logging():
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.WARNING if settings.APP_ENV == "production" else logging.INFO
    )

    return root_logger


logger = logging.getLogger("smart_energy")
