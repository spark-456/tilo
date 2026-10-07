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

`just live-run` asks for your request at a prompt (finish with an empty line); `just live-run-file <path>` reads it from a UTF-8 file. The topic never goes on the `just` command line, so no shell ever sees it; the recipes take flags only (`--dry-run`, `--auto-answer`, `--auto-approve-t1t2`, `--max-credits N`) and `just` refuses anything else. To pass the text yourself, call the script directly in PowerShell: `uv run python evals/scripts/live_run.py --topic '<your request>'` (single quotes: PowerShell expands nothing inside them). It runs through the same runner, meter, cap, switch refusals and report as `live-e2e`. Run `just live-run --dry-run` first: it prints the estimate and the topic's length and SHA-256, and names the safety screen (it does not call it). Then set `$env:LIVE = "1"` and run `just live-run` again.

- The topic is untrusted: the `safety` role (Model Armor, `armor-default`, template `tilo-default`) screens it before any model call, and intake and typed answers again. No such role, or a screen that fails, gives `REFUSED safety_unavailable` (never a weaker screen), which lists what it needs (`GOOGLE_CLOUD_PROJECT`, `TILO_MODEL_ARMOR_LOCATION` default `asia-southeast1`, user ADC, the Model Armor API); a flagged topic gives `REFUSED unsafe_topic` with a category only.
- You answer in the terminal: questions (a number, your words, or empty for the default), the approach and every gate card (y/n and a reason; "n" holds, nothing is sent). A gate card shows exactly what is sent, to whom and where. A T3 gate (or one with no tier) can be approved only at an interactive terminal; piped input holds it. `--auto-answer` and `--auto-approve-t1t2` (T1/T2 only) are labelled as the CLI, not a person. Model text is printed without control or bidi characters.
- The report says `expected: none`, runs the structural checks, prints who decided what and each unit's text (`deliverable:` or `draft (not delivered):`). Connectors stay recording mocks unless you pass `--real-connectors` (below). Exit 0 completed, held or declined with the hard checks holding; 1 otherwise; 2 refused; 3 cap. `TILO_RECORD=1` saves to the git-ignored `evals/bank/live/adhoc/<hash>/` (`--recordings-dir` must stay under it).

## Real connectors, read only (`--real-connectors`, CL-LIVE-1)

`just live-e2e --real-connectors` and `just live-run --real-connectors` swap the recording mocks for your own Gmail, Drive and Calendar, **read only**: every write door (send, draft, save, invite) refuses with "writes are not enabled until CL-LIVE-2", so nothing leaves your accounts. Scopes are the minimum `config/connectors.yaml` already declares: Gmail `gmail.readonly` and `gmail.compose`, Drive `drive.file`, Calendar `calendar.readonly`; the Gmail send scope is never requested. Note that `gmail.compose` can send mail at the token level, so read-only is enforced by the wrapper (every write door refuses), not by the scope; CL-LIVE-3 should request `gmail.readonly` only until CL-LIVE-2.

- `--dry-run --real-connectors` needs no switch: it prints `real-connector <id>: scopes=... mode=read_only` per connector and builds no client, broker or listener.
- A live run needs `LIVE=1` exactly, no `CI` or Cloud Run marker, real providers (not `--replay`) and a token for all three connectors; otherwise it exits 2 (`REFUSED real_connectors_not_live`, `real_connectors_fake_providers`, `real_connectors_no_token` or `real_connectors_failed`) before any model call and never falls back to the mocks. The consent flow that supplies the tokens is CL-LIVE-3's; until then the default refuses with `real_connectors_no_token`.
- The report says `side_effects: real_read_only` and prints `connectors: real_read_only (...)`; the recipient is still the dev stand-in. What the adapters read is never recorded, logged, printed or put in an event. No `.env` is read or written.

## Real connectors, writes behind a typed approval (`--allow-writes`, `--allow-send`, CL-LIVE-2)

`just live-run --real-connectors --allow-writes` lets the run really **create a Gmail draft** or **save a file to Drive** (`drive.file`, the Tilo folder). Add `--allow-send` and a gated Gmail **send** is possible too (off by default). Reads are as above; Calendar, Lovable and the meeting host still refuse every write. Use the test account (`tilotesting@gmail.com`), never the bot or Owner account (BQ-CLLIVE-2).

- A write goes out only if all hold: the step went through the outbox and the policy engine (a T3 action always asks a person); **you typed `yes`** (exactly that word; `y`, Enter, a flag or piped input never count) at an interactive terminal on the gate card; the card showed the exact recipients, destination, subject and a 300-character preview (secrets redacted); the content is byte-for-byte what you saw (a changed recipient, body or destination needs a new approval); the token for that scope exists. `--auto-approve-t1t2` does not apply to a real write. Hold, `no`, EOF or no terminal: nothing is sent and the run ends held.
- Exactly once: an approval covers one entry; a retry after a lost answer finds the draft by its marker and makes no second one.
- The run's stand-in destination `thread-dev-1` means "a new message, no thread" for Gmail and "the Tilo folder" for Drive; recipients are the run's stand-in (`dev.recipient@example.com`) until a real resolver exists, so a draft or send goes to that address.
- `live-e2e` has no person, so `--allow-writes` is refused there (`allow_writes_needs_a_person`). `--allow-writes` needs `--real-connectors` (`allow_writes_needs_real_connectors`); `--allow-send` needs `--allow-writes` (`allow_send_needs_allow_writes`). All the read-only guards apply (LIVE=1, not CI or Cloud Run, not replay).
- `--dry-run --real-connectors --allow-writes` prints `real-writes: write_gated ...`, each connector's scopes and mode, and one `real-write <id> <action>: typed terminal approval` line per gated write; nothing is built. Scopes: drafts `gmail.compose` (+ `gmail.readonly` for the duplicate lookup); the send scope only with `--allow-send`; Drive `drive.file`.
- The report says `side_effects: real_write_gated` (or `real_write_gated_send`) and prints `connectors: real_write_gated (...)`. Content appears only on the terminal card; never in a recording, event, log or report.
