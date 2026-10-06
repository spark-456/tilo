"""Shared, non-test support for the FR-AGT-15 acceptance tests (services/harness).

FR-AGT-15 (Should, PRD 8.2 "Teaching", 10.5 "Promote to skill"): "Promote a Team Lead answer into a proposed
skill change." Acceptance: "The proposal appears for expert review with a diff."

The module under test does not exist yet: `tilo_harness.skill_proposals` (see `services/api/tests/API_FR_AGT_15.md`
for the whole interface the builder must provide). Every helper that touches it imports it lazily, so this file
always imports cleanly and each test fails with the right reason (ModuleNotFoundError) until the builder lands it.

No business logic lives here: the helpers write skill folders, build contract-valid Decision records, assemble fake
secrets at runtime (never as literals: the secret scan and guard hook would flag them) and apply a unified diff so a
test can check that the diff a proposal shows really turns the old skill into the new one.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml

SKILL_ID = "web_research"
DOMAIN = "research"
LEAD_USER = "u_lead_a"  # the Team Lead who gave the answer, and so the proposer
LEAD_ID = "tl_research"
OTHER_EXPERT = "u_expert_b"  # a second person who holds the same domain
CLOCK_NOW = "2026-10-06T09:00:00.000Z"
ULID = "01J8Z3K4M5N6P7Q8R9S0T1V2W6"
CARD_ULID = "01J8Z3K4M5N6P7Q8R9S0T1V2W2"
MAX_GUIDANCE_CHARS = 2000  # decision.schema.json answer maxLength: a promoted answer is never longer than that
SKILL_FILE_CAP_BYTES = 256 * 1024  # tilo_harness.skills._MAX_FILE_BYTES: a larger file makes the skill unloadable

BODY = (
    "# Web research\n\n"
    "When to use: a unit needs facts gathered from open web sources with citations.\n\n"
    "## Steps\n"
    "1. Form 2-3 search queries from the unit's brief.\n"
    "2. Read each result; keep only sources with a clear publish date.\n\n"
    "## Quality bar\n"
    "Every claim has at least one citation.\n"
)


def skill_yaml_text(*, skill_id: str = SKILL_ID, domain: str = DOMAIN, version: str = "1.0.0") -> str:
    data = {
        "id": skill_id,
        "version": version,
        "domain": domain,
        "author": "Ada Example",
        "reviewer": "Grace Example",
        "tools_allowed": ["search_web"],
        "inputs": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
        "outputs": {"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array"}}},
        "description": "Web research with citations for a specialist unit.",
    }
    return yaml.safe_dump(data, sort_keys=False)


def write_skill(
    root: Path,
    *,
    skill_id: str = SKILL_ID,
    domain: str = DOMAIN,
    version: str = "1.0.0",
    body: str = BODY,
) -> Path:
    """skills/<domain>/<skill-id>/{skill.yaml,SKILL.md}, valid against contracts/skill.schema.json."""
    folder = root / domain / skill_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "skill.yaml").write_bytes(skill_yaml_text(skill_id=skill_id, domain=domain, version=version).encode())
    (folder / "SKILL.md").write_bytes(body.encode("utf-8"))
    return folder


def tree_snapshot(root: Path) -> dict[str, bytes]:
    """Every file under `root` (relative posix path -> bytes): 'the skill store is unchanged' is equality of this."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def make_registry(root: Path) -> Any:
    from tilo_harness.skills import SkillRegistry

    registry = SkillRegistry(root)
    assert registry.problems == {}, registry.problems
    return registry


def make_proposals(root: Path, *, clock: Callable[[], str] | None = None) -> Any:
    """`SkillProposals(registry, clock=)`: the in-process proposal store the builder provides."""
    from tilo_harness.skill_proposals import SkillProposals

    return SkillProposals(make_registry(root), clock=clock or (lambda: CLOCK_NOW))


def error_type() -> Any:
    from tilo_harness.skill_proposals import SkillProposalError

    return SkillProposalError


def team_lead_decision(
    *,
    answer: str = "Prefer sources dated within the last 12 months; flag older ones as stale.",
    domain: str | None = DOMAIN,
    lead_user: str = LEAD_USER,
    lead_id: str = LEAD_ID,
    decision_id: str = ULID,
    world_id: str = "w_village_basic",
    run_id: str = "r_village_basic_1",
    card_id: str = CARD_ULID,
) -> dict[str, Any]:
    """A Team Lead's Decision (contracts/decision.schema.json): the stored form of a Team Lead's answer."""
    return {
        "id": decision_id,
        "org_id": "org_acme",
        "question": "How old may a source be before the research skill must flag it?",
        "domain": domain,
        "answer": answer,
        "option_id": None,
        "answered_by": {"by": "team_lead", "ref": lead_id, "user": lead_user, "at": "2026-10-05T10:00:00.000Z"},
        "source": {"world_id": world_id, "run_id": run_id, "card_id": card_id},
        "scope": {"worlds": "all", "districts": "all"},
        "created_at": "2026-10-05T10:00:01.000Z",
        "expires_at": None,
    }


def owner_decision(*, answer: str = "Use whichever sources you like.") -> dict[str, Any]:
    """An owner's (person's) Decision: not a Team Lead's answer, so nothing to promote."""
    decision = team_lead_decision(answer=answer, domain=None)
    decision["answered_by"] = {"by": "person", "ref": "u_owner", "at": "2026-10-05T10:00:00.000Z"}
    return decision


# --- fake secrets, assembled at runtime ---------------------------------------------------------------------------


def fake_secrets() -> dict[str, str]:
    """Strings shaped like real credentials, built from parts so no literal in this repo trips the secret scan."""
    return {
        "github": "gh" + "p_" + ("Ab1Cd2Ef3G" * 4)[:36],
        "api_key": "s" + "k-" + "Zy9Xw8Vu7Ts6Rq5Po4Nm3Lk2",
        "private_key": "-----BEGIN " + "RSA PRIVATE KEY-----",
        "google": "AI" + "za" + "SyD4f9k2Lm8Qp1Rs5Tv7Wx3Yz6Ab0Cd2Ef4",
    }


# --- unified diff, applied -----------------------------------------------------------------------------------------

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def diff_sections(diff: str) -> dict[str, list[tuple[int, int, list[str]]]]:
    """A unified diff as {path of the `+++` line: [(old_start, old_len, hunk lines)]}. Hunk lengths decide where a
    hunk ends, so a removed line that itself starts with '-- ' is not mistaken for a file header."""
    lines = diff.split("\n")
    sections: dict[str, list[tuple[int, int, list[str]]]] = {}
    i = 0
    while i < len(lines):
        if lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            path = lines[i + 1][4:].split("\t")[0].strip()
            i += 2
            hunks: list[tuple[int, int, list[str]]] = []
            while i < len(lines) and (m := _HUNK.match(lines[i])):
                old_len = 1 if m.group(2) is None else int(m.group(2))
                new_len = 1 if m.group(4) is None else int(m.group(4))
                i += 1
                body: list[str] = []
                seen_old = seen_new = 0
                while i < len(lines) and (seen_old < old_len or seen_new < new_len or lines[i].startswith("\\")):
                    line = lines[i]
                    i += 1
                    if line.startswith("\\"):
                        continue  # "\ No newline at end of file"
                    tag = line[:1] or " "  # a blank context line may have lost its leading space
                    seen_old += tag in " -"
                    seen_new += tag in " +"
                    body.append(tag + line[1:])
                hunks.append((int(m.group(1)), old_len, body))
            sections[path] = hunks
        else:
            i += 1
    return sections


def apply_diff_section(before: str, hunks: list[tuple[int, int, list[str]]]) -> list[str]:
    """`before` with one file's hunks applied, as a list of lines. Raises AssertionError when a context or removed
    line does not match `before`: a diff that does not fit the old skill is no diff of it."""
    source = before.splitlines()
    out: list[str] = []
    pos = 0
    for old_start, old_len, body in hunks:
        start = old_start - 1 if old_len else old_start
        out += source[pos:start]
        pos = start
        for line in body:
            tag, text = line[0], line[1:]
            if tag in " -":
                assert source[pos] == text, (
                    f"diff does not fit the old file at line {pos + 1}: {source[pos]!r} != {text!r}"
                )
                if tag == " ":
                    out.append(text)
                pos += 1
            else:
                out.append(text)
    out += source[pos:]
    return out


def section_for(diff: str, filename: str) -> list[tuple[int, int, list[str]]]:
    sections = diff_sections(diff)
    matches = [hunks for path, hunks in sections.items() if path.endswith("/" + filename) or path == filename]
    assert len(matches) == 1, f"the diff must hold exactly one section for {filename}; found {sorted(sections)}"
    return matches[0]


def added_lines(diff: str) -> list[str]:
    """Every '+' line of every hunk, header lines excluded."""
    return [
        line[1:] for hunks in diff_sections(diff).values() for _, _, body in hunks for line in body if line[0] == "+"
    ]


def removed_lines(diff: str) -> list[str]:
    return [
        line[1:] for hunks in diff_sections(diff).values() for _, _, body in hunks for line in body if line[0] == "-"
    ]


def semver(version: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version)
    assert m, f"{version!r} is not plain semver"
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def skill_yaml_of(root: Path, *, skill_id: str = SKILL_ID, domain: str = DOMAIN) -> dict[str, Any]:
    return yaml.safe_load((root / domain / skill_id / "skill.yaml").read_text(encoding="utf-8"))


@contextmanager
def temp_skills(**kwargs: Any) -> Iterator[Path]:
    """A throwaway skills root for property tests, which cannot take the function-scoped `tmp_path` fixture."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "skills"
        write_skill(root, **kwargs)
        yield root
