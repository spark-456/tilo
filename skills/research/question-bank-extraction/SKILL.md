# Question bank extraction

## When to use
Use when a unit receives fetched or uploaded past-paper PDFs (and optional official answer-key PDFs) as `parts` and must extract multiple-choice questions (MCQs) as structured JSON.

## Steps
1. Read each `question_paper` PDF part page by page and locate every 4-option MCQ (`a`, `b`, `c`, `d`).
2. Extract the plain-text `stem`, the four `options` (`a`–`d`), a lower-case `topic` slug, and `source` (`artifact` ref plus 1-based `page`).
3. If an `answer_key` part (or printed answer section) explicitly states the option letter for a question, record `answer` (`a`–`d`) and `answer_source` (`artifact` and `page`).
4. When no printed answer exists for a question, set `answer` to `"unknown"` and `answer_source` to `null`; never invent an answer key.

## Quality bar
- Every extracted question cites the exact `source.artifact` (`artifact_id`, `version`) and 1-based `source.page` where the stem appears.
- Verified questions (`answer` in `a`–`d`) conform directly to `appspec.schema.json#/$defs/question`.

## Checklist
- [ ] Every MCQ has `id` (`q1`..`q999`), `stem`, `options` (`a`, `b`, `c`, `d`), `topic`, and `source`.
- [ ] `answer` is `"unknown"` (and `answer_source` is `null`) whenever the answer is not printed in an answer key.
- [ ] Strings are plain text with no HTML, script, or external URLs.

## Pitfalls
- Never invent or solve an answer key from the stem when the key is missing or illegible.
- Never omit the 1-based `page` number on `source` or `answer_source`.
