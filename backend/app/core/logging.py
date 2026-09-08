import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Only our explicit event names and opaque IDs enter logs. No transcripts or exceptions.
        return json.dumps({"time": datetime.now(timezone.utc).isoformat(),
                           "level": record.levelname, "event": record.getMessage(),
                           "recording_id": getattr(record, "recording_id", None)}, ensure_ascii=False)


def configure(settings):
    folder = settings.data_directory / "logs"
    folder.mkdir(exist_ok=True)
    logger = logging.getLogger("jarvis")
    logger.setLevel(settings.log_level)
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)
    handler = RotatingFileHandler(folder / "backend.jsonl", maxBytes=2_000_000,
                                  backupCount=4, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
