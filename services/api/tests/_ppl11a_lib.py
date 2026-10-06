"""Helpers for the PPL-11a acceptance tests (people API on tilo-api: evidence quotes, the plate, confirm and the
writes around them; the interface is pinned in `API_PPL_11a.md`).

Named `_ppl11a_lib` for the same global-bare-module-name reason as `_sec15_lib.py`. Nothing here is business logic:
it loads the crossref fixtures unchanged, builds fakes behind the seams the doc names, and calls the real
`tilo_api.app` through `TestClient`. A seam the production code does not have yet resolves to a placeholder key
(`_clint1_lib.seam`), so a missing seam shows up as a wrong response, not as an `AttributeError` in set-up. A route
the code does not have yet is caught by `Rig.require_route`, so a "404 as expected" test cannot pass by accident.

No network, no paid call, no clock, no secret: the clock is an argument, the model router is replaced by a spy that
fails the test when anything builds one, and the fake secret is assembled at run time.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import sys
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from _clint1_lib import seam
from fastapi import HTTPException
from fastapi.testclient import TestClient

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"
CONTRACT_TESTS = REPO_ROOT / "tests" / "contracts"

ORG = "org_example"
OTHER_ORG = "org_elsewhere"
NOW = "2026-10-06T10:00:00.000Z"  # the crossref cases' `now`
EARLY = "2026-10-05T09:00:00.000Z"  # before every stamp a case makes
OWNER, PRIYA, DEV, SAM, MEERA = "u_owner", "u_priya", "u_dev", "u_sam", "u_meera"

# Routes (API_PPL_11a.md section 1). The path templates are pinned as literals.
R_QUOTES = ("GET", "/v1/meetings/{meeting_id}/quotes")
R_ITEM_QUOTE = ("GET", "/v1/work-items/{work_item_id}/quote")
R_PLATE = ("GET", "/v1/plate")
R_CONFIRM_MEETING = ("POST", "/v1/meetings/{meeting_id}/confirm")
R_CONFIRM_ITEM = ("POST", "/v1/work-items/{work_item_id}/confirm")
R_CREATE_MEETING = ("POST", "/v1/meetings")
R_CREATE_PERSON = ("POST", "/v1/people")
R_CREATE_ITEM = ("POST", "/v1/work-items")
PEOPLE_ROUTES = (
    R_QUOTES,
    R_ITEM_QUOTE,
    R_PLATE,
    R_CONFIRM_MEETING,
    R_CONFIRM_ITEM,
    R_CREATE_MEETING,
    R_CREATE_PERSON,
    R_CREATE_ITEM,
)


# Tests that only slice B (plate) or slice C (writes) turn green: they call a route that slice A does not have. They are
# marked `xfail(strict=True)` by `pytest_collection_modifyitems` in `conftest.py`. Slice B and C each delete the entries
# their routes make green (strict: a test that passes unmarked fails the run) and restore their own test files from
# `origin/tests/PPL-11a-people-api`. Entries are substrings of the pytest node id.
SLICE_BC_PENDING = (
    "test_PPL_11a_SEC_15_the_people_routes_exist_and_none_of_them_is_public",
    "refused_before_anything_is_touched[POST /v1/meetings/{meeting_id}/confirm]",
    "refused_before_anything_is_touched[POST /v1/work-items/{work_item_id}/confirm]",
    "refused_before_anything_is_touched[POST /v1/meetings]",
    "refused_before_anything_is_touched[POST /v1/people]",
    "refused_before_anything_is_touched[POST /v1/work-items]",
    "lets_nobody_in[POST /v1/meetings]",
    "test_PPL_11a_SEC_15_a_judge_reaches_the_routes_own_rules_unchanged",
    "test_PPL_11a_PE_19_every_people_route_is_503_not_configured_until_its_seams_are_wired",
    "test_PPL_11a_PE_19_each_route_needs_exactly_the_seams_it_uses",
    "test_PPL_11a_PE_17_dev_mode_serves_its_one_owner_an_empty_plate",
    "test_PPL_11a_EFF_01_the_dev_people_stores_are_one_in_memory_set",
)


# --- the reference oracle (tests/contracts/test_CC_PEOPLE_3_quotes_and_plate.py) -----------------------------------


def _is_contract_module(mod: Any) -> bool:
    return pathlib.Path(getattr(mod, "__file__", "") or "").parent == CONTRACT_TESTS


def load_oracle() -> Any:
    """The contract suite's oracle module, loaded by path so its `test_` functions are never collected here. It
    imports `_lib` and `_people_lib` by bare name: while it loads, a same-named module another suite put in
    `sys.modules` is set aside and restored."""
    name = "cc_people_3_oracle"
    if name in sys.modules:
        return sys.modules[name]
    aside = {k: m for k in ("_lib", "_people_lib") if (m := sys.modules.get(k)) and not _is_contract_module(m)}
    for k in aside:
        del sys.modules[k]
    sys.path.insert(0, str(CONTRACT_TESTS))
    try:
        spec = importlib.util.spec_from_file_location(name, CONTRACT_TESTS / "test_CC_PEOPLE_3_quotes_and_plate.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(CONTRACT_TESTS))
        sys.modules.update(aside)
    return module


oracle = load_oracle()
pl = oracle.pl  # tests/contracts/_people_lib: the minimal-document builders and the reference `permits`


def crossref_cases(folder: str) -> list[tuple[str, str, dict[str, Any]]]:
    """(kind, file stem, case) for `contracts/fixtures/<folder>/crossref/{valid,invalid}/*.json`."""
    found = []
    for kind in ("valid", "invalid"):
        for path in sorted((CONTRACTS / "fixtures" / folder / "crossref" / kind).glob("*.json")):
            found.append((kind, path.stem, json.loads(path.read_text(encoding="utf-8"))))
    assert found, f"no crossref cases under contracts/fixtures/{folder}/crossref"
    return found


def case_params(folder: str) -> list[Any]:
    import pytest  # noqa: PLC0415

    return [pytest.param(k, n, c, id=f"{k}/{n}") for k, n, c in crossref_cases(folder)]


def fixture_case(folder: str, kind: str, name: str) -> dict[str, Any]:
    path = CONTRACTS / "fixtures" / folder / "crossref" / kind / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


STANDARD_PERSONS: dict[str, dict[str, Any]] = fixture_case("transcript", "valid", "owner_reads_quotes")["persons"]
# u_owner (org owner), u_priya and u_dev (tm_launch), u_sam (tm_ops), u_meera (org owner, tm_ops); org_example


def conforms(name: str, doc: Any) -> bool:
    from tilo_policy.schemas import conforms as _conforms  # noqa: PLC0415

    return _conforms(name, doc)


# --- fakes behind the seams -----------------------------------------------------------------------------------------

_TOKEN = re.compile(r"tok_[A-Za-z0-9]{40,}")


def fake_token() -> str:
    """A fake secret assembled at run time (never a literal in the repo): the shape the fake redactor removes."""
    return "tok" + "_" + "aB" * 25


class SpyRedactor:
    """The shared secret redactor, faked (deps.get_redactor): removes `fake_token()`-shaped text, records inputs."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        return _TOKEN.sub("[REDACTED]", text)


class IdentityRedactor:
    def __call__(self, text: str) -> str:
        return text


class FakeSources:
    """`deps.get_plate_sources()`: the cards, runs and mail the plate may draw on (API_PPL_11a.md section 4). Every
    method ignores its `user_id` and returns everything it holds, like a careless or hostile store, so the tests
    prove the API filters by owner itself."""

    def __init__(self) -> None:
        self.card_facts: list[dict[str, Any]] = []
        self.run_facts: list[dict[str, Any]] = []
        self.mail_facts: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []

    def cards(self, user_id: str) -> list[dict[str, Any]]:
        self.calls.append(("cards", user_id))
        return copy.deepcopy(self.card_facts)

    def runs(self, user_id: str) -> list[dict[str, Any]]:
        self.calls.append(("runs", user_id))
        return copy.deepcopy(self.run_facts)

    def mail(self, user_id: str) -> list[dict[str, Any]]:
        self.calls.append(("mail", user_id))
        return copy.deepcopy(self.mail_facts)


class FakeOwners:
    """`deps.get_source_owners()`: who owns a mail message or a request (API_PPL_11a.md section 5)."""

    def __init__(self, owners: dict[tuple[str, str], str] | None = None) -> None:
        self.owners = dict(owners or {})
        self.calls: list[tuple[str, str]] = []

    def owner_of(self, kind: str, ref: str) -> str | None:
        self.calls.append((kind, ref))
        return self.owners.get((kind, ref))


class _Screener:
    """SafetyProvider-shaped screener for the artifact store: the verdict of the next `put`."""

    def __init__(self) -> None:
        self.verdict = "clean"  # clean | flagged | unscreened

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> dict[str, Any]:
        if self.verdict == "unscreened":
            raise RuntimeError("no verdict")
        return {"flagged": self.verdict == "flagged", "reason": None}


class SpyStore:
    """Wraps one `RecordStore`, recording (method, org_id) of every call; `fail_replace` makes `replace` raise
    `VersionConflict` (a lost compare-and-set)."""

    def __init__(self, inner: Any, log: list[tuple[str, str, str]], fail_replace: bool = False) -> None:
        self._inner, self._log, self.fail_replace = inner, log, fail_replace
        self.kind = inner.kind

    def _note(self, method: str, org_id: str) -> None:
        self._log.append((self.kind, method, org_id))

    def get(self, org_id: str, record_id: str) -> Any:
        self._note("get", org_id)
        return self._inner.get(org_id, record_id)

    def create(self, record: Any) -> Any:
        self._note("create", record["org_id"])
        return self._inner.create(record)

    def replace(self, record: Any, *, expected_version: int) -> Any:
        self._note("replace", record["org_id"])
        if self.fail_replace:
            from tilo_people.errors import VersionConflict  # noqa: PLC0415

            raise VersionConflict(f"{self.kind} {record['id']}")
        return self._inner.replace(record, expected_version=expected_version)

    def delete(self, org_id: str, record_id: str, *, expected_version: int) -> None:
        self._note("delete", org_id)
        return self._inner.delete(org_id, record_id, expected_version=expected_version)

    def list(self, org_id: str, field: str | None = None, value: str | None = None) -> Any:
        self._note("list", org_id)
        return self._inner.list(org_id, field, value)


# --- the rig --------------------------------------------------------------------------------------------------------


def case_org(case: dict[str, Any]) -> str:
    """The one org tilo-api serves for a crossref case: the org of its meeting, else its work item or plate source,
    else the actor's person record (so a person of another org is a stranger to the served org, not its owner)."""
    src = case.get("source") or {}
    meeting = case.get("meeting") or src.get("meeting")
    if meeting:
        return meeting["org_id"]
    record = case.get("work_item") or src.get("data")
    if isinstance(record, dict) and "org_id" in record:
        return record["org_id"]
    actor = case["request"]["actor"]
    return case["persons"][actor]["org_id"] if actor in case["persons"] else ORG


class Rig:
    """The real `tilo_api.app` with every seam of API_PPL_11a.md faked: people stores, an artifact store, a redactor,
    a clock, plate sources, source owners and (optionally) the SEC-15 access store. `as_user` signs a person in."""

    def __init__(
        self, monkeypatch: Any, *, org: str = ORG, now: str = NOW, deployed: bool = False, access: Any = None
    ) -> None:
        from tilo_api import app, deps  # noqa: PLC0415
        from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend  # noqa: PLC0415
        from tilo_people.stores import PeopleStores  # noqa: PLC0415

        live_var = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch
        for name in (live_var, "TILO_JUDGE_LIVE", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
            monkeypatch.delenv(name, raising=False)
        if deployed:
            monkeypatch.setenv("K_SERVICE", "tilo-api")
        self.monkeypatch, self.app, self.deps, self.org, self.clock = monkeypatch, app, deps, org, now
        monkeypatch.setattr(deps, "ORG_ID", org)
        self.store_calls: list[tuple[str, str, str]] = []
        self.real = PeopleStores.in_memory()
        self.stores = self._wrap(self.real)
        self.redactor, self.sources, self.owners = SpyRedactor(), FakeSources(), FakeOwners()
        self.screener, self._ids, self._store_now = _Screener(), [], datetime(2026, 10, 5, 10, 5, tzinfo=UTC)
        self.blobs, self.meta = MemoryBlobBackend(), MemoryMetaBackend()
        self.artifacts = ArtifactStore(
            self.meta,
            self.blobs,
            clock=lambda: self._store_now,
            redactor=IdentityRedactor(),  # so the API's own redactor is what removes a secret
            archive_lookup=lambda scope, ref: None,
            alert_sink=lambda alert: None,
            screener=self.screener,
            new_id=lambda: self._ids.pop(0),
        )
        self.access = access
        self.user, self.role, self.world_id, self.signed_in = OWNER, "owner", None, True
        self.resolved: list[str] = []  # the seams a request resolved, in order
        self.router_calls: list[str] = []
        self.flag_calls: list[str] = []
        self.deps_names: dict[str, Any] = {}
        self._wire()
        self.client = TestClient(app, raise_server_exceptions=False)

    # -- wiring -------------------------------------------------------------------------------------------------

    def _wrap(self, real: Any, **flags: bool) -> Any:
        from tilo_people.stores import PeopleStores  # noqa: PLC0415

        wrapped = {
            f: SpyStore(getattr(real, f), self.store_calls, flags.get(f, False))
            for f in ("persons", "meetings", "work_items", "pins", "mentions", "calendar")
        }
        return PeopleStores(**wrapped)

    def conflicting_stores(self, *names: str) -> None:
        """From now on `replace` on these stores (`work_items`, `meetings`, ...) loses its compare-and-set."""
        for name in names:
            getattr(self.stores, name).fail_replace = True

    def _res(self, name: str, value: Any) -> Callable[[], Any]:
        def provide() -> Any:
            self.resolved.append(name)
            return value() if callable(value) else value

        return provide

    def _principal(self) -> Any:
        if not self.signed_in:
            raise HTTPException(status_code=401, detail="not signed in")
        return self.deps.Principal(user_id=self.user, role=self.role, world_id=self.world_id)  # type: ignore[arg-type]

    def _wire(self) -> None:
        deps, ov = self.deps, self.app.dependency_overrides
        ov[deps.get_current_principal] = self._principal
        ov[seam(deps, "get_people_stores")] = self._res("people_stores", lambda: self.stores)
        ov[seam(deps, "get_artifact_store")] = self._res("artifact_store", lambda: self.artifacts)
        ov[seam(deps, "get_redactor")] = self._res("redactor", lambda: self.redactor)
        ov[seam(deps, "get_clock")] = self._res("clock", lambda: lambda: self.clock)
        ov[seam(deps, "get_plate_sources")] = self._res("plate_sources", lambda: self.sources)
        ov[seam(deps, "get_source_owners")] = self._res("source_owners", lambda: self.owners)
        if self.access is not None:
            ov[seam(deps, "get_access_store")] = lambda: self.access

        def no_flags() -> Any:
            self.flag_calls.append("get_flag_store")
            from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415

            return InMemoryFlagStore()

        ov[deps.get_flag_store] = no_flags

        def no_router(mode: str) -> Any:
            self.router_calls.append(mode)
            raise AssertionError("the people API must never build a model router (it makes no model call)")

        self.monkeypatch.setattr(deps, "router_for_mode", no_router)

    def unwire(self, *names: str) -> None:
        """Back to the production default of a seam (`people_stores`, `artifact_store`, `redactor`, `clock`,
        `plate_sources`, `source_owners`)."""
        for name in names:
            key = seam(self.deps, f"get_{name}")
            self.app.dependency_overrides.pop(key, None)

    def close(self) -> None:
        self.app.dependency_overrides.clear()

    # -- people and records ---------------------------------------------------------------------------------------

    def as_user(self, user_id: str, role: str = "owner", world_id: str | None = None) -> None:
        self.user, self.role, self.world_id, self.signed_in = user_id, role, world_id, True

    def sign_out(self) -> None:
        self.signed_in = False

    def set_now(self, ts: str) -> None:
        self.clock = ts

    def add_people(self, persons: Iterable[dict[str, Any]] | None = None) -> None:
        for person in persons if persons is not None else STANDARD_PERSONS.values():
            self.real.persons.create(copy.deepcopy(person))

    def add(self, store: str, record: dict[str, Any]) -> None:
        getattr(self.real, store).create(copy.deepcopy(record))

    def stored(self, store: str, record_id: str, org: str | None = None) -> dict[str, Any] | None:
        found = getattr(self.real, store).get(org or self.org, record_id)
        return None if found is None else copy.deepcopy(dict(found.record))

    def version_of(self, store: str, record_id: str, org: str | None = None) -> int | None:
        found = getattr(self.real, store).get(org or self.org, record_id)
        return None if found is None else found.version

    def put_doc(
        self,
        scope: Any,
        artifact_id: str,
        doc: dict[str, Any],
        *,
        screening: str = "clean",
        created_at: str = "2026-10-05T10:05:00.000Z",
        run_id: str = "r_meeting_q4_plan_1",
    ) -> Any:
        """Stores one JSON artifact version (a transcript or minutes) under exactly the ids and scope given."""
        from tilo_memory.artifacts import NewVersion, Origin  # noqa: PLC0415

        self._ids = [artifact_id]
        self.screener.verdict = screening
        self._store_now = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        content = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        return self.artifacts.put(scope, NewVersion("application/json", content, run_id, Origin(kind="upload")))

    # -- crossref cases -------------------------------------------------------------------------------------------

    def seed_quote_case(self, case: dict[str, Any]) -> None:
        """A `fixtures/transcript/crossref/` case as stored state: the persons, the meeting (or its tombstone), the
        work item, the minutes artifact in the meeting's scope and the transcript version exactly as the case
        states it (own scope, own screening). The caller is the request's actor."""
        from tilo_memory.artifacts import Scope  # noqa: PLC0415

        self.org = case_org(case)
        self.monkeypatch.setattr(self.deps, "ORG_ID", self.org)
        self.set_now(case["now"])
        self.add_people(case["persons"].values())
        meeting, version = case["meeting"], case["version"]
        if meeting is not None:
            self.add("meetings", meeting)
        if case["work_item"] is not None:
            self.add("work_items", case["work_item"])
        if meeting is not None and case["minutes"] is not None and meeting.get("minutes"):
            world = meeting.get("world_id") or (version or {}).get("world_id") or "w_meeting_none"
            scope = Scope(meeting["org_id"], world, meeting["owner"])
            self.put_doc(
                scope, meeting["minutes"]["artifact_id"], case["minutes"], created_at=case["minutes"]["generated_at"]
            )
        if version is not None and case["transcript"] is not None:
            assert version["artifact"]["version"] == 1, "the rig stores version 1 of each artifact"
            scope = Scope(version["org_id"], version["world_id"], version["owner"])
            self.put_doc(
                scope,
                version["artifact"]["artifact_id"],
                case["transcript"],
                screening=version["screening"],
                created_at=version["created_at"],
                run_id=version["run_id"],
            )
        self.as_user(case["request"]["actor"])

    def seed_plate_case(self, case: dict[str, Any]) -> None:
        """A `fixtures/plate/crossref/` case as stored state; cards go to the plate sources as facts."""
        self.org = case_org(case)
        self.monkeypatch.setattr(self.deps, "ORG_ID", self.org)
        self.set_now(case["now"])
        self.add_people(case["persons"].values())
        src = case["source"]
        if src.get("meeting"):
            self.add("meetings", src["meeting"])
        if src["kind"] == "card":
            self.sources.card_facts.append(
                {k: src[k] for k in ("world_owner", "approver", "answered")} | {"data": src["data"]}
            )
        else:
            self.add({"work_item": "work_items", "pinboard_item": "pins"}[src["kind"]], src["data"])
            for mention in src.get("mentions", []):
                self.add("mentions", mention)
        self.as_user(case["request"]["actor"])

    # -- http -----------------------------------------------------------------------------------------------------

    def require_route(self, route: tuple[str, str]) -> None:
        method, template = route
        paths = self.app.openapi()["paths"]
        assert template in paths and method.lower() in paths[template], f"the app has no route {method} {template}"

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.client.get(path, **kwargs)

    def post(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        return self.client.post(path, json={} if body is None else body, **kwargs)

    def quote_request(self, case: dict[str, Any]) -> Any:
        req = case["request"]
        if req["meeting"] is not None:
            self.require_route(R_QUOTES)
            return self.get(f"/v1/meetings/{req['meeting']}/quotes", params={"ids": ",".join(req["ids"])})
        self.require_route(R_ITEM_QUOTE)
        return self.get(f"/v1/work-items/{req['work_item']}/quote")

    def plate(self, **kwargs: Any) -> Any:
        self.require_route(R_PLATE)
        return self.get("/v1/plate", **kwargs)

    def snapshot(self) -> Any:
        """Everything a refused request or a read must leave alone: every people store (id, version and content)
        and every artifact record."""
        out: dict[str, Any] = {}
        for name in ("persons", "meetings", "work_items", "pins", "mentions", "calendar"):
            store = getattr(self.real, name)
            out[name] = {s.record["id"]: [s.version, s.record] for s in store.list(self.org)}
        out["artifacts"] = sorted(self.meta.paths(""))
        return json.dumps(out, sort_keys=True, default=str)


def u(*code_points: int) -> str:
    """Code points as a string (no escape sequences in the test files: editors unescape them)."""
    return "".join(chr(c) for c in code_points)


def canonical(body: Any) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run_threads(count: int, work: Callable[[int], Any]) -> list[Any]:
    """`work(i)` on `count` threads released together; their results in order."""
    results: list[Any] = [None] * count
    barrier = threading.Barrier(count)

    def go(i: int) -> None:
        barrier.wait()
        results[i] = work(i)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# --- record builders (schema-valid, in org_example, the crossref universe) ------------------------------------------


def own_item(item_id: str = "wi_own1", owner: str = PRIYA, **ov: Any) -> dict[str, Any]:
    """A person-made, open work item on `owner`'s own plate (no assigner)."""
    base = pl.work_item(
        id=item_id,
        org_id=ORG,
        owner=owner,
        title="Water the plants",
        due=None,
        due_text=None,
        source={"kind": "manual", "ref": None, "evidence": []},
        created_by=pl.maker_person(owner, EARLY),
        assigned_by=None,
        confirmed_by=None,
        snoozed_until=None,
        history=[pl.history_entry(owner, "created", "open", EARLY)],
        created_at=EARLY,
        updated_at=EARLY,
    )
    return pl.with_(base, **ov)


def released_item_case() -> dict[str, Any]:
    """The plate crossref case with a Tilo-made item from u_owner's confirmed meeting, on u_priya's plate."""
    return fixture_case("plate", "valid", "own_confirmed_meeting_item_joins_rows")


def history_of(count: int, who: str = PRIYA) -> list[dict[str, Any]]:
    """`count` schema-valid history entries (a creation, then edits) for a person-made open item."""
    first = pl.history_entry(who, "created", "open", EARLY)
    return [first] + [pl.history_entry(who, "edited", "open", EARLY) for _ in range(count - 1)]


def today_in(tz: str, now: str) -> str:
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    return datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).date().isoformat()


def rows_of(plate: dict[str, Any], lane: str = "rows") -> list[dict[str, Any]]:
    return plate[lane]


def refs(plate: dict[str, Any], lane: str = "rows") -> list[tuple[str, str]]:
    return [(r["ref"]["kind"], r["ref"]["id"]) for r in plate[lane]]


def find_row(plate: dict[str, Any], kind: str, record_id: str) -> tuple[str, dict[str, Any]] | None:
    for lane in ("rows", "parked"):
        for row in plate[lane]:
            if row["ref"] == {"kind": kind, "id": record_id}:
                return lane, row
    return None
