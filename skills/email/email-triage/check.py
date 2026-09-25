# email/email-triage checker (FR-AGT-04): invariants only, from
# inputs.messages/output.triage. safety_flags come from the SafetyProvider.
from skills._lib import guard

_CATEGORIES = {"needs_reply", "needs_action", "fyi", "newsletter_promotion", "suspicious"}


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    messages = inputs.get("messages", [])
    findings = guard.ids_exactly_once(guard.str_ids(messages, "id"), (triage := output.get("triage")), "message_id")
    flagged = guard.str_ids([m for m in messages if isinstance(m, dict) and m.get("safety_flags")], "id")
    findings += guard.flags_malformed(messages)

    for row in triage if isinstance(triage, list) else []:
        if not isinstance(row, dict):
            continue
        mid, category, priority = row.get("message_id"), row.get("category"), row.get("priority")
        bad_cat = category not in _CATEGORIES
        findings += [guard.finding("category-invalid", f"{mid}: {category!r} invalid")] if bad_cat else []
        bad_prio = not isinstance(priority, int) or isinstance(priority, bool) or not (0 <= priority <= 100)
        findings += [guard.finding("priority-out-of-range", f"{mid}: {priority!r} invalid")] if bad_prio else []
        needs_susp = mid in flagged and category != "suspicious"
        findings += [guard.finding("flagged-not-suspicious", f"{mid}: flagged but {category!r}")] if needs_susp else []
    return findings
