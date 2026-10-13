# FR-MTG-03/04 internal analyst

`meeting_analysis.analyze_minutes` takes an authorised pinned transcript and a Router.
It screens before generation, checks cited spans, resolves identities/dates in code,
and preserves failed decision/action checks as unverified. Unsupported summaries refuse.
Agenda titles must match the supplied stored agenda in order and count; omitted input
means an empty agenda. Each coverage row needs a positive semantic verifier result.
Covered/partial rows need pinned evidence; the verifier receives the full transcript
to assess extent and absence. Unsupported coverage, outages and exhausted verification
budget refuse analysis, since the schema has no unverified coverage representation.
No public route, record write, confirmation, item creation or follow-up is wired here.
Acceptance: `uv run --package tilo-api pytest services/api/tests/test_FR_MTG_03_minutes_analysis.py -q`.

Agenda and extraction acceptance: add `test_FR_MTG_03_agenda_verification.py` and
`test_FR_MTG_03_extraction_acceptance.py`. The latter runs 12 synthetic transcripts
with scripted analyst/verifier outputs and independently labelled action expectations.
It checks valid minutes, 100% expected agenda rows, recall >=85%, precision >=90%,
zero invented verified commitments, and rejection of misses/inventions/duplicates.
This tests offline acceptance plumbing, not live-provider extraction quality or the
E-MEET summary rubric. Recorded provider-quality evaluation remains outstanding.
