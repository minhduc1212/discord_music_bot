import logging
import logging.handlers

def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("musicbot")
    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "[{asctime}] [{levelname:<8}] {name}: {message}",
        datefmt="%Y-%m-%d %H:%M:%S",
        style="{",
    )
    fh = logging.handlers.RotatingFileHandler(
        "discord.log", encoding="utf-8", maxBytes=16 * 1024 * 1024, backupCount=3
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    logger.addHandler(fh)
    logger.addHandler(ch)
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)
    return logger

log = _setup_logging()