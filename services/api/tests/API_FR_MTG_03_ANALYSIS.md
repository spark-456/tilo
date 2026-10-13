# FR-MTG-03/04 internal analyst

`meeting_analysis.analyze_minutes` takes an authorised pinned transcript and a Router.
It screens before generation, checks cited spans, resolves identities/dates in code,
and preserves failed decision/action checks as unverified. Unsupported summaries refuse.
Agenda coverage is generated; only its evidence ids are checked in this slice.
No public route, record write, confirmation, item creation or follow-up is wired here.
Acceptance: `uv run --package tilo-api pytest services/api/tests/test_FR_MTG_03_minutes_analysis.py -q`.
