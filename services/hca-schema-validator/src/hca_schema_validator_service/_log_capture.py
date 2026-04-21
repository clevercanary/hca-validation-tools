"""Shared logging-capture scaffold for validator subprocess entry points.

Each entry script (``main.py``, ``cell_annotation.py``) runs a validator that
emits warnings/errors via a module logger. This helper attaches a handler to
that logger, invokes the validator, and returns the standard subprocess
response shape (``{valid, warnings, errors}``) that the dataset-validator
service expects.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional


class ListHandler(logging.Handler):
  """Capture warning and error log records into lists."""

  def __init__(self, warning_list: List[str], error_list: List[str]) -> None:
    super().__init__()
    self.warning_list = warning_list
    self.error_list = error_list

  def emit(self, record: logging.LogRecord) -> None:
    if record.levelno == logging.ERROR:
      self.error_list.append(self.format(record))
    elif record.levelno == logging.WARNING:
      self.warning_list.append(self.format(record))


def run_with_captured_logs(
  *,
  file_path: str,
  logger_name: str,
  validate: Callable[[str], bool],
  unexpected_error_prefix: str,
  postprocess_warnings: Optional[Callable[[List[str]], List[str]]] = None,
) -> dict:
  """Invoke ``validate(file_path)`` with warnings/errors captured from ``logger_name``.

  Unexpected exceptions are converted to a single-error failure response
  prefixed with ``unexpected_error_prefix``. ``postprocess_warnings`` lets
  callers reorder or filter the captured warning list before returning.
  """
  logger = logging.getLogger(logger_name)
  logger.setLevel(logging.WARNING)
  warning_messages: List[str] = []
  error_messages: List[str] = []
  logger.addHandler(ListHandler(warning_messages, error_messages))

  try:
    is_valid = validate(file_path)
  except Exception as e:
    is_valid = False
    warning_messages = []
    error_messages = [f"{unexpected_error_prefix}: {e}"]

  if postprocess_warnings is not None:
    warning_messages = postprocess_warnings(warning_messages)

  return {
    "valid": is_valid,
    "warnings": warning_messages,
    "errors": error_messages,
  }
