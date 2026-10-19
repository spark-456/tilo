# Try Run Match Scorer

Deterministically scores how closely a dry/try run matched a user's taught example sequence, verifying action order, additions, skips, and strict human-in-the-loop pause gates.

## When to use

Use this skill whenever:
- Evaluating an automated try run (test or preview execution) against an established taught workflow.
- Verifying safety boundaries: ensuring every `ask_me_first` step explicitly paused before execution.
- Producing alignment feedback for users showing which steps matched, were added, or were skipped.
- Enforcing read-only evaluation: try-run match analysis never executes, sends, or mutates any external state.

## Steps

1. **Validate inputs**: Confirm `taught_steps` and `recorded_steps` are structured step arrays conforming to the `(verb, object, tool, ask_me_first)` and `(verb, object, tool, paused)` schemas.
2. **Check empty taught baseline**: If `taught_steps` is empty, immediately return `status: "fail"` with `match_percent: 0.0` and `failure_reason: "empty_taught_example"`.
3. **Verify human-in-the-loop pauses**:
   - Inspect every taught step marked with `ask_me_first: true`.
   - Ensure an equivalent step in `recorded_steps` exists and has `paused: true`.
   - If any `ask_me_first` step is missing or executed without pausing, immediately return `status: "fail"` with `match_percent: 0.0` and `failure_reason: "missed_ask_first_pause"`. A missed pause is a hard failure, not a reduced score.
4. **Compute sequence alignment**:
   - Use Longest Common Subsequence (LCS) alignment across step tuples `(verb, object, tool)` to determine matching order.
   - Categorize remaining taught steps as `skipped_steps`.
   - Categorize unaligned recorded steps as `added_steps`.
5. **Calculate match percentage**:
   - Compute `match_percent = round((len(matched_steps) / max(len(taught_steps), len(recorded_steps))) * 100.0, 1)`.
   - Return `status: "pass"`, `failure_reason: null`, along with categorized steps.

## Quality bar

- **Strict determinism**: The scorer must always produce identical outputs for identical inputs without model dependencies or probabilistic heuristics.
- **Safety guarantee**: A missed `ask_me_first` pause must NEVER be treated as a partial degradation; it is always an absolute failure (`status: "fail"`, `match_percent: 0.0`).
- **Zero side effects**: Evaluating a try run reads telemetry only and never calls mutation tools or updates live records.

## Checklist

- [ ] `taught_steps` verified non-empty.
- [ ] All `ask_me_first: true` steps paused during the try run.
- [ ] Longest Common Subsequence computed to preserve sequence order.
- [ ] `matched_steps`, `added_steps`, and `skipped_steps` cleanly partitioned.
- [ ] `match_percent` rounded to 1 decimal place between 0.0 and 100.0.
- [ ] Output passes Draft 2020-12 schema validation.

## Pitfalls

- **Treating missed pauses as score penalties**: `ask_me_first` steps are explicit safety gates defined by the person. Bypassing a pause must fail completely, not merely deduct points.
- **Ignoring step order**: Simply checking set membership without sequence alignment produces false 100% scores on out-of-order executions.
- **Inventing mutations**: Scorer is purely an analytical verification function; it must never trigger actions or persist records.
