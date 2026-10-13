"""Internal FR-MTG-03/04 analyst: grounded minutes for review, without record writes or confirmation."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from tilo_contracts import Minutes, Transcript
from tilo_people.dates import resolve_due
from tilo_people.directory import Directory
from tilo_people.names import match_name
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import GenerateRequest, SafetyProvider
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.router import Router


def _call(router: Router, role: str, data: dict, budget: float, schema: dict | None = None) -> tuple[Any, float]:
    result = router.generate(
        role,
        GenerateRequest(
            system=load_prompt("meeting_analyst", f"{role}.md"),
            prompt="<<<DATA\n" + neutralise_marker(json.dumps(data), "DATA") + "\nDATA>>>",
            json_mode=True,
            response_schema=schema,
        ),
        budget=budget,
    )
    if getattr(result, "outcome", "ok") != "ok" or result.response is None:
        raise ValueError("analysis_failed")
    left = result.budget
    if not isinstance(left, (int, float)) or isinstance(left, bool) or not math.isfinite(left):
        left = 0.0
    return json.loads(result.response.text or ""), max(0.0, min(budget, left))


def analyze_minutes(
    router: Router,
    transcript: dict[str, Any],
    transcript_ref: dict[str, Any],
    *,
    directory: Directory,
    viewer: str,
    meeting_at: str,
    now: str,
    budget: float,
    safety: SafetyProvider,
) -> dict[str, Any]:
    """Caller supplies an authorised pinned transcript, directory and stored meeting start; never a client body.

    Router retains replay/spend/redaction controls. No item is created or confirmed here. An unknown assignment
    remains unresolved. Verifier outages keep failed checks visible as unverified, never silently remove a claim.
    """
    try:
        if not math.isfinite(budget) or budget <= 0 or not conforms("transcript.schema.json", transcript):
            raise ValueError
        Transcript.model_validate(transcript)
        ids = [int(u["id"][1:]) for u in transcript["utterances"]]
        if any(b <= a for a, b in zip(ids, ids[1:])):
            raise ValueError  # generated types do not enforce the PE-22 ordering rule
        if directory.get(viewer) is None:
            raise ValueError
        screen = safety.check(json.dumps(transcript))
        if not isinstance(screen, dict) or screen.get("flagged") is not False:
            raise ValueError
        metadata = dict(meeting_id=transcript["meeting_id"], transcript=transcript_ref, generated_at=now, flagged=False)
        empty = {**metadata, "summary": [], "decisions": [], "action_items": [], "agenda": []}
        if not conforms("minutes.schema.json", empty):
            raise ValueError
        doc, left = _call(
            router,
            "meeting_analyst",
            {"transcript": transcript, "metadata": metadata},
            budget,
            Minutes.model_json_schema(),
        )
        if not isinstance(doc, dict):
            raise ValueError
        doc.update(metadata)
        # Erase model identity, dates, links and verification stamps before schema validation or use.
        for row in doc.get("action_items", []):
            row.update(owner=None, due=None, work_item_id=None, state="unverified")
        for row in doc.get("decisions", []):
            row["state"] = "unverified"
        if not conforms("minutes.schema.json", doc):
            raise ValueError
        utterances = {u["id"]: u for u in transcript["utterances"]}
        for group in ("summary", "agenda"):
            if any(not set(row["evidence"]) <= utterances.keys() for row in doc[group]):
                raise ValueError
        pending, checks = [], []
        for row in doc["summary"]:
            spans = [utterances[i] for i in row["evidence"]]
            if not spans:
                raise ValueError
            if not any(row["text"] == u["text"] for u in spans):
                pending.append(row)
                checks.append({"claim": {"text": row["text"]}, "spans": spans})
        for row in doc["decisions"] + doc["action_items"]:
            evidence = row["evidence"]
            if not evidence or not set(evidence) <= utterances.keys():
                row["evidence"] = []
                continue
            spans = [utterances[i] for i in evidence]
            if "owner_text" in row:
                # Literal phrases must be spoken in these spans, even if the verifier accepts the task text.
                if any(
                    row[k] is not None
                    and not any(re.search(r"(?<!\w)" + re.escape(row[k]) + r"(?!\w)", u["text"]) for u in spans)
                    for k in ("owner_text", "due_text")
                ):
                    continue
                owner = match_name(row["owner_text"], directory, viewer=viewer, now=now).user
                person = directory.get(owner) if owner else None
                row["owner"] = owner
                if person:
                    row["due"] = resolve_due(row["due_text"], meeting_at=meeting_at, time_zone=person["time_zone"]).due
            if any(
                row["text"] == u["text"]
                and all(row.get(k) is None or row[k] in u["text"] for k in ("owner_text", "due_text"))
                for u in spans
            ):
                row["state"] = "verified"
            else:
                pending.append(row)
                checks.append(
                    {"claim": {k: row[k] for k in ("text", "owner_text", "due_text") if k in row}, "spans": spans}
                )
        if pending and left > 0:
            try:
                verdict, _ = _call(router, "verifier", {"checks": checks}, left)
                supported = verdict["supported"]
                if set(verdict) != {"supported"} or not isinstance(supported, list) or len(supported) != len(pending):
                    raise ValueError
                if not all(type(value) is bool for value in supported):
                    raise ValueError
                for row, good in zip(pending, supported, strict=True):
                    row["state"] = "verified" if good else "unverified"
            except Exception:
                pass  # no verdict is no verification
        for row in doc["summary"]:
            if row in pending and row.pop("state", "unverified") != "verified":
                raise ValueError  # summary has no unverified representation; refuse unsupported prose
        if not conforms("minutes.schema.json", doc):
            raise ValueError
        return doc
    except Exception:
        raise ValueError("analysis_failed") from None
