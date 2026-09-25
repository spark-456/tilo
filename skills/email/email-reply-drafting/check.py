"""Deterministic quality-bar checker for email/email-reply-drafting.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

import re

# Heuristic signal that the thread embeds instructions aimed at the assistant
# rather than the human recipient (PRD 11.4, 16.3 point 1). Kept identical to
# email/email-triage/check.py's pattern — duplicated rather than imported
# because each check.py must be a self-contained stdlib module. Alternatives:
# (1) "ignore/disregard/forget [qualifier]* instructions", with several
# common qualifiers, not just one; (2) a command aimed at the assistant to
# forward/cc/bcc/send content to an address; (3) an instruction to change the
# assistant's settings or behaviour; (4) text addressed directly to
# "assistant" followed by a command verb.
_QUALIFIER = r"(?:all|any|previous|prior|above|earlier|your|the)"
_INJECTION_RE = re.compile(
    r"\b(?:ignore|disregard|forget)\s+(?:" + _QUALIFIER + r"\s+){0,3}instructions\b"
    r"|\b(?:forward|cc|bcc|send)\b[^.\n]{0,80}?\bto\b[^.\n]{0,80}?[\w.+-]+@[\w.-]+"
    r"|\bchange\s+(?:your\s+|the\s+)?(?:settings|behaviour|behavior)\b"
    r"|\bassistant\b\s*[:,-]{1,2}\s*(?:please\s+)?(?:send|forward|cc|bcc|ignore|disregard|change)\b",
    re.IGNORECASE,
)

# A "new commitment" (PRD 11.4: money, date, deliverable) that must trace
# back to the instruction. Built per class of phrasing, not per literal
# example, so a differently-worded but equally concrete commitment is still
# caught. Money/date/time classes covered (fix round 2, security-reviewer):
#   - am/pm times ("4pm", "4:30pm") and 24-hour times ("16:00")
#   - relative dates/times ("tomorrow", "today", "tonight", "noon", "midnight")
#   - "next <week/month/weekday>" and "this <week/weekend/month>"
#   - weekday names ("Thursday")
#   - ISO dates ("2026-10-15") and slash dates ("15/10/2026")
#   - month-name dates, either order ("15 October", "October 15")
#   - symbol currencies, including the rupee sign ($, €, £, ¥, ₹)
#   - 3-letter currency codes, either side of the amount ("500 usd", "usd 500")
#   - worded currencies ("500 dollars", "5000 rupees", "Rs 5000")
# A promised deliverable ("I will send the signed contract") is not
# mechanically detected here — see SKILL.md "Quality bar" for why that class
# is left to the Verifier's semantic review (FR-AGT-12) instead.
_MONTHS = r"january|february|march|april|may|june|july|august|september|october|november|december"
_WEEKDAYS = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_MONEY_WORD = r"dollars?|rupees?|euros?|pounds?|yen"
_CCY_CODE = r"usd|eur|gbp|jpy|inr|cad|aud"
_COMMITMENT_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b"  # 4pm, 4:30pm
    r"|\b(?:[01]\d|2[0-3]):[0-5]\d\b"  # 16:00 (24-hour)
    r"|[$€£¥₹]\s?\d[\d,]*(?:\.\d+)?"  # symbol currency, incl. rupee
    r"|\b(?:rs\.?|inr)\s?\d[\d,]*(?:\.\d+)?\b"  # Rs 5000
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:" + _CCY_CODE + r")\b"
    r"|\b(?:" + _CCY_CODE + r")\s?\d[\d,]*(?:\.\d+)?\b"
    r"|\b\d[\d,]*(?:\.\d+)?\s?(?:" + _MONEY_WORD + r")\b"  # 500 dollars
    r"|\b(?:" + _WEEKDAYS + r")\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"  # ISO date
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"  # slash date
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:" + _MONTHS + r")\b"  # 15 October
    r"|\b(?:" + _MONTHS + r")\s+\d{1,2}(?:st|nd|rd|th)?\b"  # October 15
    r"|\b(?:tomorrow|today|tonight|yesterday|noon|midnight)\b"
    r"|\bnext\s+(?:" + _WEEKDAYS + r")\b",  # "next Friday" names one specific day;
    # deliberately not "next/this week/month" — too vague a span to be a
    # concrete commitment, and "this week" in particular collides with
    # ordinary subject lines like "Re: Meeting this week?" that carry no
    # new commitment at all.
    re.IGNORECASE,
)

# Every key the closed output schema allows; anything else (bcc, forward_to,
# ...) must be rejected rather than silently passed through.
_OUTPUT_KEYS = {"to", "cc", "subject", "body", "attachments", "flags"}


def _normalize_commitment(token: str) -> str:
    """Whole-token normalisation so "$50" never substring-matches "$500"."""
    return re.sub(r"\s+", " ", token.strip().lower()).replace(",", "")


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]
    to = output.get("to")
    cc = output.get("cc")
    attachments = output.get("attachments")
    flags = output.get("flags")
    body = output.get("body")
    if not all(isinstance(x, list) for x in (to, cc, attachments, flags)) or not isinstance(body, str):
        return [
            {
                "check": "output-malformed",
                "detail": "output must have to/cc/attachments/flags arrays and a string body",
            }
        ]

    findings: list[dict] = []
    unexpected_keys = set(output.keys()) - _OUTPUT_KEYS
    if unexpected_keys:
        findings.append(
            {
                "check": "unexpected-output-field",
                "detail": f"output has field(s) outside the closed schema: {sorted(unexpected_keys)}",
            }
        )

    inputs = inputs if isinstance(inputs, dict) else {}
    reply_to_sender = inputs.get("reply_to_sender")
    reply_all = bool(inputs.get("reply_all"))
    thread = inputs.get("thread") if isinstance(inputs.get("thread"), dict) else {}
    messages = thread.get("messages") if isinstance(thread.get("messages"), list) else []
    thread_subject = thread.get("subject") if isinstance(thread.get("subject"), str) else ""

    known_addresses: set[str] = set()
    if isinstance(reply_to_sender, str):
        known_addresses.add(reply_to_sender)
    if reply_all:
        for message in messages:
            if not isinstance(message, dict):
                continue
            if isinstance(message.get("from"), str):
                known_addresses.add(message["from"])
            for addr in message.get("to", []) if isinstance(message.get("to"), list) else []:
                if isinstance(addr, str):
                    known_addresses.add(addr)

    for addr in list(to) + list(cc):
        # addr could be any JSON type (e.g. a list), which is unhashable and
        # would raise on `in` against a set — check the type first.
        if not isinstance(addr, str):
            findings.append({"check": "output-malformed", "detail": f"to/cc entries must be strings, got {addr!r}"})
            continue
        if addr not in known_addresses:
            findings.append(
                {
                    "check": "recipient-not-requested",
                    "detail": f"{addr!r} is not the reply-to sender or a reply-all thread participant (PRD 11.4)",
                }
            )

    if attachments:
        findings.append({"check": "attachments-not-empty", "detail": "a drafted reply must never include attachments"})

    thread_body_text = " ".join(
        m.get("body", "") for m in messages if isinstance(m, dict) and isinstance(m.get("body"), str)
    )
    thread_text = f"{thread_subject} {thread_body_text}"
    if _INJECTION_RE.search(thread_text) and not flags:
        findings.append(
            {
                "check": "injection-in-thread-not-flagged",
                "detail": (
                    "the thread (subject or body) contains an embedded instruction that must be flagged, never followed"
                ),
            }
        )

    instruction = inputs.get("instruction") if isinstance(inputs.get("instruction"), str) else ""
    instruction_tokens = {_normalize_commitment(m.group(0)) for m in _COMMITMENT_RE.finditer(instruction)}
    drafted_subject = output.get("subject") if isinstance(output.get("subject"), str) else ""
    # The commitment scan covers the drafted subject as well as the body: a
    # date or amount slipped into "Re: Meeting - $5,000 agreed" is just as
    # much a new commitment as one written into the body.
    drafted_text = f"{drafted_subject} {body}"
    for match in _COMMITMENT_RE.finditer(drafted_text):
        token = match.group(0)
        if _normalize_commitment(token) not in instruction_tokens:
            findings.append(
                {
                    "check": "new-commitment-not-in-instruction",
                    "detail": f"draft commits to {token!r} which is not present in the instruction",
                }
            )
    return findings
