"""Check registry (EFF-07; PRD 19.2, 19.3). Part a of P8-06: `@register` and lookup only;
the five deterministic checks land in part b, none registered here."""

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
    """Adds the decorated check function to the registry under `name`."""

    def decorator(fn: CheckFn) -> CheckFn:
        _REGISTRY[name] = fn
        return fn

    return decorator


def get(name: str) -> CheckFn:
    if name not in _REGISTRY:
        raise KeyError(f"tilo_evals.checks: unregistered check {name!r}")
    return _REGISTRY[name]


def is_registered(name: str) -> bool:
    return name in _REGISTRY
