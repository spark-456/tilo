# FR-MTG-13 meeting answer scope

Owner decision (21 Oct 2026, BQ-MTG-SCOPE-OWNER-1): "tilo joined but it keeps repeating the same thing whenever i
ask something without answering my questions, make it's answers more generic and reduce the safety guardrails as
well". The meeting-only scope below is now **off by default**. The deployed brain answers like a normal assistant: it
uses the meeting information when a question is about the meeting, and otherwise answers general questions (facts,
maths, explanations, small talk) in one or two short spoken sentences, through the fast-reply prompt that already
handled them. A fixed fallback line (no answer, could not get it, did not catch it, the scope decline) is never sent
twice in a row. Only the meeting-topic restriction went: the provider safety checks, the recording disclosure and
"Tilo leave" are unchanged, and the wake rules (FR-MTG-15, WAKE_GATE.md) still decide what reaches a model.

With `MEETING_ANSWER_SCOPE=1` the old scope comes back. The brain then answers read-only requests for the agenda,
minutes so far, or the speaker's own recorded meeting action items. Replies are built from the current recorded
meeting state. Unknown requests get a one-line decline; neither general model knowledge nor project-document
retrieval can supply an answer. The guard also covers the periodic analysis reply, not just the fast path.

Supported scoped requests include "show the agenda", "summarize the minutes so far" and "show my tasks". Ownership
is an exact speaker-name match on this meeting's already recorded items; unknown speakers get no item list. No
private plate, mail or other meeting is fetched. Access to personal platform records would require a verified
speaker-to-person identity binding before any route is used.

The standalone prototype replay fixtures keep their existing behavior. Tests use recorded state and fake models; no
real Meet or paid-call acceptance is claimed.
