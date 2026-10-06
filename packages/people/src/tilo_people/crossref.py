"""Adapter from the crossref fixtures (contracts/fixtures/person/crossref/{valid,invalid}/*.json) to `decide`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .access import AccessRequest, Verdict, decide
from .directory import Directory
from .errors import PeopleInputError


def _bad() -> PeopleInputError:
    return PeopleInputError("malformed crossref case")  # fixed text: never the case's own values


def case_request(case: Mapping[str, Any]) -> tuple[AccessRequest, Directory]:
    """One crossref case as a request and its directory: actor = `request.actor`; action = "read_" + view when
    `request.action` is "read", else `request.action`; kind, record, meeting, work_item, source_owner and pin
    from `record`; `mentions` as a tuple; the directory holds the persons whose key is their own id. Raises
    PeopleInputError on a case missing a key."""
    try:
        request, record, persons = case["request"], case["record"], case["persons"]
        action = request["action"]
        if action == "read":
            view = request.get("view")
            if not isinstance(view, str):
                raise _bad()
            action = "read_" + view
        extra = {key: record.get(key) for key in ("meeting", "work_item", "source_owner", "pin")}
        built = AccessRequest(
            actor=request["actor"],
            action=action,
            record_kind=record["kind"],
            record=record["data"],
            now=case["now"],
            mentions=tuple(record.get("mentions", ())),
            **extra,
        )
        directory = Directory.of(p for key, p in persons.items() if isinstance(p, Mapping) and p.get("id") == key)
    except PeopleInputError:
        raise
    except Exception:
        raise _bad() from None
    return built, directory


def verdict_for_case(case: Mapping[str, Any]) -> Verdict:
    """`decide(*case_request(case))`; a malformed case is a refusal, never an exception."""
    try:
        return decide(*case_request(case))
    except Exception:
        return Verdict(False, None)
