import logging
import os

os.makedirs("logs", exist_ok=True)

def setup_logger(name: str, log_file: str, level=logging.INFO):
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler = logging.FileHandler(f"logs/{log_file}")
    handler.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger

bot_logger = setup_logger("bot", "bot.log")
error_logger = setup_logger("error", "errors.log", logging.ERROR)
admin_logger = setup_logger("admin", "admin_actions.log")
