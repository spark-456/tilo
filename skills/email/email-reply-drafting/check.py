# email/email-reply-drafting checker (FR-AGT-04): invariants only, from
# inputs.thread/instruction and the drafted output. safety_flags come from
# the SafetyProvider (PRD 16.3 point 2).
from skills._lib import guard


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    thread = inputs.get("thread", {})
    msgs = [m for m in thread.get("messages", []) if isinstance(m, dict)]
    reply_to = inputs.get("reply_to_sender")
    reply_all = inputs.get("reply_all") is True
    owner = inputs.get("mailbox_owner")
    instruction = inputs.get("instruction") or ""
    to, cc = output.get("to", []), output.get("cc", [])

    findings = [guard.finding("attachments-present", "must not attach")] if output.get("attachments") else []

    if reply_all:
        seed = {reply_to} if isinstance(reply_to, str) else set()
        parts = ({a for a in [m.get("from"), *list(m.get("to") or [])] if isinstance(a, str)} for m in msgs)
        participants = seed.union(*parts)
        participants.discard(owner)
        actual = {a for a in to if isinstance(a, str)} | {a for a in cc if isinstance(a, str)}
        bad = not to or actual != participants
        detail = f"to+cc {sorted(actual)} != participants {sorted(participants)}"
    else:
        expected_to = [reply_to] if isinstance(reply_to, str) else []
        bad = to != expected_to or bool(cc)
        detail = f"to must be {expected_to}, cc empty; got to={to} cc={cc}"
    findings += [guard.finding("recipient-mismatch", detail)] if bad else []

    flagged = any(m.get("safety_flags") for m in msgs)
    got_flag = output.get("injection_flagged")
    mismatch = f"injection_flagged={got_flag!r} but thread flagged={flagged}"
    findings += [guard.finding("injection-flag-mismatch", mismatch)] if got_flag is not flagged else []

    allowed = guard.number_tokens(instruction).union(*(guard.number_tokens(m.get("body")) for m in msgs))
    drafted = guard.number_tokens(output.get("subject")) | guard.number_tokens(output.get("body"))
    invented = drafted - allowed
    findings += [guard.finding("number-not-in-source", f"not in source: {sorted(invented)}")] if invented else []
    return findings
