"""FR-AGT-12 (PRD 8.6, 13.3, 14.2): the Verifier fails closed, and what it hands back is a valid manifest.

- A model that fails, rambles or says "cannot tell" marks the claim `unverified`; the review still returns.
- A claim is `verified: true` in the returned manifest only when the Verifier found it supported, and the
  returned manifest is still a valid contracts/manifest.schema.json document (MF-01: a verified claim names
  a source), with only `verified` changed.
- A manifest with no claims is `unverified` (nothing was checked; PRD 14.2 counts unverified as zero saved).
- Property: whatever the model replies, it can never rescue a claim the rules reject (no source, unusable
  source, a number the source does not contain), and a deliverable is `passed` only if every claim is supported.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from agt_scripted import ScriptedProvider
from agt_support import assert_valid_contract
from agt_verifier_support import build_manifest, claim, deliverable_of, make_verifier, note_for
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

TEXT_CLAIM = "Firm Qaa never moved its office."


def _deliverable(claims, *, source_text=None):
    source = source_text if source_text is not None else note_for(5)
    manifest = build_manifest(artifact_id="art_fc", sources={"src_a": source}, claims=claims)
    return deliverable_of(manifest, {"src_a": source})


def _review(deliverable, reply):
    verifier, _ = make_verifier(
        ScriptedProvider(default=reply) if isinstance(reply, str) else ScriptedProvider({TEXT_CLAIM: reply})
    )
    return asyncio.run(verifier.review(deliverable))


@pytest.mark.parametrize(
    "reply",
    [
        json.dumps({"verdict": "cannot_tell"}),
        "",
        "no idea",
        "null",
        "[]",
        json.dumps({"verdict": "yes"}),
        json.dumps({"verdict": "SUPPORTED "}),
        json.dumps({"verdicts": ["supported"]}),
        TimeoutError("provider timeout"),
        RuntimeError("provider outage"),
    ],
    ids=["cannot_tell", "empty", "prose", "null", "list", "bad_verdict", "bad_case", "wrong_key", "timeout", "outage"],
)
def test_FR_AGT_12_a_model_that_cannot_give_a_clear_verdict_leaves_the_claim_unverified(reply) -> None:
    review = _review(_deliverable([claim("cl_1", TEXT_CLAIM, ["src_a"], verified=True)]), reply)
    assert review.status == {"cl_1": "unverified"}
    assert review.result == "unverified"
    assert review.manifest["claims"][0]["verified"] is False


def test_FR_AGT_12_the_returned_manifest_is_valid_and_changes_only_the_verified_flags() -> None:
    claims = [
        claim("cl_1", "Firm Faa reported revenue of 45 million.", ["src_a"], verified=False),
        claim("cl_2", "Firm Faa reported revenue of 945 million.", ["src_a"], verified=True),
        claim("cl_3", "Firm Faa has a new logo.", [], verified=False),
    ]
    deliverable = _deliverable(claims)
    review = _review(deliverable, json.dumps({"verdict": "supported"}))

    assert_valid_contract("manifest", review.manifest)
    assert review.status == {"cl_1": "supported", "cl_2": "contradicted", "cl_3": "unverified"}
    assert [c["verified"] for c in review.manifest["claims"]] == [True, False, False]

    expected = json.loads(json.dumps(deliverable.manifest))
    for row, verdict in zip(expected["claims"], [True, False, False], strict=True):
        row["verified"] = verdict
    assert review.manifest == expected, "everything but the claims' verified flags is the author's, unchanged"


def test_FR_AGT_12_a_manifest_with_no_claims_is_unverified() -> None:
    review = _review(_deliverable([]), json.dumps({"verdict": "supported"}))
    assert review.result == "unverified" and review.status == {}


def test_FR_AGT_12_numbers_are_compared_without_thousands_separators() -> None:
    source = "The fund held 1,250,000 units and grew 3.5 points."
    claims = [
        claim("cl_1", "The fund held 1250000 units.", ["src_a"]),
        claim("cl_2", "The fund held 1,250,000 units.", ["src_a"]),
        claim("cl_3", "The fund grew 3.6 points.", ["src_a"]),
    ]
    review = _review(_deliverable(claims, source_text=source), json.dumps({"verdict": "supported"}))
    assert review.status == {"cl_1": "supported", "cl_2": "supported", "cl_3": "contradicted"}


def test_FR_AGT_12_a_claim_citing_two_sources_needs_only_one_usable_source_holding_its_number() -> None:
    other = "A second note that mentions 77 units."
    source = note_for(5)
    manifest = build_manifest(
        artifact_id="art_two",
        sources={"src_a": source, "src_b": other},
        claims=[claim("cl_1", "Firm Faa reported revenue of 45 million.", ["src_b", "src_a"])],
    )
    verifier, _ = make_verifier(ScriptedProvider(default=json.dumps({"verdict": "supported"})))
    review = asyncio.run(verifier.review(deliverable_of(manifest, {"src_a": source, "src_b": other})))
    assert review.status == {"cl_1": "supported"} and review.result == "passed"


# --- properties ----------------------------------------------------------------------------

_MODEL_REPLIES = st.one_of(
    st.sampled_from(["", "garbage", "null", "[]"]),
    st.sampled_from(["supported", "contradicted", "cannot_tell", "yes", "SUPPORTED"]).map(
        lambda v: json.dumps({"verdict": v})
    ),
    st.text(max_size=40),
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(reply=_MODEL_REPLIES, rule=st.sampled_from(["no_sources", "wrong_number", "unusable_source", "tampered_source"]))
def test_FR_AGT_12_property_no_model_reply_can_rescue_a_claim_the_rules_reject(reply, rule) -> None:
    source = note_for(5)
    if rule == "no_sources":
        deliverable = _deliverable([claim("cl_1", TEXT_CLAIM, [], verified=False)])  # MF-01: verified needs a source
    elif rule == "wrong_number":
        deliverable = _deliverable(
            [claim("cl_1", "Firm Faa reported revenue of 905 million.", ["src_a"], verified=True)]
        )
    elif rule == "unusable_source":
        manifest = build_manifest(
            artifact_id="art_p", sources={"src_a": source}, claims=[claim("cl_1", TEXT_CLAIM, ["src_a"], verified=True)]
        )
        deliverable = deliverable_of(manifest, {})  # the fetched text is gone from the archive
    else:
        manifest = build_manifest(
            artifact_id="art_p",
            sources={"src_a": source + " edited"},
            fingerprints={"src_a": source},
            claims=[claim("cl_1", TEXT_CLAIM, ["src_a"], verified=True)],
        )
        deliverable = deliverable_of(manifest, {"src_a": source + " edited"})

    verifier, _ = make_verifier(ScriptedProvider(default=reply))
    review = asyncio.run(verifier.review(deliverable))

    assert review.status["cl_1"] in ("contradicted", "unverified"), f"{rule} rescued by reply {reply!r}"
    assert review.result != "passed"
    assert review.manifest["claims"][0]["verified"] is False


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(replies=st.lists(_MODEL_REPLIES, min_size=1, max_size=4))
def test_FR_AGT_12_property_a_deliverable_passes_only_if_every_claim_is_supported(replies) -> None:
    texts = [f"Firm Q{'a' * (k + 1)} never moved its office." for k in range(len(replies))]
    claims = [claim(f"cl_{k}", text, ["src_a"], verified=True) for k, text in enumerate(texts)]
    verifier, _ = make_verifier(ScriptedProvider(dict(zip(texts, replies, strict=True))))

    review = asyncio.run(verifier.review(_deliverable(claims)))

    statuses = [review.status[f"cl_{k}"] for k in range(len(replies))]
    assert set(statuses) <= {"supported", "contradicted", "unverified"}
    assert [c["verified"] for c in review.manifest["claims"]] == [s == "supported" for s in statuses]
    if all(s == "supported" for s in statuses):
        assert review.result == "passed"
    elif "contradicted" in statuses:
        assert review.result == "failed"
    else:
        assert review.result == "unverified"
    assert_valid_contract("manifest", review.manifest)
