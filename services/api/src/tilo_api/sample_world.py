"""STARTER-1 (BQ-STARTER-1): the default sample project, so a new account is never empty.

One read-only world, `w_sample_village_basic`, served from the recorded stream and layout the web fixture mode plays
(`contracts/fixtures/streams/village-basic.jsonl`, `.../layout/valid/village_basic.json`), shipped as package data in
`sample_data/` (a repo test pins the copies byte-identical to the originals). Nothing is recorded or invented here and
no model is called (HR-1..HR-7: every event shown was recorded); the only change is the world id, so the replay
names the sample, not the world it was recorded in.

It holds no user data, so any signed-in principal may read it. It is answered by routes registered before the
owner-scoped ones, so no store lookup, outbox, writer or meter is reached; every write under its path is
409 `sample_is_a_replay`, and no real world may take its id (`refuse_reserved`, called by both stores' commit).
Fail closed: files that cannot be read or do not parse leave the sample absent, with one log line saying why.
"""

from __future__ import annotations

import copy
import functools
import importlib.resources
import json
import logging
from dataclasses import dataclass
from importlib.resources.abc import Traversable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from tilo_api.deps import SAMPLE_WORLD_ID, Principal, get_current_principal, refuse_reserved

__all__ = ["SAMPLE_WORLD_ID", "refuse_reserved", "load", "router"]
logger = logging.getLogger(__name__)

SAMPLE_TITLE_PREFIX = "Sample: "
_RECORDED_WORLD_ID = "w_village_basic"
_EVENTS_FILE, _LAYOUT_FILE = "village-basic.jsonl", "village_basic.json"

router = APIRouter()


@dataclass(frozen=True)
class Sample:
    events: tuple[dict, ...]  # as recorded, world id aside; strictly increasing seq
    layout: dict


def _data_dir() -> Traversable:
    return importlib.resources.files("tilo_api") / "sample_data"


def _rename(value: Any) -> Any:
    return SAMPLE_WORLD_ID if value == _RECORDED_WORLD_ID else value


def _parse(data: Traversable) -> Sample:
    events = [
        json.loads(line) for line in (data / _EVENTS_FILE).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    layout = json.loads((data / _LAYOUT_FILE).read_text(encoding="utf-8"))
    if not events or not all(isinstance(e, dict) for e in events) or not isinstance(layout, dict):
        raise ValueError("unexpected shape")
    first = events[0]
    seqs = [e["seq"] for e in events]
    if first["type"] != "world.requested" or seqs != sorted(set(seqs)):
        raise ValueError("unexpected shape")
    if not isinstance(first["data"]["title"], str) or not isinstance(first["ts"], str):
        raise ValueError("unexpected shape")
    renamed = [{**e, "world_id": _rename(e["world_id"]), "target": _rename(e["target"])} for e in events]
    return Sample(events=tuple(renamed), layout={**layout, "world_id": _rename(layout.get("world_id"))})


@functools.lru_cache(maxsize=1)
def load() -> Sample | None:
    """The sample, or None (cached, so the one log line is written once) when its files cannot be used."""
    try:
        return _parse(_data_dir())
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("sample project not available, left out (%s)", type(exc).__name__)
        return None


def _read(principal: Principal = Depends(get_current_principal)) -> Sample:
    """Any signed-in principal (it holds no user data); absent files are an unknown world."""
    sample = load()
    if sample is None:
        raise HTTPException(status_code=404, detail="Tilo could not find that.")
    return sample


@router.get(f"/worlds/{SAMPLE_WORLD_ID}/events")
def sample_events(sample: Sample = Depends(_read)) -> JSONResponse:
    return JSONResponse(content={"events": copy.deepcopy(list(sample.events))})


@router.get(f"/worlds/{SAMPLE_WORLD_ID}/layout")
def sample_layout(sample: Sample = Depends(_read)) -> JSONResponse:
    return JSONResponse(content=copy.deepcopy(sample.layout))


@router.get(f"/worlds/{SAMPLE_WORLD_ID}/cards")
def sample_cards(sample: Sample = Depends(_read)) -> JSONResponse:
    return JSONResponse(content=[])  # the recorded stream's one approval is already resolved in it


@router.get(f"/worlds/{SAMPLE_WORLD_ID}/delivery")
def sample_delivery(sample: Sample = Depends(_read)) -> JSONResponse:
    """The recorded run delivered nothing a person can open (no artifact exists behind it): no artifacts, the
    credits its `world.completed` recorded, no time saved claimed."""
    done: Any = next((e["data"] for e in sample.events if e["type"] == "world.completed"), {})
    credits = done.get("credits_used") if isinstance(done, dict) else None
    return JSONResponse(
        content={
            "world_id": SAMPLE_WORLD_ID,
            "artifacts": [],
            "credits_used": credits if isinstance(credits, (int, float)) else 0,
            "time_saved": None,
        }
    )


@router.api_route(
    f"/worlds/{SAMPLE_WORLD_ID}/{{rest:path}}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False
)
@router.api_route(f"/worlds/{SAMPLE_WORLD_ID}", methods=["POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def sample_is_a_replay(principal: Principal = Depends(get_current_principal)) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "sample_is_a_replay"})
