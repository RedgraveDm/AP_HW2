import os
from datetime import datetime
from enum import Enum


class EventType(Enum):
    INFO = "INFO"
    WARNING = "WARN"
    ERROR = "ERR"


class Logger:
    def __init__(self, log_name):
        self.log_name = log_name

    def log(self, message, event_type: EventType):
        if not isinstance(event_type, EventType):
            raise ValueError("Invalid event type. Must be an instance of EventType")

        current_time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        log_entry = f"[{current_time}]  {event_type.value}  {message}\n"

        with open(self.log_name, "a", encoding="utf-8") as f:
            f.write(log_entry)

    def log_exception(self, message, exception: Exception):
        message = f"{message}: ({type(exception).__name__}) {str(exception)}"
        self.log(message, EventType.ERROR)
