# Metering rules beyond the schemas

Covers `metering.schema.json` (`config/metering.yaml`), `events/data/budget.requested.schema.json`
1.1.0, `meter.schema.json`, `attention.schema.json`, `evals.schema.json` (`config/evals.yaml`) and
`pilot.schema.json` (PRD 14, 6.6, 19.2, 2.4). Each schema checks one document; these rules compare
values, span documents or describe the computation, and the named service checks them (its own
tests cover them). Rule ids are stable.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| MT-01 | `spend.daily_usd_hard` is at least `spend.daily_usd_soft`. | `packages/metering` config loader | 14.1, 17.3 |
| MT-02 | Reconciliation, once a day: the ledger's credits for the day times `credit_usd` (`config/prices.yaml`) are compared with the billing export's cost of the `billing_services` for the same day. Drift is \|ledger − billed\| ÷ billed (÷ ledger when billed is 0; no drift when both are 0). Drift above `tolerance` raises an alert and freezes new claims in the deck until explained. | `packages/metering` reconciliation job | 14.4, FR-MTR-08 |
| MT-03 | Reserve, then commit: a step reserves its estimate × (1 + `reserve_margin`) and runs only if that reservation, added to what the run has spent and reserved, stays within the run's cap and within `caps.run_credits`, `caps.user_day_credits` and, when it is not null, `caps.org_day_credits`; otherwise it waits. After it runs, the step commits its actual cost and releases its reservation. So spent plus reserved never exceeds the cap. Reaching the hard daily spend cap flips the kill switch (NFR-24). | Treasury (`packages/metering`) | 14.1, FR-MTR-02, FR-MTR-04 |
| MT-04 | `budget.requested` is raised once per approved cap, when spent reaches `request_at` × cap. `remaining_units` are the run's plan units without a `building.completed`, in plan order, with unique ids and the plan's titles. `estimate` covers the whole run: `min` is at least `spent` and at most `max`. | Treasury (`packages/metering`) | 14.1, FR-MTR-03 |
| MT-05 | A meter state: `budget.spent` + `budget.reserved` ≤ `budget.cap`; `time_saved.low` ≤ `time_saved.minutes` ≤ `time_saved.high`; `credits_used` is the sum of `credits` over the run's events up to `last_seq`; `credits_saved` is the sum over accepted reuses (14.3); failed or unverified units count as zero (14.2); `steering_measured` is true exactly when the run has at least one attention span. | `packages/metering` | 14.1 to 14.4 |
| MT-06 | `apps/web` replaces the meter it shows only with a state for the same run and a higher `last_seq`; a state is published within 1 s of its event (FR-MTR-07). | `apps/web`, `packages/metering` | 14.4 |
| MT-07 | An attention span: `ended_at` is not earlier than `started_at`; `run_id` is a run of `world_id`; `user` can see that world (PRD 10.1); a `question` or `card` span's `ref` is a card of that run, and a `review` span's `ref` is an artifact of that run. | `tilo-api` before writing | 14.2 |
| MT-08 | Time saved subtracts the minutes of the run's steering spans (`intake`, `question`, `card`, `take_over`) and review spans (`review`); spans of one person that overlap count once. | `packages/metering` | 14.2, FR-MTR-05 |
| MT-09 | An eval pass (`full`, `smoke` or `gate`) starts no further case once its credits reach `credit_cap` for its kind, and reports the cases already run as partial results. Deploy-gate cases run `deploy_gate_repeats` times, every other case once. | eval runner (`evals/`) | 6.6, 19.2, EFF-07 |
| MT-10 | The case files in `evals/cases/<group>/` number exactly `groups[<group>]` for each group. | eval harness (`evals/`) | 19.2 |
| MT-11 | Cost regression: the nightly job fails when a cost per task or per role rose by more than `cost_regression_threshold` of its baseline ((new − baseline) ÷ baseline); with a baseline of 0, any new cost fails. | eval harness (`evals/`) | 6.6, EFF-06 |
| MT-12 | Consent comes first: a tester's tags, diary entries and survey responses are written only at or after that tester's `consented_at`. `delete_after` is the study's last day plus 30 days (EV-G3 ends on 12 Oct 2026, so 2026-11-11). On that date every record with the tester id is deleted unless `keep_data` is true; withdrawing consent deletes them at once (BQ-66). | `tilo-api`, `packages/metering` | 2.4, 16.5 |
| MT-13 | A `run` tag names a run id (`r_`) and a `card` tag a card id (ULID), of a run or card the tester's pilot account used. One diary entry per tester and date, `day` 1 to 3 in date order; one survey response per tester. | `tilo-api` | 2.4, 14.4 |
| MT-14 | The pilot report (FR-MTR-09) shows aggregates only (counts, medians and ranges across testers), never one tester's records or a tester id. A quote appears only if `quote_consent` is true (schema: `quote` is null otherwise, BQ-66). The free-text answers (`reinvested`, `reinvested_how`, `quote`) pass the secret redactor that guards the raw archive before they are written, and a quote the redactor would change is never exported. | `packages/metering` pilot report | 14.4, 16.5 |

Fixtures: `fixtures/metering/`, `fixtures/evals/`, `fixtures/meter/`, `fixtures/attention/` and
`fixtures/pilot/` (`valid/` and one `invalid/` file per schema rule, named after it);
`fixtures/events/valid/budget.requested.json` and `fixtures/events/invalid/budget_requested_*.json`.
