# Callable try-run scorer (FR-SKL-03)

`scorer.py` exports `score_try_run(taught_steps, recorded_steps)`. Load it as a Python
module from this skill directory; it does not import its tests or run any actions.
Taught steps use the skill-from-description shape: `verb`, `object`, `tool` and
boolean `ask_me_first`. Recorded steps use the same three identity fields and boolean `paused`.
Malformed fields raise `ValueError`; identities remain case-sensitive.

The result lists matched, added, skipped, paused and missed steps, with status and match
percentage. An empty example or a missing recorded pause fails at zero percent.
Every repeated taught occurrence is assessed separately. Ordered matching uses longest
common subsequence; the score divides matches by the larger input count and rounds to one
decimal place. This measures recorded correspondence, not the quality of the underlying work.

This callable module complements the skill metadata and fixture proposal in PR #765.
Run `just skills-test` for the callable implementation's golden tests, without a live switch.
