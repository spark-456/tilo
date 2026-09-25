"""Runs the P0-09 three-agent fixture plan (Director, one Lead, one Specialist; FR-AGT-01
partial, D-11, PRD 8.1, 15.3) through the single `WorldWriter`, no model calls, and returns the
events it wrote (ticket brief item 2). `python -m tilo_harness.skeleton` is the CLI (item 10):
it reuses or starts the Firestore emulator, runs the skeleton against a real `FirestoreStore`
and prints one JSON line.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from tilo_harness.writer import WorldWriter

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures/three_agent"
LEVEL, DISTRICT = "L1", "D1"
DIRECTOR_ID, LEAD_ID, SPECIALIST_ID = "A_dir", "A_lead", "A_spec"
BUILDING_ID, UNIT_ID, ARTIFACT_ID = "B1", "U1", "art_triage_list"


def _load_layout() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "layout.json").read_text(encoding="utf-8"))


async def _run_plan(writer: WorldWriter, step_delay: float) -> None:
    # Imported lazily: google-adk's import chain is heavy (~seconds), and `world.requested`
    # (ticket brief item 4's "kill mid-run" case) must already be written before that cost is
    # paid, so a kill just after process start still leaves a valid, non-empty prefix.
    from google.adk.agents.invocation_context import InvocationContext
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    from tilo_harness.agents import DirectorAgent, LeadAgent, SpecialistAgent

    specialist = SpecialistAgent(
        name="specialist",
        writer=writer,
        agent_id=SPECIALIST_ID,
        unit_id=UNIT_ID,
        level=LEVEL,
        district=DISTRICT,
        step_delay=step_delay,
        building_id=BUILDING_ID,
        artifact_id=ARTIFACT_ID,
    )
    lead = LeadAgent(
        name="lead",
        writer=writer,
        agent_id=LEAD_ID,
        unit_id=UNIT_ID,
        level=LEVEL,
        district=DISTRICT,
        step_delay=step_delay,
        specialist_id=SPECIALIST_ID,
        sub_agents=[specialist],
    )
    director = DirectorAgent(
        name="director",
        writer=writer,
        agent_id=DIRECTOR_ID,
        unit_id=UNIT_ID,
        level=LEVEL,
        district=DISTRICT,
        step_delay=step_delay,
        lead_id=LEAD_ID,
        sub_agents=[lead],
    )
    session_service = InMemorySessionService()
    session = await session_service.create_session(app_name="tilo_harness_skeleton", user_id="u_system")
    ctx = InvocationContext(
        session_service=session_service,
        invocation_id=str(uuid.uuid4()),
        session=session,
        agent=director,
    )
    async for _event in director.run_async(ctx):
        pass


def _run(
    store: Any,
    *,
    org_id: str,
    world_id: str,
    run_id: str,
    clock: Any = None,
    step_delay: float = 0.0,
    lease_s: float = 30.0,
) -> list[dict[str, Any]]:
    layout = _load_layout()
    kwargs: dict[str, Any] = {
        "org_id": org_id,
        "world_id": world_id,
        "run_id": run_id,
        "layout": layout,
        "writer_id": f"skeleton_{run_id}",
        "lease_s": lease_s,
    }
    if clock is not None:
        kwargs["clock"] = clock
    writer = WorldWriter(store, **kwargs)
    writer.open()
    writer.emit(
        type="world.requested",
        actor="u_owner",
        target=world_id,
        summary="You asked Tilo to do some work.",
        data={"title": "Run the P0-09 fixture plan", "channel": "web", "destination": None},
    )
    asyncio.run(_run_plan(writer, step_delay))
    writer.emit(
        type="world.completed",
        actor=DIRECTOR_ID,
        target=world_id,
        summary="The fixture plan finished.",
        data={"credits_used": 0, "deliverable_count": 1},
    )
    writer.close()
    return store.read_events(org_id, world_id)


def run_skeleton(
    store: Any,
    *,
    org_id: str = "org_demo",
    world_id: str,
    run_id: str,
    clock: Any = None,
    step_delay: float = 0.0,
) -> list[dict[str, Any]]:
    """Runs the fixture plan and returns the events written, in seq order."""
    return _run(store, org_id=org_id, world_id=world_id, run_id=run_id, clock=clock, step_delay=step_delay)


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Run the P0-09 harness skeleton against Firestore.")
    parser.add_argument("--org", default="org_demo")
    parser.add_argument("--world", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--lease-s", type=float, default=30.0)
    parser.add_argument("--step-delay", type=float, default=0.0)
    args = parser.parse_args()

    from tilo_harness.emulator import running_emulator
    from tilo_harness.store import FirestoreStore

    with running_emulator():
        store = FirestoreStore()
        events = _run(
            store,
            org_id=args.org,
            world_id=args.world,
            run_id=args.run,
            step_delay=args.step_delay,
            lease_s=args.lease_s,
        )
    last_seq = events[-1]["seq"] if events else 0
    print(json.dumps({"written": len(events), "world_id": args.world, "last_seq": last_seq}))
    sys.exit(0)


if __name__ == "__main__":
    _cli()
