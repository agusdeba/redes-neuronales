"""Logging estructurado (JSON lines) por fuente y por corrida."""
from __future__ import annotations

import json
import logging
import time
import uuid

from .config import LOGS

RUN_ID = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        d = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created)),
             "level": record.levelname, "logger": record.name, "run_id": RUN_ID,
             "msg": record.getMessage()}
        extra = getattr(record, "data", None)
        if extra:
            d.update(extra)
        return json.dumps(d, ensure_ascii=False, default=str)


_configured = set()


def get_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    if name in _configured:
        return log
    log.setLevel(logging.INFO)
    log.propagate = False
    fh = logging.FileHandler(LOGS / f"{name}_{RUN_ID}.jsonl", encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s", "%H:%M:%S"))
    log.addHandler(fh)
    log.addHandler(ch)
    _configured.add(name)
    return log
