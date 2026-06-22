"""Run shell commands and capture output for Textual screens."""

from __future__ import annotations

import io
import contextlib
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def _run_captured(fn: Callable[[], object]) -> tuple[str, int, object]:
    buf = io.StringIO()
    rc = 0
    result: object = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        try:
            result = fn()
            if isinstance(result, int):
                rc = result
            elif result is False:
                rc = 1
        except SystemExit as exc:
            rc = int(exc.code) if isinstance(exc.code, int) else 1
        except Exception as exc:
            print(str(exc))
            rc = 1
    text = buf.getvalue().strip()
    return text or "(no output)", rc, result


def capture_output(fn: Callable[[], object]) -> tuple[str, int]:
    text, rc, _ = _run_captured(fn)
    return text, rc


def capture_call(fn: Callable[[], T]) -> tuple[str, int, T | None]:
    text, rc, result = _run_captured(fn)
    return text, rc, result  # type: ignore[return-value]
