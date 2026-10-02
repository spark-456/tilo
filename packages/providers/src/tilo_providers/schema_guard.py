"""tilo_providers.schema_guard -- a linear `uniqueItems` for the jsonschema validators Tilo runs (#124, #173).

jsonschema's `uniqueItems` compares every pair of unsortable items (3000 dicts took 39.5 s). `unique_items`
hashes a canonical form of each item (1 == 1.0, True != 1), so the keyword is linear wherever jsonschema meets
it: anyOf/oneOf/if, `$ref`, recursion, any item type. `guarded(cls)` adds it and `anyOf`/`oneOf` that keep
at most MAX_ERRORS errors per branch. A subschema's `$schema` swaps in a stock class, so `validator` drops
the root's (no other is allowed, tested). Callers read MAX_ERRORS errors; messages are capped (`short`)."""

from __future__ import annotations

import functools
import itertools
from collections.abc import Iterator
from typing import Any

import jsonschema
from jsonschema.exceptions import ValidationError, best_match

MAX_ERRORS = 50  # errors read from one validation; the rest are not computed
MESSAGE_CHARS = 300  # longest error message kept: its head and tail, joined by " ... "


def _canonical(value: Any) -> Any:
    """A hashable form equal for JSON-equal values: numbers by value, booleans apart from numbers."""
    if isinstance(value, bool):
        return ("b", value)
    if isinstance(value, int | float):
        return ("n", value)
    if isinstance(value, str):
        return ("s", value)
    if isinstance(value, list):
        return ("a", tuple(map(_canonical, value)))
    if isinstance(value, dict):
        return ("o", frozenset((key, _canonical(item)) for key, item in value.items()))
    return ("z", repr(value))


def unique_items(validator: Any, unique: Any, instance: Any, schema: dict[str, Any]) -> Iterator[ValidationError]:
    if not unique or not validator.is_type(instance, "array"):
        return
    seen: dict[Any, int] = {}
    for index, item in enumerate(instance):
        first = seen.setdefault(_canonical(item), index)
        if first != index:
            yield ValidationError(f"has non-unique elements (item {index} repeats item {first})")
            return


def any_of(validator: Any, branches: list[Any], instance: Any, schema: dict[str, Any]) -> Iterator[ValidationError]:
    """jsonschema's `anyOf`, keeping at most MAX_ERRORS errors per branch (it kept every one)."""
    found: list[ValidationError] = []
    for index, subschema in enumerate(branches):
        errors = list(itertools.islice(validator.descend(instance, subschema, schema_path=index), MAX_ERRORS))
        if not errors:
            return
        found += errors
    yield ValidationError(f"{instance!r} is not valid under any of the given schemas", context=found)


def one_of(validator: Any, branches: list[Any], instance: Any, schema: dict[str, Any]) -> Iterator[ValidationError]:
    """jsonschema's `oneOf`, keeping at most MAX_ERRORS errors per branch."""
    found: list[ValidationError] = []
    valid: list[Any] = []
    for index, subschema in enumerate(branches):
        if valid:
            if validator.evolve(schema=subschema).is_valid(instance):
                valid.append(subschema)
        elif errors := list(itertools.islice(validator.descend(instance, subschema, schema_path=index), MAX_ERRORS)):
            found += errors
        else:
            valid.append(subschema)
    if not valid:
        yield ValidationError(f"{instance!r} is not valid under any of the given schemas", context=found)
    elif len(valid) > 1:
        yield ValidationError(f"{instance!r} is valid under each of {', '.join(map(repr, valid[1:] + valid[:1]))}")


@functools.cache
def guarded(cls: Any) -> Any:
    """`cls` with the linear `uniqueItems` and the bounded `anyOf` and `oneOf`."""
    return jsonschema.validators.extend(cls, {"uniqueItems": unique_items, "anyOf": any_of, "oneOf": one_of})


def validator(schema: dict[str, Any]) -> Any:
    """A guarded validator for `schema` (its own `$schema` dialect), after checking the schema."""
    cls = guarded(jsonschema.validators.validator_for(schema))
    cls.check_schema(schema)
    return cls({key: value for key, value in schema.items() if key != "$schema"})


def short(message: str) -> str:
    if len(message) <= MESSAGE_CHARS:
        return message
    half = (MESSAGE_CHARS - 5) // 2
    return f"{message[:half]} ... {message[-half:]}"


def describe(error: ValidationError) -> str:  # "/json/pointer: message", capped
    return short(f"/{'/'.join(map(str, error.absolute_path))}: {error.message}")


def first_error(instance: Any, schema: dict[str, Any]) -> str | None:
    """The first of the shallowest of the first `MAX_ERRORS` errors of `instance` against `schema`,
    taken down into its anyOf/oneOf branches as jsonschema's `best_match` does, described."""
    errors = list(itertools.islice(validator(schema).iter_errors(instance), MAX_ERRORS))
    if not errors:
        return None
    return describe(best_match([min(errors, key=lambda error: len(error.path))]))
