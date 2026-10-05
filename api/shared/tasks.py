import os
import logging
import sys
from typing import Any
from celery import Celery
from celery.signals import after_setup_task_logger, after_setup_logger, task_prerun
from celery.app.log import TaskFormatter  # type: ignore
from .log import FORMAT, DATEFMT, LEVEL
from . import config

MAX_QUEUE = 20
MAX_CPU = 80

HIGH_PRIORITY = 0
NORMAL_PRIORITY = 5
LOW_PRIORITY = 9

TASKFORMAT = "%(asctime)s.%(msecs)03d %(levelname)s [%(process)d] %(module)s.%(funcName)s[%(task_id)s]:%(lineno)d: %(message)s"

tasks = Celery(
    "tasks",
    broker="%s://%s:%s@%s/%s"
    % (
        os.environ["queue_proto"],
        os.environ["queue_user"],
        os.environ["queue_pass"],
        os.environ["queue_host"],
        os.environ["queue_db"],
    ),
)

# Independent opt-ins until dedicated consumers are running. Tasks outside
# these explicit routes retain the default queue, including unknown future types.
INTERACTIVE_TASKS = frozenset({"api.lists.list_find_start", "api.lists.list_find"})


def route_transactional_task(name, args, kwargs, options, task=None, **extra):
    # Route the orchestration task, not shared provider adapters used by broadcasts.
    if os.environ.get("transactional_task_queue", "").lower() in ("true", "1") and name == "api.transactional.send_txn":
        return {"queue": "transactional"}
    return None


def route_interactive_task(name, args, kwargs, options, task=None, **extra):
    if os.environ.get("interactive_task_queue", "").lower() in ("true", "1") and name in INTERACTIVE_TASKS:
        return {"queue": "interactive"}
    return None


tasks.conf.update(
    task_routes=(route_transactional_task, route_interactive_task),
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "sep": ":",
        "queue_order_strategy": "priority",
        "visibility_timeout": 900,
    },
)


@after_setup_logger.connect
def setup_logger(logger: logging.Logger, *args: Any, **kwargs: Any) -> None:
    for handler in logger.handlers:
        handler.setFormatter(logging.Formatter(FORMAT, DATEFMT))
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter(FORMAT, DATEFMT))
    logger.addHandler(h)


@after_setup_task_logger.connect
def setup_task_logger(logger: logging.Logger, *args: Any, **kwargs: Any) -> None:
    for handler in logger.handlers:
        fmt = TaskFormatter(TASKFORMAT)
        fmt.datefmt = DATEFMT
        # not a documented API, may break in the future but its the best way I could find to not
        # output ANSI colors into the log file
        fmt.use_color = False
        handler.setFormatter(fmt)
    h = logging.StreamHandler(sys.stdout)
    fmt = TaskFormatter(TASKFORMAT)
    fmt.datefmt = DATEFMT
    fmt.use_color = False  # ditto
    h.setFormatter(fmt)
    logger.addHandler(h)
    logger.setLevel(LEVEL)
