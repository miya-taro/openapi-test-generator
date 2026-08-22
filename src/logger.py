"""pino 相当の薄いロガーラッパー。

呼び出し規約は pino に合わせ、`log.info(message)` と
`log.info(fields_dict, message)` の両方を受け付ける。
"""
from __future__ import annotations
import logging

_logger = logging.getLogger("openapi_test_gen")
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    _logger.addHandler(_handler)
_logger.setLevel(logging.INFO)
_logger.propagate = False

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}


def set_log_level(level: str) -> None:
    _logger.setLevel(_LEVELS.get(level.lower(), logging.INFO))


def _format(fields: dict, message: str) -> str:
    if not fields:
        return message
    extra = " ".join(f"{k}={v!r}" for k, v in fields.items())
    return f"{message} ({extra})"


def _log(level: int, *args: object) -> None:
    if len(args) == 1:
        fields: dict = {}
        message = str(args[0])
    else:
        fields = args[0] or {}  # type: ignore[assignment]
        message = str(args[1])
    _logger.log(level, _format(fields, message))


def debug(*args: object) -> None:
    _log(logging.DEBUG, *args)


def info(*args: object) -> None:
    _log(logging.INFO, *args)


def warn(*args: object) -> None:
    _log(logging.WARNING, *args)


def error(*args: object) -> None:
    _log(logging.ERROR, *args)
