# FR-MTG-13 meeting answer scope

The deployed brain answers read-only requests for the agenda, minutes so far,
or the speaker's own recorded meeting action items. Replies are built from the
current recorded meeting state. Unknown requests get a one-line decline; neither
general model knowledge nor project-document retrieval can supply an answer.
The guard also covers the periodic analysis reply, not just the fast path.

Supported requests include "show the agenda", "summarize the minutes so far"
and "show my tasks". Ownership is an exact speaker-name match on this meeting's
already recorded items; unknown speakers get no item list. No private plate,
mail or other meeting is fetched. Access to personal platform records would
require a verified speaker-to-person identity binding before any route is used.

Deploy after FR-MTG-15's wake gate; these are separate requirement PRs. The
standalone prototype replay fixtures keep their existing behavior. Tests use
recorded state and fake models; no real Meet or paid-call acceptance is claimed.
