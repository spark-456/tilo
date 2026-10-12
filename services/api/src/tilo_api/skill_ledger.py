"""Real runs, ratings, fixes and state of a taught skill, one set of rules for both stores (FR-SKL-05, FR-SKL-06;
ADR-0034, ADR-0037; taught_skill.rules.md TS-08, TS-09, TS-13 to TS-15).

A store gives `_atomic(work)` (every read of `work` first, then its buffered writes together, or none: a memory lock, or
a Firestore transaction that retries on a concurrent write) and `_children(path)`. `work(tx)` has `get`, `find` (one
equality filter in a collection), `create` (fails if the document exists) and `set`; it raises `SkillRefused` with a
fixed reason, which writes nothing. Layout under `orgs/{org}/taught_skills/{skill}`: `real_runs/{run_id}` (the run id
is the key, so a run is recorded once), `ratings/{id}`, `fixes/{id}`. A run's `org_id`, `skill`, `version`, `plan` and
`by` come from the stored skill and the verified caller, never from a request; the pinned plan is a copy.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterable
from typing import Any

from tilo_policy.schemas import conforms

_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")
_SKILL = re.compile(r"tsk_[0-9A-Za-z_]{1,48}")
_RUN = re.compile(r"r_[0-9A-Za-z_]{1,48}")
_SCHEMA = "taught_skill.schema.json#/$defs/"
_CHANGES: dict[str, dict[str, Any]] = {
    "paused": {"paused": True},
    "resumed": {"paused": False},
    "learning": {"status": "learning"},
    "trusted": {"status": "trusted"},
}


class SkillRefused(Exception):
    """A rule refused the write; `reason` is a fixed word, never record text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Tx:
    def __init__(self, read: Callable[[str], Any], find: Callable[[str, str, Any], list[dict[str, Any]]]) -> None:
        self.get, self.find = read, find
        self.writes: list[tuple[str, str, dict[str, Any]]] = []

    def create(self, path: str, doc: dict[str, Any]) -> None:
        self.writes.append(("create", path, copy.deepcopy(doc)))

    def set(self, path: str, doc: dict[str, Any]) -> None:
        self.writes.append(("set", path, copy.deepcopy(doc)))


def _root(org: Any, skill_id: Any) -> str:
    if not (isinstance(org, str) and _ORG.fullmatch(org) and isinstance(skill_id, str) and _SKILL.fullmatch(skill_id)):
        raise SkillRefused("not_found")
    return f"orgs/{org}/taught_skills/{skill_id}"


def _run_path(root: str, run_id: Any) -> str:
    if not (isinstance(run_id, str) and _RUN.fullmatch(run_id)):
        raise SkillRefused("not_found")
    return f"{root}/real_runs/{run_id}"


def _read(tx: Tx, root: str, *, drafts: bool = False) -> dict[str, Any]:
    found = tx.get(root)
    if found is None or (found["status"] == "draft" and not drafts):
        raise SkillRefused("not_found")
    return dict(found)


def _valid(name: str, record: dict[str, Any]) -> None:
    if not conforms("taught_skill.schema.json#/$defs/" + name, record):
        raise SkillRefused("invalid_record")


class SkillLedger:
    def _atomic(self, work: Callable[[Tx], Any]) -> Any:
        raise NotImplementedError

    def _doc(self, path: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def _children(self, path: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def start_real_run(
        self, org: str, skill_id: str, *, by: str, teams: Iterable[str], world_id: str, run_id: str, now: str
    ) -> dict[str, Any]:
        """The runner's start guard (TS-13): a draft or paused skill refuses; a run id is recorded once."""
        root = _root(org, skill_id)
        path, teams = _run_path(root, run_id), set(teams)

        def work(tx: Tx) -> dict[str, Any]:
            skill = _read(tx, root, drafts=True)
            scope, held = skill["scope"], tx.get(path)
            if by != skill["owner"] and not (scope["kind"] == "team" and scope["team"] in teams):
                raise SkillRefused("forbidden")
            if held is not None:  # recorded once; only the person it belongs to gets it back
                if held["by"] != by:
                    raise SkillRefused("forbidden")
                return held  # type: ignore[no-any-return]
            if skill["status"] == "draft" or skill["paused"]:
                raise SkillRefused("paused" if skill["paused"] else "draft")
            run = {
                "org_id": org,
                "skill": skill_id,
                "version": skill["version"],
                "run_id": run_id,
                "world_id": world_id,
                "by": by,
                "plan": copy.deepcopy(skill["plan"]),
                "started_at": now,
                "finished_at": None,
                "outcome": None,
            }
            _valid("real_run", run)
            tx.create(path, run)
            return run

        return self._atomic(work)  # type: ignore[no-any-return]

    def finish_real_run(self, org: str, skill_id: str, run_id: str, *, outcome: str, at: str) -> dict[str, Any]:
        """Set `finished_at` and `outcome` together, once (TS-14); a finished run is returned as it is."""
        path = _run_path(_root(org, skill_id), run_id)

        def work(tx: Tx) -> dict[str, Any]:
            run = tx.get(path)
            if run is None:
                raise SkillRefused("not_found")
            if run["outcome"] is not None:
                return run  # type: ignore[no-any-return]
            if at < run["started_at"]:
                raise SkillRefused("finished_before_start")
            done = {**run, "finished_at": at, "outcome": outcome}
            _valid("real_run", done)
            tx.set(path, done)
            return done

        return self._atomic(work)  # type: ignore[no-any-return]

    def record_rating(self, org: str, skill_id: str, rating: dict[str, Any]) -> dict[str, Any]:
        """One rating for a finished real run of the rater's own pinned version (TS-15); `good_runs` follows (TS-08)."""
        root = _root(org, skill_id)
        _valid("rating", rating)
        path = _run_path(root, rating["run_id"])

        def work(tx: Tx) -> dict[str, Any]:
            skill, run = _read(tx, root), tx.get(path)
            if (
                rating["skill"] != skill_id
                or run is None
                or any(run[k] != rating[k] for k in ("version", "by"))
                or run["outcome"] is None
            ):
                raise SkillRefused("not_found")
            if rating["thumb"] == "up" and run["outcome"] != "completed":
                raise SkillRefused("not_rateable")
            if rating["wrong_step"] is not None and rating["wrong_step"] > len(run["plan"]):
                raise SkillRefused("invalid_step")
            if tx.find(f"{root}/ratings", "run_id", rating["run_id"]):
                raise SkillRefused("already_rated")
            ups = {r["run_id"] for r in tx.find(f"{root}/ratings", "thumb", "up")}
            tx.create(f"{root}/ratings/{rating['id']}", rating)
            if rating["thumb"] == "up":
                tx.set(root, {**skill, "good_runs": len(ups | {rating["run_id"]}), "updated_at": rating["at"]})
            return rating

        return self._atomic(work)  # type: ignore[no-any-return]

    def apply_fix(self, org: str, skill_id: str, fix: dict[str, Any]) -> dict[str, Any]:
        """The owner's fix of one step of the current version (TS-09): the record, the plan and version + 1 together."""
        root = _root(org, skill_id)

        def work(tx: Tx) -> dict[str, Any]:
            skill = _read(tx, root)
            plan, step = copy.deepcopy(skill["plan"]), fix["step"]
            if fix["by"] != skill["owner"]:
                raise SkillRefused("forbidden")
            if fix["from_version"] != skill["version"]:
                raise SkillRefused("stale_version")
            if not 1 <= step <= len(plan):
                raise SkillRefused("invalid_step")
            if plan[step - 1]["must_ask"] and not fix["ask_first"]:
                raise SkillRefused("ask_first_required")
            if fix["rating"] is not None and not any(
                r["thumb"] == "down" for r in tx.find(f"{root}/ratings", "id", fix["rating"])
            ):
                raise SkillRefused("unknown_rating")
            record = {**fix, "skill": skill_id, "to_version": skill["version"] + 1}
            _valid("fix", record)
            plan[step - 1] = {**plan[step - 1], "text": fix["text"], "ask_first": fix["ask_first"]}
            after = {**skill, "plan": plan, "version": record["to_version"], "updated_at": fix["at"]}
            tx.create(f"{root}/fixes/{fix['id']}", record)
            tx.set(root, after)
            return after

        return self._atomic(work)  # type: ignore[no-any-return]

    def set_state(
        self, org: str, skill_id: str, change: str, *, by: str, threshold: int, now: str
    ) -> tuple[dict[str, Any], bool]:
        """paused, resumed, learning (Keep learning) or trusted, by the owner; trusted needs `threshold` runs whose
        one rating is an up (TS-08). Returns the record and whether anything changed."""
        root, target = _root(org, skill_id), _CHANGES[change]

        def work(tx: Tx) -> tuple[dict[str, Any], bool]:
            skill = _read(tx, root)
            if by != skill["owner"]:
                raise SkillRefused("forbidden")
            if all(skill[k] == v for k, v in target.items()):
                return skill, False
            good = len({r["run_id"] for r in tx.find(f"{root}/ratings", "thumb", "up")})
            if change == "trusted" and good < threshold:
                raise SkillRefused("not_enough_good_runs")
            after = {**skill, **target, "good_runs": good, "updated_at": now}
            tx.set(root, after)
            return after, True

        return self._atomic(work)  # type: ignore[no-any-return]

    def get_real_run(self, org: str, skill_id: str, run_id: str) -> dict[str, Any] | None:
        try:
            return self._doc(_run_path(_root(org, skill_id), run_id))
        except SkillRefused:
            return None

    def list_real_runs(self, org: str, skill_id: str) -> list[dict[str, Any]]:
        return self._sub(org, skill_id, "real_runs", ("started_at", "run_id"))

    def list_ratings(self, org: str, skill_id: str) -> list[dict[str, Any]]:
        return self._sub(org, skill_id, "ratings", ("at", "id"))

    def list_fixes(self, org: str, skill_id: str) -> list[dict[str, Any]]:
        return self._sub(org, skill_id, "fixes", ("at", "id"))

    def _sub(self, org: str, skill_id: str, name: str, key: tuple[str, str]) -> list[dict[str, Any]]:
        try:
            rows = self._children(f"{_root(org, skill_id)}/{name}")
        except SkillRefused:
            return []
        return sorted(rows, key=lambda r: (r[key[0]], r[key[1]]))
