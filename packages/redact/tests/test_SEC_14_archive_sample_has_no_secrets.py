"""SEC-14 (PRD 16.4, 16.2 "Redaction before write") and FR-MEM-05: a raw archive built with the shared redactor
holds no token, no secure-field value and no full card number, and its hash chain (FR-MEM-04) still verifies,
because redaction runs before hashing. `RunArchive` takes `redact_value`, the tree form of the shared redactor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from _redact_samples_lib import FIXED_TAIL, build
from tilo_archive import LocalDirStore, RunArchive, verify_chain
from tilo_redact import REDACTED, redact_value

ORG, RUN = "org_test01", "r_test01"
NOW = datetime(2026, 10, 7, 9, 30, tzinfo=UTC)
FLIP = FIXED_TAIL[::-1]  # a different tail: the same shapes with other secret values


def _sample(kind: str, tail: str = FIXED_TAIL):
    return build(kind, tail)


def _records(tail: str, *, card_in: bool = True):
    """One payload per archive kind, each carrying secrets in free text and in secure fields."""
    pem, jwt, card = _sample("pem_private_key", tail), _sample("jwt", tail), _sample("card_spaced", tail)
    token, bearer, pw = (
        _sample("google_oauth_access", tail),
        _sample("bearer_bare", tail),
        _sample("password_equals", tail),
    )
    cookie = "sid=" + tail[:12]
    request = {"prompt": f"Fetch it with {token.text}", "headers": {"Authorization": bearer.text}}
    response = {"text": f"here is the key {pem.text}", "usage": {"input_tokens": 12, "output_tokens": 3}}
    args = {"user": "u_01HZ", "password": "Zq" + tail[:12], "note": pw.text}
    mail = "ops@harrier-logistics.example"
    records = [
        ("model_call", {"request": request, "response": response}),
        ("tool_call", {"name": "login", "args": args}),
        ("channel_in", {"from": mail, "text": f"my session {jwt.text}", "cookie": cookie}),
        ("channel_out", {"to": mail, "body": card.text if card_in else "no card", "refresh_token": "1/" + tail[:20]}),
    ]
    vanish = [
        *token.vanish,
        *bearer.vanish,
        *pem.vanish,
        *pw.vanish,
        *jwt.vanish,
        *(card.vanish if card_in else ()),
        cookie,
        "Zq" + tail[:12],
    ]
    return records, vanish, card


def _archive(root, tail, *, card_in: bool = True):
    archive = RunArchive(LocalDirStore(root), org_id=ORG, run_id=RUN, redactor=redact_value, clock=lambda: NOW)
    records, vanish, card = _records(tail, card_in=card_in)
    for kind, payload in records:
        archive.append(kind, payload)
    return archive, vanish, card


def test_SEC_14_archive_sample_has_no_tokens_secure_fields_or_full_card_numbers(tmp_path):
    archive, vanish, card = _archive(tmp_path, FIXED_TAIL)
    stored = "\n".join(LocalDirStore(tmp_path).read_lines(ORG, RUN))
    assert [v for v in vanish if v in stored] == []
    assert card.card is not None and card.card not in stored
    payloads = [json.loads(line)["payload"] for line in stored.split("\n")]
    assert payloads[1]["args"]["password"] == REDACTED
    assert payloads[2]["cookie"] == REDACTED and payloads[3]["refresh_token"] == REDACTED
    assert payloads[0]["request"]["headers"]["Authorization"] == REDACTED
    assert payloads[0]["response"]["usage"] == {"input_tokens": 12, "output_tokens": 3}  # not a secure field
    assert payloads[2]["from"] == "ops@harrier-logistics.example"
    assert [r["kind"] for r in archive.records()] == ["model_call", "tool_call", "channel_in", "channel_out"]


def test_SEC_14_hash_chain_verifies_after_redaction_and_after_reopening(tmp_path):
    archive, _, _ = _archive(tmp_path, FIXED_TAIL)
    assert verify_chain(archive.records(), archive.head()) == []
    reopened = RunArchive(LocalDirStore(tmp_path), org_id=ORG, run_id=RUN, redactor=redact_value)
    assert reopened.records() == archive.records()
    assert verify_chain(reopened.records(), archive.head()) == []


def test_SEC_14_redaction_happens_before_hashing_so_a_hash_never_depends_on_a_secret(tmp_path):
    one, _, _ = _archive(tmp_path / "one", FIXED_TAIL, card_in=False)  # a card keeps its last four: leave it out
    other, _, _ = _archive(tmp_path / "other", FLIP, card_in=False)
    assert one.head() == other.head()  # same shapes, other secret values: identical stored records and hashes
