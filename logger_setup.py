"""
Logging Configuration — dual output to console (colored) and daily log file.
"""
import os
import logging
from datetime import datetime
import config


def setup_logger(name="trading_bot"):
    """Create and return a logger that writes to console and a daily log file."""
    os.makedirs(config.LOGS_DIR, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers on re-init
    if logger.handlers:
        return logger

    # ── Console handler (INFO and above) ──
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch_fmt = logging.Formatter("  %(message)s")
    ch.setFormatter(ch_fmt)
    logger.addHandler(ch)

    # ── File handler (DEBUG and above) ──
    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(config.LOGS_DIR, f"trading_{today}.log")
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh_fmt = logging.Formatter("%(asctime)s [%(levelname)-8s] %(message)s",
                               datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fh_fmt)
    logger.addHandler(fh)

    return logger


def get_logger():
    """Get or create the trading bot logger."""
    return logging.getLogger("trading_bot")
