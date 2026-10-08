# ADR-0033: EvalProvider, the Gen AI evaluation service behind packages/providers

- Status: Proposed (architect, 2026-10-08). It changes no contract, so it needs no user gate. It
  becomes Accepted when the docs PR for VERTEX-EVAL-1 merges.
- Deciders: architect; the user approved the feature (VERTEX-EVAL-1).
- Requirements:
  - PRD 6.3 (the Gen AI evaluation service: "Autoraters for plan quality and groundedness")
  - 6.4 (PL-01, PL-04, PL-06; the sibling interfaces)
  - 6.6 (EFF-01, EFF-07)
  - 19.3 (autoraters, honest reporting)
  - OQ-13 (default: custom rubrics)
- Design: `docs/design/VERTEX-EVAL-1.md`. Questions: BQ-VEVAL-1 to BQ-VEVAL-3.

## Context
Every model call goes through `packages/providers` (PL-01). The evaluation service calls a judge
model, so it must go through that layer too. The service does not fit `ModelProvider`:
- One call evaluates one instance against one metric spec and returns a pairwise choice or a
  pointwise score, plus an explanation.
- It reports no token usage.
- The judge model is a field of the request (`autoraterConfig.autoraterModel`), not the endpoint.

The router's schema repair, cascade and fallback assume generated text. They would be wrong here,
since a judge that changes in the middle of a run invalidates a comparison.

## Decision
1. **A sibling interface:** `EvalProvider.evaluate(EvalRequest) -> EvalScore` in
   `tilo_providers.interfaces`, with `redact()`. It is thin pydantic with `extra="forbid"`, one
   instance per call, and kind and fields must agree. A result that does not match its kind fails
   closed (`ProviderError`).
2. **One role, primary only:** `eval_judge`. `build_eval_provider` reads `primary` and never
   `fallback`, like `safety` (BQ-68). The role's fallback is the same profile, so NFR-25 holds.
3. **One provider kind:** `vertex_eval`. `profile.model` is the judge model the service is told to
   use, so the model id stays in config (PL-01). The adapter is REST over `httpx` with the user's ADC
   bearer token, following `model_armor_adapter.py`. It is built and tested on mocks. Without an
   injected transport, it refuses to build unless `LIVE=1` is set. `fake` gives a deterministic
   `FakeEvalProvider`, which is refused when live or deployed. There is no record-and-replay provider:
   the run's report JSON keeps every judgement.
4. **Custom rubrics only:** templates in `prompts/eval_judge/` (PL-04), sent as
   `metricPromptTemplate`. Predefined metrics are never used, because the service judges them with
   its own default model, which is unpriced and may be denylisted (OQ-13).
5. **Metering at quote:** the service reports no usage, so each call is charged its pre-call quote:
   - the input is a deliberately high byte-based token estimate plus a fixed overhead;
   - the output is an assumed size that includes thinking tokens;
   - the rates come from `config/prices.yaml`.

   A call whose quote does not fit is never sent. The figure is reconciled against the billing
   export (PRD 14.1).
6. **No contract change.** `$defs.profile.provider` is a free slug. The price row uses the existing
   `$defs.price` shape, and a fee per character uses ADR-0029's `unit_price` (providers 1.3.0).

## Consequences
- **Two autorater paths.** `autorater` (ModelProvider through the Router: the generator's GEN-10
  scores) and `eval_judge` (EvalProvider through the evaluation service). Moving GEN-10 onto
  `eval_judge` is possible later and out of scope here.
- **No live profile yet.** `config/models.yaml` gets the `vertex-eval` profile and the
  `eval_judge` role only together with their price row (BQ-VEVAL-1). A profile without a price stops
  start-up for every service while `prices.yaml` is `status: set`.
- **Conformance.** `just conformance` skips `vertex_eval` and `model_armor` profiles: PL-05 is for
  ModelProviders only.
- **Region.** Once ADR-0029's region check lands, `vertex_eval` joins it. The adapter's location is
  `TILO_VERTEX_EVAL_LOCATION`, default `asia-southeast1` (BQ-VEVAL-1).
- **Reports stay apart.** Results are a separate local report labelled LIVE or FAKE. They never feed
  the EV rows, `evals/results.md` or the metrics report (PRD 19.3 honest reporting).
