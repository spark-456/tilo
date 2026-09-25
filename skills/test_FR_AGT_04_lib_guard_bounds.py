"""FR-AGT-04 re-scope, point 3: skills/_lib/guard.py is a shared, bounded,
fail-closed helper module. These tests exercise it directly (not through any
skill's check.py) to prove two properties every checker will rely on:

1. Type and size caps on a value (capped strings, capped list lengths, capped
   nesting) never raise and never hang, even on adversarial input -- an oversize
   value always yields a finding instead.
2. Bounded Decimal parsing rejects NaN, infinities, oversize-digit numbers and
   floats-as-strings with an exponent beyond the cap, and never round-trips
   through a Python float (which would silently lose precision).

Ambiguity resolved (ticket brief names the module's capabilities and gives the
exact signature only for `ids_exactly_once`; the other two function names below
are this suite's choice, since a concrete call is needed to write an executable
test): `guard.check_bounds(value)` for the size/nesting caps, and
`guard.parse_decimal(text)` for bounded Decimal parsing. A builder is free to add
more helpers, but these two entry points, with this behaviour, are what every
check.py needs and so are pinned here.

These fail today with "No module named 'skills._lib'" because skills/_lib does
not exist yet.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest


def _import_guard():
    try:
        from skills._lib import guard  # noqa: PLC0415
    except ModuleNotFoundError as exc:
        pytest.fail(f"skills/_lib/guard.py is required (ticket FR-AGT-04 re-scope, point 3): {exc}")
    return guard


# ---------------------------------------------------------------------------
# Bounded size/nesting caps
# ---------------------------------------------------------------------------


def test_FR_AGT_04_guard_huge_string_yields_finding_fast_and_never_raises():
    guard = _import_guard()
    huge_string = "a" * 2_000_000

    started = time.monotonic()
    try:
        findings = guard.check_bounds(huge_string)
    except Exception as exc:  # noqa: BLE001 - the point is that nothing may raise
        pytest.fail(f"guard.check_bounds raised {exc!r} on a 2,000,000-character string; it must fail closed")
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"guard.check_bounds took {elapsed:.2f}s on a 2,000,000-character string, must be < 2s"
    assert isinstance(findings, list)
    assert findings, "a string over the size cap must yield at least one finding"
    for finding in findings:
        assert isinstance(finding, dict) and "check" in finding and "detail" in finding


def test_FR_AGT_04_guard_deep_nesting_yields_finding_fast_and_never_raises():
    guard = _import_guard()
    deeply_nested: object = "leaf"
    for _ in range(10_000):
        deeply_nested = [deeply_nested]

    started = time.monotonic()
    try:
        findings = guard.check_bounds(deeply_nested)
    except Exception as exc:  # noqa: BLE001 - the point is that nothing may raise
        pytest.fail(f"guard.check_bounds raised {exc!r} on 10,000-deep nesting; it must fail closed")
    elapsed = time.monotonic() - started

    assert elapsed < 2.0, f"guard.check_bounds took {elapsed:.2f}s on 10,000-deep nesting, must be < 2s"
    assert isinstance(findings, list)
    assert findings, "nesting over the depth cap must yield at least one finding"
    for finding in findings:
        assert isinstance(finding, dict) and "check" in finding and "detail" in finding


def test_FR_AGT_04_guard_ordinary_value_within_caps_yields_no_finding():
    guard = _import_guard()
    findings = guard.check_bounds({"a": [1, 2, 3], "b": "short string"})
    assert findings == [], f"an ordinary, well-bounded value must yield no findings, got {findings}"


# ---------------------------------------------------------------------------
# Bounded Decimal parsing: finite, magnitude and digit caps; never a float.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "NaN",
        "nan",
        "Infinity",
        "-Infinity",
        "inf",
        "1" * 401,  # 401-digit number, over any reasonable digit cap
        "1e10000",  # float-style exponent far beyond a magnitude cap
    ],
    ids=["nan", "nan-lower", "inf", "neg-inf", "inf-short", "401-digits", "huge-exponent"],
)
def test_FR_AGT_04_guard_parse_decimal_rejects_malformed_values(text):
    guard = _import_guard()
    try:
        result = guard.parse_decimal(text)
    except Exception as exc:  # noqa: BLE001 - bounded parsing must never raise
        pytest.fail(f"guard.parse_decimal raised {exc!r} on {text!r}; malformed input must fail closed, not raise")
    assert result is None, f"guard.parse_decimal({text!r}) must reject the value (return None), got {result!r}"


def test_FR_AGT_04_guard_parse_decimal_accepts_ordinary_values_exactly():
    guard = _import_guard()
    result = guard.parse_decimal("42.50")
    assert result == Decimal("42.50"), (
        f"guard.parse_decimal('42.50') must equal Decimal('42.50') exactly, got {result!r}"
    )

    # 0.1 has no exact binary float representation; a float round-trip would
    # corrupt it. Bounded Decimal parsing must never go through float().
    result = guard.parse_decimal("0.1")
    assert result == Decimal("0.1"), (
        f"guard.parse_decimal('0.1') must equal Decimal('0.1') exactly (never float-parsed), got {result!r}"
    )
