"""FR-SKL-03: read-only comparison of taught steps and recorded rehearsal steps.

This computes feedback from records; it never executes a step or authorizes an action.
Keys are exact (verb, object, tool) strings: resource identity is case-sensitive.
"""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from typing import Any

Step = dict[str, Any]
Key = tuple[str, str, str]


def _keys(steps: list[Step], flag: str) -> list[Key]:
    keys: list[Key] = []
    for step in steps:
        values = [step.get(field) for field in ("verb", "object", "tool")]
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError("Each step needs non-empty verb, object and tool strings")
        if not isinstance(step.get(flag), bool):
            raise ValueError(f"Each step needs a boolean {flag}")
        keys.append((step["verb"], step["object"], step["tool"]))
    return keys


def score_try_run(taught_steps: list[Step], recorded_steps: list[Step]) -> dict[str, Any]:
    """Return match percentage and ordered differences, plus recorded pause feedback.

    A missed taught pause or empty example fails with zero percent. Repeated identical
    steps pair by occurrence for pause feedback; one pause cannot cover two occurrences.
    Alignment uses longest common subsequence with an earlier taught-step tie break.
    The percentage is matches / max(taught count, recorded count), rounded to one decimal.
    Input records are validated, never modified, and output records are independent copies.
    """
    taught_keys = _keys(taught_steps, "ask_me_first")
    recorded_keys = _keys(recorded_steps, "paused")
    occurrences: dict[Key, deque[int]] = defaultdict(deque)
    for index, key in enumerate(recorded_keys):
        occurrences[key].append(index)
    paused: list[Step] = []
    missed: list[Step] = []
    for step, key in zip(taught_steps, taught_keys, strict=True):
        recorded_index = occurrences[key].popleft() if occurrences[key] else None
        if step["ask_me_first"]:
            destination = paused if recorded_index is not None and recorded_steps[recorded_index]["paused"] else missed
            destination.append(step)

    m, n = len(taught_keys), len(recorded_keys)
    lengths = [[0] * (n + 1) for _ in range(m + 1)]
    for i, taught_key in enumerate(taught_keys):
        for j, recorded_key in enumerate(recorded_keys):
            lengths[i + 1][j + 1] = (
                lengths[i][j] + 1 if taught_key == recorded_key else max(lengths[i][j + 1], lengths[i + 1][j])
            )
    matched_taught: set[int] = set()
    matched_recorded: set[int] = set()
    i, j = m, n
    while i and j:
        if taught_keys[i - 1] == recorded_keys[j - 1]:
            matched_taught.add(i - 1)
            matched_recorded.add(j - 1)
            i, j = i - 1, j - 1
        elif lengths[i - 1][j] >= lengths[i][j - 1]:
            i -= 1
        else:
            j -= 1
    reason = "empty_taught_example" if not taught_steps else "missed_ask_first_pause" if missed else None
    percent = round(100 * len(matched_taught) / max(m, n), 1) if reason is None else 0.0
    return {
        "status": "fail" if reason else "pass",
        "match_percent": percent,
        "matched_steps": deepcopy([taught_steps[k] for k in sorted(matched_taught)]),
        "added_steps": deepcopy([step for k, step in enumerate(recorded_steps) if k not in matched_recorded]),
        "skipped_steps": deepcopy([step for k, step in enumerate(taught_steps) if k not in matched_taught]),
        "paused_ask_first_steps": deepcopy(paused),
        "missed_ask_first_steps": deepcopy(missed),
        "failure_reason": reason,
    }
