# Shared bounded, fail-closed helpers for skills/**/check.py (FR-AGT-04).
# Malformed or oversize input never raises here; it yields a finding instead.
# check.py may import only this module and the standard library.

import re
from decimal import Decimal

MAX_STR = 20_000
MAX_ITEMS = 2_000
MAX_DEPTH = 20

_DEC_RE = re.compile(r"^[+-]?\d{1,40}(\.\d{1,40})?$")
_NUM_RE = re.compile(r"(?<!\w)[+-]?\d[\d,]*(?:\.\d+)?(?!\w)")


def finding(check: str, detail: object) -> dict:
    return {"check": check, "detail": str(detail)[:300]}


def check_bounds(value: object) -> list[dict]:
    findings: list[dict] = []
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH:
            findings.append(finding("bounds-depth", f"nesting exceeds {MAX_DEPTH} levels"))
            continue
        if isinstance(node, str) and len(node) > MAX_STR:
            findings.append(finding("bounds-string", f"a string exceeds {MAX_STR} characters"))
        elif isinstance(node, (dict, list, tuple)):
            items = list(node.values()) if isinstance(node, dict) else list(node)
            bad_key = isinstance(node, dict) and any(len(k) > MAX_STR for k in node if isinstance(k, str))
            if len(items) > MAX_ITEMS or bad_key:
                findings.append(finding("bounds-size", "too many entries, or a key too long"))
            stack += [(v, depth + 1) for v in items[:MAX_ITEMS]]
    return findings


def parse_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        text = repr(value)
    elif isinstance(value, str):
        text = value.strip()
    else:
        return None
    if not _DEC_RE.match(text):
        return None
    try:
        dec = Decimal(text)
        return dec if dec.is_finite() else None
    except Exception:  # noqa: BLE001 - parsing must never raise
        return None


def number_tokens(text: object) -> set[str]:
    if not isinstance(text, str):
        return set()
    return {m.group(0).lstrip("+").replace(",", "") for m in _NUM_RE.finditer(text[:MAX_STR])}


def ids_exactly_once(expected_ids, rows: object, key: str) -> list[dict]:
    if not isinstance(rows, list):
        return [finding("ids-malformed", f"expected a list of rows keyed by {key!r}, got {type(rows).__name__}")]
    expected = {e for e in (expected_ids or []) if isinstance(e, str)}
    counts: dict[str, int] = {}
    for row in rows[:MAX_ITEMS]:
        raw = row.get(key) if isinstance(row, dict) else None
        skey = raw if isinstance(raw, str) else repr(raw)
        counts[skey] = counts.get(skey, 0) + 1
    missing, unknown = expected - counts.keys(), counts.keys() - expected
    dup = {k for k, c in counts.items() if k in expected and c > 1}
    out = [finding("ids-missing", f"missing: {sorted(missing)}")] if missing else []
    out += [finding("ids-unknown", f"unknown: {sorted(unknown)}")] if unknown else []
    out += [finding("ids-duplicate", f"duplicate: {sorted(dup)}")] if dup else []
    return out


def str_ids(items: object, key: str) -> set[str]:
    rows = items if isinstance(items, list) else []
    return {v for it in rows if isinstance(it, dict) and isinstance((v := it.get(key)), str)}


def index_by(items: object, key: str) -> dict:
    rows = items if isinstance(items, list) else []
    return {it[key]: it for it in rows if isinstance(it, dict) and isinstance(it.get(key), str)}


def gather_material(inputs: dict) -> tuple[set, set]:
    m1, m2 = inputs.get("material"), inputs.get("materials")
    items = m1 if isinstance(m1, list) else (m2 if isinstance(m2, list) else [])
    tokens, ids = set(), set()
    for m in items:
        if not isinstance(m, dict):
            continue
        tokens |= number_tokens(m.get("text"))
        mid = next((m[k] for k in ("source_id", "material_id", "id") if isinstance(m.get(k), str)), None)
        ids |= {mid} if mid else set()
    return tokens, ids


# SafetyProvider items (PRD 16.3 point 2): safety_flags must be a list of
# non-empty strings, empty means clean; missing/None/any other shape is
# malformed and must not silently read as clean (fail-open otherwise).
def flags_malformed(items: object) -> list[dict]:
    out: list[dict] = []
    for it in items if isinstance(items, list) else []:
        f = it.get("safety_flags") if isinstance(it, dict) else None
        valid = f == [] or (isinstance(f, list) and f and all(isinstance(x, str) and x for x in f[:MAX_ITEMS]))
        out += [finding("safety-flags-malformed", f"not a list of non-empty strings: {f!r}")] if not valid else []
    return out


def fail_closed(fn):
    def wrapper(inputs, output):
        bounds = check_bounds(inputs) + check_bounds(output)
        try:
            result = bounds or fn(inputs, output)
        except Exception as exc:  # noqa: BLE001 - the point is to never raise
            return [finding("checker-error", f"{type(exc).__name__}: {exc}")]
        return result if isinstance(result, list) else [finding("checker-error", "check() returned a non-list")]

    return wrapper
