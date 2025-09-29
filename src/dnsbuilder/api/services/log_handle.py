import logging
from typing import List
import asyncio
from ..wsm import manager

class UILogHandler(logging.Handler):
    def __init__(self, build_id: str, logs_list: List[str]):
        super().__init__()
        self.build_id = build_id
        self.logs_list = logs_list

    def emit(self, record):
        log_entry = self.format(record)
        self.logs_list.append(log_entry)
        asyncio.run(manager.broadcast(f"log:{self.build_id}:{log_entry}"))
