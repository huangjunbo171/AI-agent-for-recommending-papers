import logging
import os
from logging.handlers import TimedRotatingFileHandler
from typing import Optional
from colorlog import ColoredFormatter, StreamHandler

LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red",
}


class Logger:
    def __init__(self, filename: str, level: int = logging.INFO, datefmt: Optional[str] = None):
        self.level = level
        self.datefmt = datefmt
        self.filename = filename
        
        self.logger = self.create_logger()
        self.stream_handler = self.create_stream_handler()
        self.file_handler = self.create_file_handler()
        
        # 只添加处理器，如果 logger 还没有添加过处理器
        if not self.logger.handlers:
            self.stream_handler.setFormatter(self.create_formatter(colored=True))
            self.file_handler.setFormatter(self.create_formatter(colored=False))

            self.logger.addHandler(self.stream_handler)
            self.logger.addHandler(self.file_handler)

    def create_logger(self):
        # 使用filename作为logger名称，避免重复
        _logger = logging.getLogger(self.filename)  
        _logger.setLevel(self.level)
        return _logger

    @staticmethod
    def create_stream_handler():
        return StreamHandler()

    def create_file_handler(self):
        log_dir = os.path.dirname(self.filename)
        os.makedirs(log_dir, exist_ok=True)  # 确保目录存在
        handler = TimedRotatingFileHandler(
            self.filename, when="midnight", interval=1, backupCount=0, encoding='utf-8'
        )
        handler.suffix = "%Y-%m-%d"
        return handler

    def create_formatter(self, colored=False):
        if colored:
            formatter = ColoredFormatter(
                "%(log_color)s%(asctime)s - %(levelname)s - %(message)s",
                datefmt=self.datefmt,
                reset=True,
                log_colors=LOG_COLORS,
            )
        else:
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s",
                datefmt=self.datefmt,
            )
        return formatter


# def logger(filename):
#     return Logger(filename=filename).logger

# 全局缓存
_loggers = {}

def logger(filename):
    if filename in _loggers:
        return _loggers[filename]
    log_obj = Logger(filename=filename).logger
    _loggers[filename] = log_obj
    return log_obj