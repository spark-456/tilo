"""RT-01, RT-06, RT-07, RT-10: the indexer hooks run after a committed write, only when TILO_RETRIEVAL=1, and never
change the answer of the request that triggered them. Fakes only; no network (EFF-01)."""

from __future__ import annotations

import pytest
from _ppl11a_lib import PRIYA, SAM
from _rt_lib import WordEmbedder
from tilo_api import grounding
from tilo_api.grounding import ApiSourceRules, Grounding
from tilo_memory.chunks import ChunkConfig, ChunkStore
from tilo_memory.chunks_backends import MemoryChunkBackend


def _wire(rig, monkeypatch, *, enabled: bool = True) -> tuple[Grounding, WordEmbedder]:
    embedder = WordEmbedder()
    rules = ApiSourceRules(rig.real, rig.event_store, rig.artifacts)
    store = ChunkStore(MemoryChunkBackend(), embedder, rules, config=ChunkConfig())
    opened = Grounding(store, rig.org, rig.real, rig.event_store, rig.artifacts)
    monkeypatch.setattr(grounding, "opener", lambda request, **kw: lambda: opened)
    if enabled:
        monkeypatch.setenv("TILO_RETRIEVAL", "1")
    else:
        monkeypatch.delenv("TILO_RETRIEVAL", raising=False)
    return opened, embedder


def _pin(rig, title="Quarterly offsite agenda", body="book the venue and the travel"):
    return rig.post("/v1/pinboards", {"title": title, "body": body})


def test_RT_01_a_created_pin_is_indexed_for_its_owner_and_removing_it_deletes_the_chunks(people_rig, monkeypatch):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    opened, _ = _wire(rig, monkeypatch)
    made = _pin(rig)
    assert made.status_code == 201
    hits = opened.store.search(rig.org, PRIYA, "offsite agenda venue")
    assert [h.source["id"] for h in hits] == [made.json()["id"]] and "venue" in hits[0].text
    assert opened.store.search(rig.org, SAM, "offsite agenda venue") == []  # another person's: no chunks, no hit
    assert rig.post(f"/v1/pinboards/{made.json()['id']}/delete", {}).status_code == 200
    assert opened.store.search(rig.org, PRIYA, "offsite agenda venue") == []  # RT-07: gone with the pin


def test_RT_10_the_hooks_do_nothing_unless_retrieval_is_switched_on(people_rig, monkeypatch):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    opened, embedder = _wire(rig, monkeypatch, enabled=False)
    assert _pin(rig).status_code == 201
    assert embedder.calls == [] and list(opened.store._backend.scan(rig.org)) == []


def test_RT_06_an_embedding_failure_never_changes_the_write_that_triggered_it(people_rig, monkeypatch):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    opened, embedder = _wire(rig, monkeypatch)
    embedder.fail = True
    made = _pin(rig)
    assert made.status_code == 201 and made.json()["title"] == "Quarterly offsite agenda"
    assert list(opened.store._backend.scan(rig.org)) == []  # nothing half-stored; the next change indexes it
    embedder.fail = False
    assert rig.post(f"/v1/pinboards/{made.json()['id']}/delete", {}).status_code == 200


def test_RT_10_a_hook_that_cannot_open_grounding_is_skipped(people_rig, monkeypatch):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    monkeypatch.setenv("TILO_RETRIEVAL", "1")
    monkeypatch.setattr(grounding, "opener", lambda request, **kw: lambda: None)
    assert _pin(rig).status_code == 201


def test_RT_10_grounding_is_off_by_default_and_opens_only_with_the_switch(monkeypatch):
    monkeypatch.delenv("TILO_RETRIEVAL", raising=False)
    assert grounding.enabled() is False
    monkeypatch.setenv("TILO_RETRIEVAL", "true")
    assert grounding.enabled() is False  # exactly "1"
    monkeypatch.setenv("TILO_RETRIEVAL", "1")
    assert grounding.enabled() is True


def test_RT_01_a_flagged_pin_is_not_indexed_and_loses_what_it_had(people_rig, monkeypatch):
    rig = people_rig()
    rig.add_people()
    rig.as_user(PRIYA)
    opened, _ = _wire(rig, monkeypatch)
    pin = _pin(rig).json()
    assert len(list(opened.store._backend.scan(rig.org))) == 1
    opened.index_pin(pin | {"flagged": True})
    assert list(opened.store._backend.scan(rig.org)) == []


def test_RT_01_RT_02_confirmed_minutes_are_the_owners_alone_and_unconfirmed_ones_are_not_indexed(
    people_rig, monkeypatch
):
    import copy

    from _mtg09b_lib import block_network
    from _ppl11a_lib import OWNER
    from _ppl11c_lib import meeting_rig, transcript_case
    from tilo_api.deps import WorldRecord
    from tilo_api.meeting_minutes import publish_minutes
    from tilo_api.people_writes import Writer, confirm_minutes

    block_network(monkeypatch)
    rig = meeting_rig(people_rig)
    before = rig.stored("meetings", "mt_q4_plan")
    ended = {**before, "status": "ended", "minutes": None, "minutes_confirmed_by": None, "delete_minutes_after": None}
    rig.real.meetings.replace(ended, expected_version=1)
    rig.event_store.worlds[ended["world_id"]] = WorldRecord(OWNER, {}, run_id="r_meeting_q4_plan_1")
    rig._ids = ["art_publication_minutes"]
    doc = copy.deepcopy(transcript_case("owner_reads_quotes")["minutes"])
    for row in doc["action_items"]:
        row["work_item_id"] = None
    writer = Writer(rig.stores, rig.org, OWNER, rig.clock, rig.redactor)
    publish_minutes(writer, rig.event_store, rig.artifacts, "mt_q4_plan", doc, events=rig.events)
    opened, _ = _wire(rig, monkeypatch)
    opened.index_minutes("mt_q4_plan")
    assert list(opened.store._backend.scan(rig.org)) == []  # not confirmed yet: nothing is indexed (RT-01)
    confirm_minutes(Writer(rig.stores, rig.org, OWNER, rig.clock, rig.redactor), "mt_q4_plan")
    opened.index_minutes("mt_q4_plan")
    held = list(opened.store._backend.scan(rig.org))
    assert held and {d["source"]["kind"] for d in held} == {"minutes"} and all(d["team_id"] is None for d in held)
    words = " ".join(doc["decisions"][0]["text"].split()[:4])
    assert opened.store.search(rig.org, OWNER, words)  # the owner finds their own minutes
    assert opened.store.search(rig.org, SAM, words) == []  # nobody else, whatever team (PE-05)


def test_RT_05_RT_06_the_embedder_goes_through_the_router_and_a_metered_router_counts_each_call(monkeypatch):
    from pathlib import Path

    from tilo_api.spend_units import MeteredRouter
    from tilo_providers.config import load_providers_config
    from tilo_providers.router import Router

    monkeypatch.delenv("LIVE", raising=False)
    root = Path(__file__).resolve().parents[3]
    raw = Router(load_providers_config(root / "config/models.dev.yaml", root / "config/prices.yaml"), fixtures_dir=root)
    metered: list[str] = []

    class Meter:
        def call(self, fn, minor, failed, **kw):
            metered.append("unit")
            return fn()

        def router_minor(self, attempts):
            return 1

        def router_usage(self, attempts):
            return None

    assert not hasattr(MeteredRouter(raw, Meter()), "embed")  # SEC-16's pinned rule: only `metered_embed` exists
    embedder = grounding.RouterEmbedder(MeteredRouter(raw, Meter()), "embed-fake", 64, 2)
    vectors = embedder.embed(["one", "two", "three"], "document")  # batch_max 2: two router calls, two units
    assert len(vectors) == 3 and all(len(v) == 64 for v in vectors) and metered == ["unit", "unit"]
    wrong = grounding.RouterEmbedder(raw, "embed-google", 64, 2)  # vectors of another profile are never mixed
    with pytest.raises(Exception, match="another profile"):
        wrong.embed(["x"], "query")


def test_RT_09_run_end_writes_one_memory_saved_and_a_failing_grounding_never_ends_the_run():
    from types import SimpleNamespace

    from tilo_api.runs import Run

    written: list[tuple] = []
    run = SimpleNamespace(director="A_dir", world_id="w_x", run_id="r_x", put=lambda *a, **kw: written.append((a, kw)))
    run.seams = SimpleNamespace(grounding=lambda: SimpleNamespace(index_deliverables=lambda world: 3))
    Run._remember_deliverables(run)
    ((args, kwargs),) = written
    assert args[0] == "memory.saved" and args[4] == {"layer": "artifact_memory", "item_count": 3}
    assert kwargs["vis"] == []  # the owner's alone (HR-1: recorded, never widened)
    written.clear()
    run.seams = SimpleNamespace(grounding=lambda: SimpleNamespace(index_deliverables=lambda world: 0))
    Run._remember_deliverables(run)
    run.seams = SimpleNamespace(grounding=None)
    Run._remember_deliverables(run)
    assert written == []
    run.seams = SimpleNamespace(grounding=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    Run._remember_deliverables(run)  # a failure is logged by type, the run goes on to world.completed
    assert written == []


def test_RT_07_the_daily_sweep_runs_once_a_day_and_only_when_retrieval_is_on(monkeypatch):
    from types import SimpleNamespace

    swept: list[int] = []
    opened = SimpleNamespace(sweep=lambda: swept.append(1))
    monkeypatch.setattr(grounding, "opener", lambda request, **kw: lambda: opened)
    monkeypatch.setattr(grounding, "_swept_day", "")
    monkeypatch.delenv("TILO_RETRIEVAL", raising=False)
    grounding.sweep_daily(object(), "2026-10-16T09:00:00.000Z")
    assert swept == []
    monkeypatch.setenv("TILO_RETRIEVAL", "1")
    grounding.sweep_daily(object(), "2026-10-16T09:00:00.000Z")
    grounding.sweep_daily(object(), "2026-10-16T23:00:00.000Z")  # the same day
    grounding.sweep_daily(object(), "2026-10-17T00:01:00.000Z")
    assert swept == [1, 1]
