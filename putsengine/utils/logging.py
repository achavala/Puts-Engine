"""
Logging configuration for PutsEngine.
"""

import sys
from pathlib import Path
from loguru import logger

from putsengine.config import Settings


def setup_logging(settings: Settings) -> None:
    """
    Configure logging for the application.

    Args:
        settings: Application settings with log configuration
    """
    # Remove default handler
    logger.remove()

    # Console handler with colors
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        level=settings.log_level,
        colorize=True
    )

    # File handler
    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        settings.log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        level=settings.log_level,
        rotation="10 MB",
        retention="7 days",
        compression="gz"
    )

    logger.info(f"Logging configured: level={settings.log_level}, file={settings.log_file}")


def get_logger(name: str):
    """Get a logger instance with the given name."""
    return logger.bind(name=name)
