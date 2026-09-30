"""FR-AGT-04 fix round (security-reviewer, qa-breaker): pins the shared
fail-closed guard layer actually being enforced by every checker, not just by
guard.py in isolation.

These call a skill's check.py directly with inputs that a schema-valid golden
fixture cannot express (an oversize string, 10k-deep nesting, a malformed
safety_flags value) -- the same pattern test_FR_AGT_04_skill_specific_goldens.py
already uses for other checker-level invariants.
"""

from __future__ import annotations

import time

from conftest import import_check_module

UNTRUSTED_READERS = [
    ("email", "email-triage"),
    ("email", "email-reply-drafting"),
    ("research", "web-research-citations"),
]


def _assert_bounds_finding(findings, why):
    assert isinstance(findings, list)
    assert findings, why
    assert all(isinstance(f, dict) and "check" in f and "detail" in f for f in findings)


# ---------------------------------------------------------------------------
# security-reviewer: fail_closed must run guard.check_bounds on inputs/output
# before the check body, fast and without ever raising -- not just have
# check_bounds exist unused.
# ---------------------------------------------------------------------------


def test_FR_AGT_04_untrusted_reader_huge_string_input_yields_bounds_finding_fast():
    huge = "a" * 1_000_000
    for domain, skill_id in UNTRUSTED_READERS:
        module = import_check_module(domain, skill_id)
        started = time.monotonic()
        findings = module.check({"poison": huge}, {})
        elapsed = time.monotonic() - started
        _assert_bounds_finding(findings, f"{domain}/{skill_id}: a 1MB input string must yield a finding, not pass")
        assert elapsed < 2.0, f"{domain}/{skill_id}: check() took {elapsed:.2f}s on a 1MB string, must be bounded"


def test_FR_AGT_04_untrusted_reader_deep_nesting_input_yields_bounds_finding_fast():
    nested: object = "leaf"
    for _ in range(10_000):
        nested = [nested]
    for domain, skill_id in UNTRUSTED_READERS:
        module = import_check_module(domain, skill_id)
        started = time.monotonic()
        findings = module.check({"poison": nested}, {})
        elapsed = time.monotonic() - started
        _assert_bounds_finding(findings, f"{domain}/{skill_id}: 10,000-deep input nesting must yield a finding")
        assert elapsed < 2.0, f"{domain}/{skill_id}: check() took {elapsed:.2f}s on 10,000-deep nesting"


def test_FR_AGT_04_executive_summary_number_past_the_string_cap_is_not_silently_truncated():
    """qa-breaker: number_tokens used to slice text at MAX_STR chars, so a
    fabricated number placed after character 20,000 slipped past the
    number-not-in-material check instead of being caught. fail_closed's
    check_bounds now rejects the oversize string outright, before check()'s
    body ever runs -- it is never silently truncated and let through."""
    module = import_check_module("writing", "executive-summary")
    padding = "filler " * 3000  # well past guard.MAX_STR (20,000 chars)
    inputs = {
        "question": "Did revenue grow?",
        "material": [{"source_id": "src-1", "text": "Revenue reached 1500 thousand dollars."}],
        "max_words": 400,
    }
    output = {
        "answer_first": padding + " and then we invented a 999999 figure.",
        "claims": [{"text": "Revenue reached 1500 thousand dollars.", "source_id": "src-1"}],
    }
    findings = module.check(inputs, output)
    _assert_bounds_finding(findings, "an output string past the size cap must fail closed, not be silently cut")


# ---------------------------------------------------------------------------
# security-reviewer: a safety_flags value that is missing, None, or any shape
# other than a list of non-empty strings must fail closed, not read as clean.
# ---------------------------------------------------------------------------


def test_FR_AGT_04_email_triage_malformed_safety_flags_fails_closed():
    module = import_check_module("email", "email-triage")
    for bad in (None, 0, "", {}, ["", "ok"]):
        inputs = {
            "messages": [{"id": "m1", "from": "a@example.com", "subject": "s", "body": "b", "safety_flags": bad}],
            "vip_senders": [],
        }
        output = {"triage": [{"message_id": "m1", "category": "fyi", "priority": 10}]}
        findings = module.check(inputs, output)
        _assert_bounds_finding(findings, f"safety_flags={bad!r} is not a list of non-empty strings, must fail")


def test_FR_AGT_04_email_reply_drafting_malformed_safety_flags_fails_closed():
    module = import_check_module("email", "email-reply-drafting")
    inputs = {
        "instruction": "Confirm Thursday.",
        "thread": {
            "subject": "s",
            "messages": [{"from": "a@example.com", "to": ["assistant@example.com"], "body": "b", "safety_flags": 0}],
        },
        "reply_to_sender": "a@example.com",
    }
    output = {
        "to": ["a@example.com"],
        "cc": [],
        "subject": "Re: s",
        "body": "Thursday works.",
        "attachments": [],
        "injection_flagged": False,
    }
    findings = module.check(inputs, output)
    _assert_bounds_finding(findings, "safety_flags=0 is not a list of non-empty strings, must fail")


def test_FR_AGT_04_web_research_malformed_safety_flags_fails_closed():
    module = import_check_module("research", "web-research-citations")
    inputs = {
        "question": "q",
        "sources": [{"id": "s1", "url": "https://example.com/a", "text": "Some text.", "safety_flags": {}}],
    }
    output = {"claims": [{"text": "Some text.", "source_ids": ["s1"]}], "flagged_sources": []}
    findings = module.check(inputs, output)
    _assert_bounds_finding(findings, "safety_flags={} is not a list of non-empty strings, must fail")


# ---------------------------------------------------------------------------
# FR-AGT-04 fix round 2 (security-reviewer): email-reply-drafting recipient
# exactness must hold for the whole output, not just the lower-case "bcc"/
# "forward_to" keys, and must not silently drop a non-string to/cc entry
# before comparing sets. Each case below is schema-valid input shaped like a
# real thread; only the drafted output is adversarial.
# ---------------------------------------------------------------------------

_REPLY_ALL_INPUTS = {
    "instruction": "Reply to everyone and confirm Thursday.",
    "thread": {
        "subject": "Thursday plan",
        "messages": [
            {
                "from": "riya@example.com",
                "to": ["assistant@example.com", "bob@example.com"],
                "body": "Does Thursday work for the team?",
                "safety_flags": [],
            }
        ],
    },
    "reply_to_sender": "riya@example.com",
    "reply_all": True,
    "mailbox_owner": "assistant@example.com",
}
_REPLY_ALL_CLEAN_OUTPUT = {
    "to": ["riya@example.com"],
    "cc": ["bob@example.com"],
    "subject": "Re: Thursday plan",
    "body": "Thursday works for the team.",
    "attachments": [],
    "injection_flagged": False,
}


def test_FR_AGT_04_email_reply_drafting_clean_reply_all_passes():
    module = import_check_module("email", "email-reply-drafting")
    findings = module.check(_REPLY_ALL_INPUTS, _REPLY_ALL_CLEAN_OUTPUT)
    assert findings == [], f"a correct reply-all draft must not fail, got {findings}"


def test_FR_AGT_04_email_reply_drafting_capitalized_bcc_key_fails_closed():
    module = import_check_module("email", "email-reply-drafting")
    output = {**_REPLY_ALL_CLEAN_OUTPUT, "Bcc": ["evil@attacker.test"]}
    findings = module.check(_REPLY_ALL_INPUTS, output)
    _assert_bounds_finding(findings, "an output key outside the schema's six (here 'Bcc') must fail, not be ignored")


def test_FR_AGT_04_email_reply_drafting_nested_bcc_header_fails_closed():
    module = import_check_module("email", "email-reply-drafting")
    output = {**_REPLY_ALL_CLEAN_OUTPUT, "headers": {"Bcc": "evil@attacker.test"}}
    findings = module.check(_REPLY_ALL_INPUTS, output)
    _assert_bounds_finding(findings, "a bcc smuggled in an extra 'headers' key must fail, not be ignored")


def test_FR_AGT_04_email_reply_drafting_non_string_cc_dict_entry_fails_closed():
    module = import_check_module("email", "email-reply-drafting")
    output = {**_REPLY_ALL_CLEAN_OUTPUT, "cc": ["bob@example.com", {"address": "evil@attacker.test"}]}
    findings = module.check(_REPLY_ALL_INPUTS, output)
    _assert_bounds_finding(findings, "a non-string cc entry must not be silently dropped before comparing sets")


def test_FR_AGT_04_email_reply_drafting_non_string_cc_nested_list_entry_fails_closed():
    module = import_check_module("email", "email-reply-drafting")
    output = {**_REPLY_ALL_CLEAN_OUTPUT, "cc": [["evil@attacker.test"]]}
    findings = module.check(_REPLY_ALL_INPUTS, output)
    _assert_bounds_finding(findings, "a nested-list cc entry must not be silently dropped before comparing sets")


def test_FR_AGT_04_email_reply_drafting_none_entry_in_to_fails_closed():
    module = import_check_module("email", "email-reply-drafting")
    output = {**_REPLY_ALL_CLEAN_OUTPUT, "to": [None]}
    findings = module.check(_REPLY_ALL_INPUTS, output)
    _assert_bounds_finding(findings, "a None entry in 'to' must fail, not be silently dropped")


# ---------------------------------------------------------------------------
# FR-AGT-04 fix round 2 (code-reviewer): a `pick` that is neither an object
# nor null (a bare string or int) must itself yield a finding, not silently
# pass through both the dict and the None branch.
# ---------------------------------------------------------------------------


def test_FR_AGT_04_price_comparison_non_dict_non_null_pick_fails_closed():
    module = import_check_module("commerce", "price-comparison")
    inputs = {
        "item": "20L backpack",
        "requirements": [{"field": "waterproof", "op": "eq", "value": True}],
        "currency": "USD",
        "rates": {"USD": 1.0},
        "offers": [
            {"offer_id": "o1", "source_id": "src-1", "price": 29.0, "currency": "USD", "unit_count": 1},
        ],
    }
    output = {
        "unit_prices": [{"offer_id": "o1", "unit_price": 29.0, "currency": "USD", "source_id": "src-1"}],
        "pick": "o1",
    }
    findings = module.check(inputs, output)
    _assert_bounds_finding(findings, "pick='o1' (a bare string, not an object or null) must fail, not pass")

    findings_int = module.check(inputs, {**output, "pick": 42})
    _assert_bounds_finding(findings_int, "pick=42 (a bare int, not an object or null) must fail, not pass")


# ---------------------------------------------------------------------------
# FR-AGT-04 fix round 2 (qa-breaker): totals must recompute under a Decimal
# context wide enough for the parse_decimal digit caps, not the default
# 28-digit context, which would silently round a large exact sum and let a
# wrong total pass.
# ---------------------------------------------------------------------------


def test_FR_AGT_04_invoice_po_matching_wrong_total_beyond_default_precision_fails_closed():
    module = import_check_module("finance", "invoice-po-matching")
    big = 10**28
    inputs = {
        "invoice_lines": [
            {"line_id": "i1", "amount": big, "description": "Widgets"},
            {"line_id": "i2", "amount": 1, "description": "Freight"},
        ],
        "po_lines": [
            {"line_id": "p1", "amount": big, "description": "Widgets"},
            {"line_id": "p2", "amount": 1, "description": "Freight"},
        ],
    }
    matches = [
        {"invoice_line_id": "i1", "po_line_id": "p1", "status": "matched", "reason_code": None},
        {"invoice_line_id": "i2", "po_line_id": "p2", "status": "matched", "reason_code": None},
    ]
    wrong = {"matches": matches, "totals": {"invoice_total": big, "po_total": big}}
    right = {"matches": matches, "totals": {"invoice_total": big + 1, "po_total": big + 1}}

    findings_wrong = module.check(inputs, wrong)
    _assert_bounds_finding(findings_wrong, f"total {big} (dropping the +1 line) must fail, not pass by rounding")
    assert module.check(inputs, right) == [], "the exactly-correct total must still pass"
