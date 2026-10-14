# Why the 160-case replay set is not runnable

Audited against published LIVE3 source
`aa708ec8b1380cc869a377bd6ac23b7a5b17670b` on 14 October 2026.
This is a fixture inventory, not a new eval pass or deployment acceptance.
M2's PREP-INTEGRATE offline result (8/8 passed, zero credits, 160 not runnable)
is separate evidence; its checkout and eval implementation remain untouched.

## Runner reasons

`runner._is_runnable` requires both a non-skeleton status and a recording path.
All 160 cases have `recording: null`: 76 are skeletons and 84 are ready.
The full pass reports the former as `status skeleton` and the latter as
`no recording`. There are no populated recording paths to repair.

Fake providers do not remove this prerequisite. `ReplayExecutor` reads JSONL
outcomes (events plus outputs and credits); it does not run a model or construct
an outcome from case inputs. Expected answers in `ground_truth` are comparison
targets, not execution evidence. Copying them into outputs would manufacture a
pass. Unit tests that write temporary recordings test the runner mechanics and
do not supply outcomes for the repository cases.

## Reasons by case category

| Category | Cases | Status | Missing evidence beyond input fixtures |
| --- | ---: | --- | --- |
| E-PLAN | 10 | ready | Director brief/plan output and measured question/approach counts. Task descriptions and the CSV/notes inputs do not supply those outputs. |
| E-RES | 10 | ready | Case-specific research outputs and citations from the sandbox scenarios. Seed pages are inputs; groundedness autoraters also remain pending when a deterministic replay becomes available. |
| E-DOC | 6 | skeleton | Rendered deliverables, extracted output statistics and actual clean-open evidence for PDF/PPTX. Six table CSVs supply source data, not generated files or proof that a file opens. |
| E-MAIL-01 through E-MAIL-30 | 30 | ready | Triage classification/priority outputs. Thread bodies and expected labels do not record a triage execution. |
| E-MAIL-31 through E-MAIL-50 | 20 | skeleton | Draft/recipient outputs and their action evidence. Draft quality autoraters remain separate pending checks. No real sending is needed or authorised for this audit. |
| E-CHN | 30 | skeleton | Assistant-panel response outputs and channel/action events. Scripted prompts and expected behaviour are case definitions, not replay outcomes. |
| E-HAND | 20 | skeleton | Harness context-handoff outcomes and rework evidence. Synthetic intranet references do not supply the multi-step execution. |
| E-RED | 14 | ready | Safety refusal/flag events and recorded absence of side effects. Injection text, mail and web fixtures are adversarial inputs, not safety-screen outcomes. |
| E-ROUTE | 20 | ready | Matching `question.routed` and `question.answered` events, including decision references where required. `fixtures/route/routing_scenarios.yaml` supplies context exercised by acceptance tests, not a replay event stream. |
| **Total** | **160** | **84 ready, 76 skeleton** | **All missing outcome recordings.** |

## Fixture-wiring result

There are **zero cases in this 160-case set whose only missing piece is a link
to an existing case-matching replay outcome**. No case status, assertion,
recording path or executor has been changed by this sweep. Making these cases
runnable requires producing actual execution outcomes, which is outside this
ticket's no-new-recordings scope; raw input fixtures cannot safely be substituted.

The existing `fixtures/res/E-RES-11.jsonl` belongs to
[`web-cases/E-RES/E-RES-11.yaml`](web-cases/E-RES/E-RES-11.yaml), which already points to it.
It is intentionally outside the 160-case selection and measures a different
web-research scenario. The provider JSON files in `fixtures/liveweb-complete/`
replay individual provider responses for a separate workflow; they are not
case-level outcomes for the 160 definitions. World/demo and meeting transcript
JSONL files elsewhere in the repository likewise represent different scenarios.

When case-specific outcomes are supplied under a separately authorised task,
wire each case to its own JSONL, retain its checks, and change skeleton status
only after its implementation and evidence exist. Run the affected replay cases
once and report deterministic failures, pending autoraters, cap stops and missing
evidence separately. Zero failures with zero executed cases is not a suite pass.
