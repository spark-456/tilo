# Quiz assessment

## When to use
Use when a unit evaluates a person's quiz attempt (`questions` and `responses`) to produce a scored diagnostic, identify `weak_topics`, recommend a `next_practice_set`, and write a short plain-language `summary`.

## Steps
1. Compare each entry in `responses` against the verified `answer` in `questions` (unanswered or `null` counts as incorrect) and compute overall `score` (`correct`, `total`, `accuracy_pct`).
2. Group questions by `topic` to compute `topic_breakdown` (`correct`, `total`, `accuracy_pct`, and `status`: `"strong"` for >= 75%, `"needs_practice"` for 50%–74%, `"weak"` for < 50%).
3. List every topic with `status == "weak"` in `weak_topics` and build `next_practice_set` entries targeting weak (or needs-practice) topics with `source_refs` pointing to the cited paper pages.
4. Write a concise `summary` stating the score, the weak topics, and the recommended practice focus.

## Quality bar
- `score.correct` and each topic's counts match the exact comparison of `responses` against `questions`.
- Every topic in `weak_topics` is included in `next_practice_set` with at least one cited `source_refs` entry.

## Checklist
- [ ] `score.total` equals the number of questions in `questions`.
- [ ] `weak_topics` matches all topics marked `"weak"` in `topic_breakdown`.
- [ ] `next_practice_set` cites valid `artifact_id`, `version`, and `page` references from the input questions.

## Pitfalls
- Never alter the verified answer key when scoring an attempt.
- Never recommend practice sources that are not present in the world's stored artifacts.
