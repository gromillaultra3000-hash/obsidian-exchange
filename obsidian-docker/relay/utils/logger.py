import logging
import os

LOG_DIR = '/root/relay/logs'
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

def get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Обработчик для файла
    fh = logging.FileHandler(f'{LOG_DIR}/relay.log')
    fh.setLevel(logging.INFO)

    # Обработчик для консоли
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger
