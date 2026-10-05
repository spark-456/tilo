"""CC-PEOPLE-3: evidence quotes (ADR-0020, people.rules.md PE-22 to PE-25) and the plate (ADR-0021, PE-26 to
PE-30). `expected_quotes` and `expected_join` are the reference oracles for `fixtures/transcript/crossref/` and
`fixtures/plate/crossref/` (formats in people.rules.md, "Fixtures"), which the tilo-api tests (PPL-11a) run too.
A valid file states the outcome the rules give; an invalid file states one its `rule` forbids.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata

import _people_lib as pl
import pytest
from _lib import load_json

MASK = re.compile(r"[^\s@]+@[^\s@]+|\S+://\S+|www\.\S+|\+?\d[\d ().-]{6,}\d")
ORDER = ("attention", "overdue", "soon", "rest", "snoozed", "asked", "done")
QUOTE = {"state": "shown", "speaker": None, "text": None, "truncated": False}
KIND_REASONS = {
    "card": {"gate", "consent", "blocked", "question", "meeting_card"},
    "world": {"blocked", "run"},
    "work_item": {"work_item"},
    "mail": {"mail_reply"},
    "pinboard_item": {"pin_owner", "pin_tagged"},
    "calendar_entry": {"calendar"},
}
BASE = {"rule", "note", "now", "persons", "request"}
# quote case part -> the contract (contract#def) it validates against when not null
PARTS = dict(
    p.split("=")
    for p in "meeting=meeting minutes=minutes transcript=transcript version=artifact work_item=work_item "
    "response=transcript#evidence_quotes".split()
)
FORMATS = {  # folder -> (case keys, rules an invalid case may name)
    "transcript": (BASE | set(PARTS), ("PE-19", "PE-22", "PE-23", "PE-24", "PE-25")),
    "plate": (BASE | {"source", "join"}, ("PE-26", "PE-27")),
}
REQUIRED = {  # ADR-0020 and ADR-0021, "Crossref cases"
    "transcript": set(
        "owner_reads_quotes assignee_reads_one_quote assignee_withheld_for_a_flagged_transcript "
        "assignee_expired_after_the_sweep pe23_assignee_gets_a_second_quote pe23_proposed_work_item "
        "pe23_unconfirmed_minutes pe23_utterance_the_minutes_item_does_not_cite pe23_assigner_on_the_work_item_route "
        "pe23_attendee pe23_teammate pe23_org_owner pe23_another_orgs_meeting".split()
    ),
    "plate": set(
        "own_open_work_item_joins_rows pe27_proposed_work_item pe27_teammates_personal_pin "
        "pe27_pin_after_leaving_the_team pe27_card_in_a_world_where_only_a_viewer pe26_another_persons_plate".split()
    ),
}


def _ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clean(text: str) -> str:
    """PE-24: control, format and separator characters (Unicode Cc, Cf, Zl, Zp) are removed for every viewer."""
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp"))


def _cut(text: str, owner: bool) -> tuple[str, bool]:
    """PE-24: addresses, phone numbers and links masked for a non-owner, then a 240-character cut on a word boundary."""
    t = _clean(text) if owner else MASK.sub("[removed]", _clean(text))
    if len(t) <= 240:
        return t, False
    return (t[:241].rsplit(" ", 1)[0] if " " in t[:241] else t[:240]).rstrip(), True


def _read(case: dict, kind: str, data: dict, actor: str, meeting: dict | None) -> bool:
    """PE-01 to PE-05 through the people oracle: may `actor` read the record in full?"""
    record = {"kind": kind, "data": data, **({"meeting": meeting} if meeting else {})}
    request = {"actor": actor, "action": "read_full", "view": "full"}
    return pl.permits({"now": case["now"], "persons": case["persons"], "record": record, "request": request})


def _assignee_ids(case: dict, present: set[str]) -> list[str] | None:
    """PE-23: the owner of a confirmed item from confirmed minutes gets the lowest utterance both the item and its
    minutes action item cite, present in the pinned version if any is; None refuses."""
    m, mins, wi, req = case["meeting"], case["minutes"], case["work_item"], case["request"]
    if wi is None or req["work_item"] != wi["id"] or req["ids"] or wi["created_by"]["by"] != "tilo":
        return None
    confirmed = m["minutes_confirmed_by"]
    if not _read(case, "work_item", wi, req["actor"], m) or confirmed is None or confirmed["by"] != m["owner"]:
        return None
    item = wi["source"]["ref"].partition("#")[2]
    ai = next((a for a in mins["action_items"] if a["id"] == item and a["work_item_id"] == wi["id"]), None)
    if ai is None or ai["owner"] != wi["owner"] or confirmed["at"] > case["now"]:
        return None
    shared = sorted(set(wi["source"]["evidence"]) & set(ai["evidence"]), key=lambda u: int(u[1:]))
    return [next((u for u in shared if u in present), shared[0])] if shared else []


def _speaker(case: dict, label: str) -> str | None:
    """PE-24: for a non-owner, the display name of the attendee the label resolved to, if that person is the viewer
    or a teammate; otherwise null."""
    persons, actor = case["persons"], case["request"]["actor"]
    user = next((a["user"] for a in case["meeting"]["attendees"] if a["name"] == label and a["user"]), None)
    if user not in persons or (user != actor and not pl.teammates(persons, actor, user, case["now"])):
        return None
    return _clean(persons[user]["display_name"]) or None


def expected_quotes(case: dict) -> dict | None:
    """The `evidence_quotes` tilo-api answers (PE-22 to PE-25), or None for a 404 (PE-19, PE-23)."""
    m, mins, tr, ver, req = (case[k] for k in ("meeting", "minutes", "transcript", "version", "request"))
    me, ref = case["persons"].get(req["actor"]), {k: mins["transcript"][k] for k in ("artifact_id", "version")}
    if me is None or me["org_id"] != m["org_id"] or "world_id" not in m or m["status"] != "minuted":
        return None
    if mins["meeting_id"] != m["id"] or m["transcript"] not in (None, ref):
        return None
    gone = tr is None or m["transcript"] is None or case["now"] >= (m["delete_transcript_after"] or "9")
    if not gone:  # PE-19: the store reads the version only in the meeting's own scope (org, world, owner)
        pinned = ver and {k: ver["artifact"][k] for k in ref} == ref and tr["meeting_id"] == m["id"]
        if not pinned or (ver["org_id"], ver["world_id"], ver["owner"]) != (m["org_id"], m["world_id"], m["owner"]):
            return None
    utterances = {} if gone else {u["id"]: u for u in tr["utterances"]}
    owner = req["actor"] == m["owner"]
    if owner:
        ids = req["ids"] if req["work_item"] is None and 1 <= len(req["ids"]) <= 20 else None
    else:
        ids = _assignee_ids(case, set(utterances))
    if ids is None:
        return None
    quotes = []
    for uid in ids:
        q = {"meeting_id": m["id"], "transcript": ref, "utterance_id": uid, **QUOTE}
        if gone:
            q["state"] = "expired"
        elif uid not in utterances:
            q["state"] = "missing"
        elif not owner and (ver["screening"] != "clean" or mins["flagged"]):
            q["state"] = "withheld"
        else:
            u = utterances[uid]
            q["text"], q["truncated"] = _cut(u["text"], owner)
            q["speaker"] = (_clean(u["speaker"]) or None) if owner else _speaker(case, u["speaker"])
        quotes.append(q)
    return {"quotes": quotes}


def expected_join(case: dict) -> str | None:
    """Where `source` joins the plate of `request.user`: `rows`, `parked` or nowhere (PE-26, PE-27)."""
    req, src, now = case["request"], case["source"], case["now"]
    actor, d = req["actor"], src["data"]
    if req["user"] != actor:  # PE-26: only ever the signed-in person's own plate
        return None
    if src["kind"] == "card":  # unanswered, unexpired, in a world they own or a gate naming them its Approver
        expired = _ts(d["created_at"]) + dt.timedelta(seconds=d["timeout"]) <= _ts(now)
        mine = src["world_owner"] == actor or (d["kind"] == "gate" and src["approver"] == actor)
        return "rows" if mine and src["answered"] is False and not expired else None
    if not _read(case, src["kind"], d, actor, src.get("meeting")) or d["status"] not in ("open", "done", "active"):
        return None
    if src["kind"] == "pinboard_item":
        if d["scope"]["kind"] == "personal":
            return "rows" if d["due"] is not None else None
        tags = src.get("mentions", [])
        tagged = any(t["user"] == actor and t["pin_id"] == d["id"] and not t["removed"] for t in tags)
        return "rows" if d["owner"] == actor or tagged else None
    if d["owner"] != actor:
        return None
    if d["status"] == "open":
        asked = d["history"][-1]["change"] == "reassign_requested"
        return "parked" if asked or (d["snoozed_until"] or "") > now else "rows"
    return "parked" if _ts(now) - _ts(d["updated_at"]) <= dt.timedelta(hours=24) else None


def _group(row: dict, today: str) -> str:
    """PE-28: the group code gives a row in `rows`."""
    soon = (dt.date.fromisoformat(today) + dt.timedelta(days=2)).isoformat()
    if row["reason"] in ("gate", "consent", "blocked"):
        return "attention"
    if row["due"] is not None and row["due"] < today:
        return "overdue"
    if (row["due"] is not None and row["due"] <= soon) or row["reason"] in ("calendar", "question", "meeting_card"):
        return "soon"
    return "rest"


def _order(row: dict) -> tuple:
    """PE-28: group, then due and at ascending with null last ("~" sorts after digits), ref kind, ref id."""
    return ORDER.index(row["group"]), row["due"] or "~", row["at"] or "~", row["ref"]["kind"], row["ref"]["id"]


def _fingerprint(rows: list) -> str:
    """PE-30: SHA-256 of `rows` as JSON with sorted keys, no whitespace, UTF-8."""
    text = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode()).hexdigest()


def _plate_problems(plate: dict) -> list[str]:
    found = []
    for lane in ("rows", "parked"):
        rows = plate[lane]
        found += [f"{r['ref']}: reason" for r in rows if r["reason"] not in KIND_REASONS[r["ref"]["kind"]]]
        found += [f"{r['ref']}: group" for r in rows if lane == "rows" and r["group"] != _group(r, plate["today"])]
        found += [] if [_order(r) for r in rows] == sorted(map(_order, rows)) else [f"{lane}: order"]
    if plate["truncated"] and len(plate["rows"]) < 200 and len(plate["parked"]) < 100:  # PE-27: only a full lane
        found.append("truncated below the cap")
    return found + ([] if plate["fingerprint"] == _fingerprint(plate["rows"]) else ["fingerprint"])


def _cases(repo_root, folder: str, kind: str) -> list:
    cases = [(p, load_json(p)) for p in pl.fixture_files(repo_root, f"{folder}/crossref/{kind}")]
    assert cases, f"contracts/fixtures/{folder}/crossref/{kind}/ must hold at least one case"
    return cases


def _shape(repo_root, registry, folder: str, case: dict) -> list[str]:
    def check(contract: str, doc, def_: str | None = None) -> list[str]:
        return pl.problems(repo_root, registry, contract, doc, def_)

    keys, rules = FORMATS[folder]
    if set(case) != keys:
        return [f"keys must be {sorted(keys)}"]
    found = [] if case["rule"] is None or case["rule"] in rules else [f"rule must be null or one of {rules}"]
    found += check("common", case["now"], "timestamp")
    for key, person in case["persons"].items():
        found += check("person", person) + ([] if person["id"] == key else [f"persons.{key}: the key is the id"])
    req = case["request"]
    if folder == "transcript":
        for part, target in PARTS.items():
            contract, _, def_ = target.partition("#")
            found += [] if case[part] is None else check(contract, case[part], def_ or None)
        found += [] if set(req) == {"actor", "work_item", "ids"} else ["request holds actor, work_item and ids"]
        users, ids = [req["actor"]], req["ids"]
        return (
            found
            + [m for u in users for m in check("common", u, "user_id")]
            + [m for u in ids for m in check("common", u, "utterance_id")]
        )
    src = case["source"]
    found += [] if set(req) == {"actor", "user"} and case["join"] in ("rows", "parked") else ["request or join"]
    found += check(src["kind"], src["data"]) + (check("meeting", src["meeting"]) if "meeting" in src else [])
    found += [] if src["kind"] != "card" or isinstance(src.get("answered"), bool) else ["a card says if answered"]
    users = [req["actor"], req["user"], *(u for u in (src.get("world_owner"), src.get("approver")) if u)]
    found += [m for u in users for m in check("common", u, "user_id")]
    return found + [m for t in src.get("mentions", []) for m in check("mention", t)]


def _outcome(folder: str, case: dict):
    return (expected_quotes(case), case["response"]) if folder == "transcript" else (expected_join(case), case["join"])


@pytest.mark.parametrize("folder", sorted(FORMATS))
@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_CC_PEOPLE_3_PE_22_crossref_cases_are_shape_valid(repo_root, registry, folder, kind):
    for path, case in _cases(repo_root, folder, kind):
        found = _shape(repo_root, registry, folder, case)
        assert not found, f"{folder}/crossref/{kind}/{path.name}: {found[:3]}"


@pytest.mark.parametrize("folder", sorted(FORMATS))
def test_CC_PEOPLE_3_PE_23_valid_cases_get_exactly_what_the_rules_answer(repo_root, folder):
    for path, case in _cases(repo_root, folder, "valid"):
        expected, claimed = _outcome(folder, case)
        assert case["rule"] is None and expected == claimed, f"valid/{path.name}: rules give {expected}, file {claimed}"


@pytest.mark.parametrize("folder", sorted(FORMATS))
def test_CC_PEOPLE_3_PE_23_invalid_cases_claim_what_their_rule_forbids(repo_root, folder):
    for path, case in _cases(repo_root, folder, "invalid"):
        expected, claimed = _outcome(folder, case)
        assert path.name.startswith(f"{str(case['rule']).lower().replace('-', '')}_"), f"invalid/{path.name}: rule"
        assert expected != claimed, f"invalid/{path.name}: the rules give exactly this outcome"


@pytest.mark.parametrize("folder", sorted(REQUIRED))
def test_CC_PEOPLE_3_PE_23_the_adr_crossref_cases_exist(repo_root, folder):
    names = {p.stem for kind in ("valid", "invalid") for p, _ in _cases(repo_root, folder, kind)}
    assert REQUIRED[folder] <= names, f"missing crossref cases: {sorted(REQUIRED[folder] - names)}"


def test_CC_PEOPLE_3_PE_22_transcript_utterance_ids_strictly_increase(repo_root):
    docs = [load_json(p) for p in pl.fixture_files(repo_root, "transcript/valid")]
    docs += [c["transcript"] for _, c in _cases(repo_root, "transcript", "valid") if c["transcript"]]
    for doc in docs:
        ids = [int(u["id"][1:]) for u in doc["utterances"]]
        assert ids == sorted(set(ids)), f"{doc['meeting_id']}: utterance ids must strictly increase"


def test_CC_PEOPLE_3_PE_28_valid_plates_are_grouped_ordered_and_fingerprinted_by_code(repo_root):
    plates = [load_json(p) for p in pl.fixture_files(repo_root, "plate/valid")]
    assert plates and any(len(p["rows"]) > 5 and p["parked"] for p in plates), "need a plate with every lane"
    for plate in plates:
        assert not _plate_problems(plate), _plate_problems(plate)


def test_CC_PEOPLE_3_PE_28_the_plate_check_refuses_a_wrong_group_order_fingerprint_or_truncation(repo_root):
    plates = [load_json(p) for p in pl.fixture_files(repo_root, "plate/valid")]
    plate = next(p for p in plates if p["parked"] and len({r["group"] for r in p["rows"]}) > 2)
    swapped = pl.put(plate, ("rows",), plate["rows"][::-1])
    moved = pl.put(plate, ("rows", 0, "group"), "rest")
    retitled = pl.put(plate, ("rows", 0, "title"), "Another title")
    truncated = pl.put(plate, ("truncated",), True)
    for doc in (swapped, moved, retitled, truncated):
        assert _plate_problems(doc), "a plate the code would not build must be refused"
    assert any(p["truncated"] and len(p["rows"]) == 200 for p in plates), "a valid plate truncated at the row cap"
