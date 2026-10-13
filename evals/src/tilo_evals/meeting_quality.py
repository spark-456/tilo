"""FR-MTG-03/04: grade saved, independently annotated outputs; no provider execution."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, TypeGuard

from .checks import _strict_equal, _validator

BASES = ("scripted_fakes", "recorded_provider")


def _strings(value: Any) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def _provenance(case: dict[str, Any]) -> bool:
    provenance = case.get("provenance", {})
    if not isinstance(provenance, dict):
        return False
    reviewer, producer = provenance.get("reviewer"), provenance.get("producer")
    payload = {key: case.get(key) for key in ("transcript", "minutes")}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return (
        isinstance(reviewer, str)
        and bool(reviewer.strip())
        and isinstance(producer, str)
        and bool(producer.strip())
        and reviewer != producer
        and provenance.get("recording_sha256") == digest
    )


def _group(cases: list[dict[str, Any]], basis: str) -> dict[str, Any]:
    failures: set[str] = set()
    pending: set[str] = set()
    hits = predicted = expected = valid = false_total = false_caught = 0
    ids = [case.get("id") for case in cases]
    if len(cases) != 12 or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        pending.add("requires 12 distinct case IDs")
    transcripts = [
        json.dumps(case["transcript"].get("utterances"), sort_keys=True)
        for case in cases
        if isinstance(case.get("transcript"), dict)
    ]
    if len(set(transcripts)) != len(transcripts):
        pending.add("requires distinct transcripts")
    for case in cases:
        transcript: Any = case.get("transcript")
        minutes: Any = case.get("minutes")
        schema_valid = all(
            _validator(f"{name}.schema.json").is_valid(value)
            for name, value in (("transcript", transcript), ("minutes", minutes))
        )
        valid += schema_valid
        if not schema_valid:
            failures.add("schema")
            continue
        if transcript["meeting_id"] != minutes["meeting_id"]:
            failures.add("meeting identity")
        utterances = [row["id"] for row in transcript["utterances"]]
        if len(set(utterances)) != len(utterances):
            failures.add("duplicate utterance IDs")
        cited = set(utterances)
        rows = minutes["action_items"]
        action_ids = [row["id"] for row in rows]
        if len(set(action_ids)) != len(action_ids):
            failures.add("duplicate action IDs")
        for row in minutes["summary"] + minutes["agenda"] + minutes["decisions"] + rows:
            if not set(row["evidence"]) <= cited:
                failures.add("evidence")
            if row.get("state") == "verified" and not row["evidence"]:
                failures.add("evidence")
        gold, annotation = case.get("gold"), case.get("annotation")
        if not isinstance(gold, dict) or not isinstance(annotation, dict):
            pending.add("independent annotations missing")
            continue
        gold_ids, planted = gold.get("action_ids"), gold.get("planted_false_ids")
        matches = annotation.get("action_matches")
        inventions = annotation.get("invented_commitment_ids")
        if (
            not _strings(gold_ids)
            or len(set(gold_ids)) != len(gold_ids)
            or not _strings(planted)
            or len(set(planted)) != len(planted)
            or not isinstance(matches, dict)
            or not _strings(inventions)
            or any(not isinstance(k, str) or (v is not None and not isinstance(v, str)) for k, v in matches.items())
        ):
            pending.add("annotation shape")
            continue
        verified = [row for row in rows if row["state"] == "verified"]
        if not {row["id"] for row in verified} <= matches.keys():
            pending.add("action matching incomplete")
        unmatched = set(gold_ids)
        expected += len(gold_ids)
        predicted += len(verified)
        for row in verified:
            match = matches.get(row["id"])
            if match in unmatched:
                hits += 1
                unmatched.remove(match)
        if inventions:
            failures.add("invented commitments")
        for key in ("dates_correct", "ambiguous_names_safe"):
            if type(annotation.get(key)) is not bool:
                pending.add(key)
            elif not annotation[key]:
                failures.add(key)
        if not isinstance(gold.get("agenda"), list):
            pending.add("agenda annotation missing")
        elif not _strict_equal(gold["agenda"], minutes["agenda"]):
            failures.add("agenda")
        score = gold.get("summary_score")
        if type(score) is not int or not 1 <= score <= 5:
            pending.add("summary score missing")
        elif score < 4:
            failures.add("summary rubric")
        false_total += len(planted)
        false_caught += sum(any(row["id"] == i and row["state"] == "unverified" for row in rows) for i in planted)
        if basis == "recorded_provider" and not _provenance(case):
            pending.add("independent bound provenance missing")
    recall = hits / expected if expected else None
    precision = hits / predicted if predicted else (0.0 if expected else None)
    if expected == 0:
        pending.add("action gold corpus missing")
    elif recall is not None and recall < 0.85:
        failures.add("action recall")
    if precision is not None and precision < 0.90:
        failures.add("action precision")
    false_rate = false_caught / false_total if false_total else None
    if false_rate is None:
        pending.add("planted false coverage missing")
    elif false_rate < 0.90:
        failures.add("planted false detection")
    state = "pending" if pending else "fail" if failures else "pass"
    return {
        "mechanics": state,
        "provider_quality": "pending" if basis != "recorded_provider" else state,
        "case_count": len(cases),
        "metrics": {
            "action_recall": recall,
            "action_precision": precision,
            "schema_valid_rate": valid / len(cases) if cases else None,
            "planted_false_detection": false_rate,
        },
        "failures": sorted(failures),
        "pending": sorted(pending),
    }


def evaluate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Provider labels are independently reviewed input assertions, never inferred from fixtures."""
    if not isinstance(cases, list) or any(not isinstance(c, dict) or c.get("basis") not in BASES for c in cases):
        return {
            "mechanics": "pending",
            "provider_quality": "pending",
            "metrics": {},
            "pending": ["invalid case list or basis"],
            "by_basis": {},
        }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case["basis"]].append(case)
    reports = {basis: _group(rows, basis) for basis, rows in grouped.items()}
    if len(reports) == 1:
        return {**next(iter(reports.values())), "by_basis": reports}
    return {
        "mechanics": "pending",
        "provider_quality": "pending",
        "metrics": {},
        "by_basis": reports,
        "pending": ["bases cannot be pooled" if reports else "no cases"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    try:
        if args.bundle.stat().st_size > 20_000_000:
            raise ValueError("bundle too large")
        report = evaluate(json.loads(args.bundle.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"provider_quality": "pending", "pending": ["bundle unreadable or malformed"]}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return {"pass": 0, "fail": 1, "pending": 2}[report["provider_quality"]]


if __name__ == "__main__":
    raise SystemExit(main())
