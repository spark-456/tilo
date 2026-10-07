# Running one case live (`just live-e2e`, PL-LIVE-E2E, issue #340)

`just live-e2e` runs one held-out bank case (`evals/bank/<id>.yaml`) through the real pipeline: intake, the questions (answered from the case), approaches, approval, the plan, the run (Leads, Writers, the Verifier), the Narrator, and delivery or an honest stop. Every model call goes through `packages/providers` by role, so the models are whatever `config/models.yaml` names and the prices are whatever `config/prices.yaml` says. Delivery and the gated send go to the recording mock connectors: nothing real is sent (`side_effects: mock_only`).

Only you start a live run. Nothing in the repo, CI or the dev tools sets `LIVE=1`; the command refuses unless it is exactly `1`, and refuses in CI and on Cloud Run even then.

## Free modes (no switch, safe anywhere)

- `just live-e2e --case B-007 --dry-run` prints the cost estimate and stops. Run it first.
- `just live-e2e --case B-007 --replay` replays the committed recording `evals/bank/live/B-007/model-recordings/` with no paid call and no live provider. CI runs this. A changed prompt, brief or config shows as `replay_miss` naming the stage, the role and the key, never as a pass. The committed B-007 recording is a synthetic fixture written by a fake provider (a `SYNTHETIC` file beside `model-recordings/` says so), and a replay says so on its `recordings:` line, so it is never mistaken for a real model run. A live run with `TILO_RECORD=1` removes that file; a run with an injected fake provider (the tests, the regen script) writes it.

## One live case (PowerShell, your own terminal)

Sign-in is Application Default Credentials only. Remove any API key first, then set the project, the live switch and the recording switch.

```powershell
Remove-Item Env:GOOGLE_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
$env:GOOGLE_CLOUD_PROJECT = "<your project id>"
# $env:GOOGLE_LOCATION = "global"    # optional; global is the default
just live-e2e --case B-007 --dry-run
$env:LIVE = "1"
$env:TILO_RECORD = "1"
just live-e2e --case B-007
```

Afterwards clear the switches: `Remove-Item Env:LIVE, Env:TILO_RECORD`.

- The default cap is 40 credits (US$0.20, from the prices file); `--max-credits N` changes it, at most 200. At the cap the run stops honestly (`stopped_at_cap`, exit 3), never sends a call the remaining budget cannot cover, and never shows a completion it did not reach.
- `--report-json path` also writes the report as JSON (no run content beyond the Story lines).
- With `TILO_RECORD=1` each model reply is saved, redacted (secrets, emails, phone numbers), with LF line endings, under `evals/bank/live/<case>/model-recordings/<role>/<key>.json`. To replace the synthetic fixture with the real run, delete `evals/bank/live/B-007/model-recordings` before the live run (otherwise old files with other keys stay beside the new ones). Review the diff, then commit it deliberately, so `--replay` then replays the real run. A prompt, template or config change (a new connector in `config/connectors.yaml` changes the Director prompt) needs a new recording: `uv run python evals/tests/regen_live_e2e_fixture.py` regenerates the synthetic fixture with no environment variable at all, through `tilo_evals.live_e2e.record_with_fake` (programmatic only; takes an injected fake provider, refuses a network adapter or anything not marked `SYNTHETIC_FAKE`, never reads the live switch; the CLI still refuses without the user's own). Commit the result.
- Exit codes: 0 the run ended as the case expects and every hard check holds; 1 a check failed, a different outcome, `failed` or `replay_miss`; 2 refused (one `REFUSED <code>: ...` line); 3 `stopped_at_cap`.
- A provider that rejects a request (HTTP 400, for example a thinking level its model does not take) ends the run as `rejected` (exit 1), with the reason the adapter already redacted, scrubbed again (project id, credential files, tokens, emails), cut to one line and 200 characters. Every other status prints its code only (`auth`, `permission`, `location`, `quota`, `unknown`), never the server's words.
- Director requests carry the role's `max_output_tokens` from `config/models.yaml` (16384 since BQ-PL02-1), or a 4096 floor when the role sets none (the Router's default of 1024 includes thinking tokens and can cut a plan short). The estimate uses the same cap, so its worst case (every Director call using its whole cap) is well above the default 40-credit cap; the meter, not the estimate, bounds the spend. Each call is quoted at its full cap and refused when that quote exceeds the credits left (about 12 credits for a Director call at 16384), so Director retries can stop a run before 40 credits are spent; rerun with `--max-credits 60` if that happens. A reply cut off at its cap ends the run with `provider call failed (director role): truncated`.
- A call that raised after it may have been sent (a blocked reply, a timeout) is counted in the meter at the Router's own quote (its input and the full output cap); a refused request (400, 429) is not billed and not counted.

## What the report says

Counts per stage and role (calls, tokens in and out, credits, latency), the outcome class, the event count, the structural checks of the generality bank (GEN-a) applied to the live run, and total credits against the cap. It lists what is faked on every run (`faked:` lines: the safety screen is trusted bank input only, connectors and the recipient are recording mocks, the Verifier's verdict is recorded but not acted on). Planning credits come from this meter, because the planning events carry 0 (#327): the meter, not the events, is the spend. The claim scope is a structural pass rate (GEN-11), not output quality. It says `safety: trusted_bank_input (by design; Model Armor is the safety role's live adapter, FR-INT-02, #450)`: a live run screens intake with a named screen that accepts only the committed case's own text and refuses anything else (BQ-LE2E-5), so nothing untrusted can reach a live model.

## Any topic (`just live-run`)

`just live-run --topic "<your request>"` (or `--topic-file F`) runs your own text through the same runner, meter, cap, switch refusals and report. Run `--dry-run` first (estimate and safety screen, no call), then set `$env:LIVE = "1"` and run it again.

- The topic is untrusted: the `safety` role (Model Armor, `armor-default`, template `tilo-default`) screens it before any model call, and intake and typed answers again. No such role or a screen that cannot run gives `REFUSED safety_unavailable`, which lists what it needs (`GOOGLE_CLOUD_PROJECT`, `TILO_MODEL_ARMOR_LOCATION` default `asia-southeast1`, user ADC, the Model Armor API); a flagged topic gives `REFUSED unsafe_topic` with a category only.
- You answer in the terminal: questions (a number, your words, or empty for the default), the approach and every gate card (y/n and a reason; "n" holds, nothing is sent). `--auto-answer` and `--auto-approve-t1t2` (T1/T2 only; a T3 gate always asks) are labelled as the CLI, not a person.
- The report says `expected: none`, runs the structural checks, prints who decided what and each unit's text (`deliverable:` or `draft (not delivered):`). Connectors stay recording mocks. Exit 0 completed, held or declined with the hard checks holding; 1 otherwise; 2 refused; 3 cap. `TILO_RECORD=1` saves to the git-ignored `evals/bank/live/adhoc/<hash>/`.
