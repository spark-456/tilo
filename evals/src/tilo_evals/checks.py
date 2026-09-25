"""Check registry (EFF-07; PRD 19.2, 19.3). Part a: `@register` and `is_registered`; the checks land in part b."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    cause: str | None = None
    detail: Any = None


CheckFn = Callable[..., CheckResult]
_REGISTRY: dict[str, CheckFn] = {}


def register(name: str) -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY[name] = fn
        return fn

    return decorator


def is_registered(name: str) -> bool:
    return name in _REGISTRY
