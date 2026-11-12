"""统一的响应信封与通用工具。"""
from __future__ import annotations

from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 1, data: Any = None) -> dict:
    return {"code": code, "message": message, "data": data}
