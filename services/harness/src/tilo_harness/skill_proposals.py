"""Promote a Team Lead's answer into a proposed skill change (FR-AGT-15, PRD 8.2 Teaching and Governance, 10.5).

The answer is untrusted text. Deterministic code (no model, no provider) turns it into a proposal: the skill's
SKILL.md plus the text appended under a code-owned heading, and a patch version bump in skill.yaml, shown as one
unified diff. A proposal never applies itself and is nowhere near a prompt: a run loads skills only from its pins.
`approve` is the only writer of skill files. It needs a reviewer who is in `experts` (the Team Leads of the skill's
domain, resolved by the caller from current records and re-checked on every call), who is not the proposer or the
answering Lead, and a skill still hash-equal to the one the proposal was made against. Text can only ever land in
SKILL.md: skill.yaml gets `version` and `reviewer` from code. Secret-looking text is refused, never stored.
Proposals live in memory, like `CardStore`; the registry's folder is the skill store."""

from __future__ import annotations

import copy
import datetime
import difflib
import hashlib
import json
import os
import re
import secrets
import threading
import unicodedata
from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any

import yaml

from tilo_harness.skills import _MAX_FILE_BYTES, SkillError, SkillRegistry
from tilo_harness.validator import repo_validator

MAX_GUIDANCE_CHARS = 2000  # decision.schema.json: the answer cap
MAX_NOTE_CHARS = 500
MAX_OPEN_PER_PROPOSER = 20
_SKILL_ID = re.compile(r"[a-z][a-z0-9]*([_-][a-z0-9]+)*")
_SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
_REVIEWER = re.compile(r"[A-Za-z0-9_.@-]{1,80}")
_HEADING = "## Team Lead guidance"
_REVIEWER_STANDIN = "<the approving expert, filled in by code>"
# a fresh copy of the patterns of scripts/secret_scan.py (that script is never imported)
_SECRETS = [
    re.compile(p)
    for p in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"AIza[0-9A-Za-z_\-]{35}",
        r"\bAQ\.[0-9A-Za-z_\-]{40,}",
        r"ya29\.[0-9A-Za-z_\-]{20,}",
        r"1//0[0-9A-Za-z_\-]{30,}",
        r"\bsk-[A-Za-z0-9_\-]{20,}",
        r"\bgh[pousr]_[A-Za-z0-9]{36}\b",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}",
        r"\bEAA[A-Za-z0-9]{60,}",
        r"\bnvapi-[A-Za-z0-9_\-]{20,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
        r"\"type\"\s*:\s*\"service_account\"",
    )
]
# Unicode Default_Ignorable_Code_Point (DerivedCoreProperties.txt; `unicodedata` has no such property): invisible in a
# diff, so they can hide a key's halves or a payload. All refused, but one VS15/VS16 then one joiner after a visible
# base character.
_IGNORABLE = (
    (0xAD, 0xAD), (0x34F, 0x34F), (0x61C, 0x61C), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
    (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F), (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3), (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)  # fmt: skip
_JOINERS = {"\u200c", "\u200d"}
_VARIATION = {"\ufe0e", "\ufe0f"}


def _ignorable(char: str) -> bool:
    return any(lo <= ord(char) <= hi for lo, hi in _IGNORABLE)


class SkillProposalError(Exception):
    """A refusal with a stable `reason` code; nothing was stored or written."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _now() -> str:
    t = datetime.datetime.now(datetime.UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def _scan_secrets(sample: str) -> None:
    """Refuses secret-looking text, judged on the NFKC form with every invisible character dropped (format, control,
    default-ignorable), so a full-width, zero-width or variation-selector-split token is still the token."""

    def visible(value: str) -> str:
        return "".join(
            c
            for c in unicodedata.normalize("NFKC", value)
            if unicodedata.category(c) not in {"Cf", "Cc", "Cs"} and not _ignorable(c)
        )

    flat = visible(visible(sample))  # a second pass: dropping can leave a pair that normalises into something new
    if any(p.search(flat) or p.search(sample) for p in _SECRETS):
        raise SkillProposalError("secret_in_content")


def _clean(text: Any, *, limit: int) -> str:
    """The text as stored: LF line ends, trimmed; refused if too long, blank, secret-looking, or holding anything but
    plain printable text: no surrogate, control, line separator or invisible default-ignorable character, except one
    VS15/VS16 and one joiner right after a visible character (emoji sequences). Runs of them are refused."""
    if not isinstance(text, str):
        raise SkillProposalError("invalid_text")
    if len(text) > limit:
        raise SkillProposalError("too_large")
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    base, varied, joined = False, False, False  # the last visible char; a VS / joiner has followed it
    for char in text:
        category = unicodedata.category(char)
        if category in {"Cs", "Zl", "Zp", "Co", "Cn"} or (category == "Cc" and char not in "\n\t"):
            raise SkillProposalError("invalid_text")
        if char in _VARIATION or char in _JOINERS:
            is_vs = char in _VARIATION
            if not base or joined or (is_vs and varied):
                raise SkillProposalError("invalid_text")
            varied, joined = varied or is_vs, joined or not is_vs
        elif category == "Cf" or _ignorable(char):
            raise SkillProposalError("invalid_text")
        else:
            base, varied, joined = not char.isspace(), False, False
    if not text:
        raise SkillProposalError("empty")
    _scan_secrets(text)
    return text


def _udiff(name: str, old: str, new: str) -> str:
    return "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{name}", f"b/{name}", lineterm=""))


def _bump(version: str) -> str:
    m = _SEMVER.fullmatch(version)
    if m is None:
        raise SkillProposalError("unsupported_skill")
    return f"{m.group(1)}.{m.group(2)}.{int(m.group(3)) + 1}"


def _render_yaml(raw: str, data: dict[str, Any], *, version: str, reviewer: str | None) -> str:
    """skill.yaml with `version` (and `reviewer`, once a person signs off) replaced line by line (comments and layout
    stay), then proven by parsing it back: it must equal the old data with exactly those fields changed."""
    doc = raw
    changes = {"version": version} if reviewer is None else {"version": version, "reviewer": reviewer}
    for key, value in changes.items():
        pattern = re.compile(rf"^{key}:[ \t]*[^\r\n]*$", re.M)
        if len(pattern.findall(doc)) != 1:
            raise SkillProposalError("unsupported_skill")
        line = f"{key}: {json.dumps(value, ensure_ascii=False)}"
        doc = pattern.sub(lambda _m: line, doc)
    try:
        parsed = yaml.safe_load(doc)
    except yaml.YAMLError as error:
        raise SkillProposalError("unsupported_skill") from error
    if parsed != {**data, **changes} or repo_validator().contract_problems("skill", parsed):
        raise SkillProposalError("unsupported_skill")
    return doc


def _read_pair(folder: Path) -> tuple[bytes, bytes]:
    paths = (folder / "skill.yaml", folder / "SKILL.md")
    if any(p.stat().st_size > _MAX_FILE_BYTES for p in paths):
        raise SkillError("skill file over the cap")
    return paths[0].read_bytes(), paths[1].read_bytes()


def _write_pair(folder: Path, raw_yaml: bytes, raw_md: bytes, new_yaml: bytes, new_md: bytes) -> None:
    """Both files or neither: temp files first, then two renames, the first undone if the second fails."""
    tmp_md, tmp_yaml = folder / ".SKILL.md.tmp", folder / ".skill.yaml.tmp"
    try:
        tmp_md.write_bytes(new_md)
        tmp_yaml.write_bytes(new_yaml)
        os.replace(tmp_md, folder / "SKILL.md")
        try:
            os.replace(tmp_yaml, folder / "skill.yaml")
        except OSError:
            (folder / "SKILL.md").write_bytes(raw_md)
            raise
    finally:
        tmp_md.unlink(missing_ok=True)
        tmp_yaml.unlink(missing_ok=True)


class SkillProposals:
    def __init__(self, registry: SkillRegistry, *, clock: Callable[[], str] | None = None) -> None:
        self._registry = registry
        self._clock = clock or _now
        self._proposals: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def propose(
        self, *, decision: Mapping[str, Any], skill_id: str, proposer: str, guidance: str | None = None
    ) -> dict:
        try:
            record = copy.deepcopy(dict(decision))
        except (TypeError, ValueError):
            raise SkillProposalError("invalid_decision") from None
        if repo_validator().contract_problems("decision", record):
            raise SkillProposalError("invalid_decision")
        by = record["answered_by"]
        if by["by"] != "team_lead":
            raise SkillProposalError("not_team_lead_answer")
        if proposer != by["user"]:
            raise SkillProposalError("not_the_answerer")
        folder = (
            self._registry.folder(skill_id) if isinstance(skill_id, str) and _SKILL_ID.fullmatch(skill_id) else None
        )
        if folder is None:
            raise SkillProposalError("unknown_skill")
        if record["domain"] != folder.parent.name:
            raise SkillProposalError("domain_mismatch")
        _scan_secrets(record["answer"])  # the stored answer is screened even when typed guidance replaces it
        text = _clean(record["answer"] if guidance is None else guidance, limit=MAX_GUIDANCE_CHARS)
        with self._lock:
            if sum(
                p["provenance"]["proposed_by"] == proposer and p["status"] == "proposed"
                for p in self._proposals.values()
            ) >= (MAX_OPEN_PER_PROPOSER):
                raise SkillProposalError("too_many_open")
            proposal = self._build(record, folder, skill_id, proposer, text)
            self._proposals[proposal["id"]] = proposal
            return copy.deepcopy(proposal)

    def _build(self, record: dict, folder: Path, skill_id: str, proposer: str, text: str) -> dict[str, Any]:
        try:
            loaded = self._registry.load(skill_id)
            raw_yaml, raw_md = _read_pair(folder)
        except (SkillError, OSError) as error:
            raise SkillProposalError("unknown_skill") from error
        if hashlib.sha256(raw_yaml + raw_md).hexdigest() != loaded.sha256:
            raise SkillProposalError("stale")
        old_body = loaded.body
        body = old_body + ("" if old_body.endswith("\n") or not old_body else "\n") + f"\n{_HEADING}\n\n{text}\n"
        if len(body.encode("utf-8")) > _MAX_FILE_BYTES:
            raise SkillProposalError("too_large")
        to_version = _bump(loaded.version)
        data = yaml.safe_load(raw_yaml)
        # the shown skill.yaml carries a stand-in reviewer: code fills in the approving expert's user id on approval
        new_yaml = _render_yaml(raw_yaml.decode("utf-8"), data, version=to_version, reviewer=_REVIEWER_STANDIN)
        where = f"skills/{folder.parent.name}/{skill_id}"
        diff = (
            _udiff(f"{where}/SKILL.md", old_body, body)
            + "\n"
            + _udiff(f"{where}/skill.yaml", raw_yaml.decode(), new_yaml)
        )
        by, source = record["answered_by"], record["source"]
        return {
            "id": f"sp_{secrets.token_hex(8)}",
            "status": "proposed",
            "skill_id": skill_id,
            "domain": folder.parent.name,
            "from_version": loaded.version,
            "to_version": to_version,
            "base_sha256": loaded.sha256,
            "guidance": text,
            "proposed_body": body,
            "diff": diff + "\n",
            "provenance": {
                "decision_id": record["id"],
                "card_id": source["card_id"],
                "team_lead": by["ref"],
                "team_lead_user": by["user"],
                "world_id": source["world_id"],
                "run_id": source["run_id"],
                "proposed_by": proposer,
                "proposed_at": self._clock(),
            },
            "reviewed_by": None,
            "reviewed_at": None,
            "review_note": None,
        }

    def get(self, proposal_id: str) -> dict | None:
        with self._lock:
            found = self._proposals.get(proposal_id) if isinstance(proposal_id, str) else None
            return copy.deepcopy(found)

    def list(self, *, status: str | None = None) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(p) for p in self._proposals.values() if status in (None, p["status"])]

    def _open_for_review(self, proposal_id: str, reviewer: str, experts: Collection[str]) -> dict[str, Any]:
        """The proposal if `reviewer` may decide it now; every other case raises. Authorisation is plain code on
        the reviewer's identity: nothing in the proposal's text is read."""
        proposal = self._proposals.get(proposal_id) if isinstance(proposal_id, str) else None
        if proposal is None:
            raise SkillProposalError("unknown_proposal")
        prov = proposal["provenance"]
        if reviewer in (prov["proposed_by"], prov["team_lead_user"]):
            raise SkillProposalError("self_review")
        if not isinstance(reviewer, str) or not _REVIEWER.fullmatch(reviewer) or reviewer not in experts:
            raise SkillProposalError("not_expert")
        if proposal["status"] != "proposed":
            raise SkillProposalError("already_decided")
        return proposal

    def approve(self, proposal_id: str, *, reviewer: str, experts: Collection[str]) -> dict:
        with self._lock:
            proposal = self._open_for_review(proposal_id, reviewer, experts)
            folder = self._registry.folder(proposal["skill_id"])
            try:
                if folder is None:
                    raise SkillError("gone")
                raw_yaml, raw_md = _read_pair(folder)
            except (SkillError, OSError) as error:
                raise SkillProposalError("stale") from error
            if hashlib.sha256(raw_yaml + raw_md).hexdigest() != proposal["base_sha256"]:
                raise SkillProposalError("stale")
            new_yaml = _render_yaml(
                raw_yaml.decode("utf-8"),
                yaml.safe_load(raw_yaml),
                version=proposal["to_version"],
                reviewer=reviewer,
            )
            _write_pair(folder, raw_yaml, raw_md, new_yaml.encode("utf-8"), proposal["proposed_body"].encode("utf-8"))
            return self._close(proposal, "approved", reviewer, None)

    def reject(self, proposal_id: str, *, reviewer: str, experts: Collection[str], reason: str | None = None) -> dict:
        with self._lock:
            proposal = self._open_for_review(proposal_id, reviewer, experts)
            blank = reason is None or (isinstance(reason, str) and not reason.strip())
            note = None if blank else _clean(reason, limit=MAX_NOTE_CHARS)
            return self._close(proposal, "rejected", reviewer, note)

    def _close(self, proposal: dict[str, Any], status: str, reviewer: str, note: str | None) -> dict:
        proposal.update(status=status, reviewed_by=reviewer, reviewed_at=self._clock(), review_note=note)
        return copy.deepcopy(proposal)
