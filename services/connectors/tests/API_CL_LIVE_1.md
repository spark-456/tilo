# API pinned by the CL-LIVE-1 tests (CONNECTORS-LIVE slice 1, Req: CL-LIVE-1)

User wish, 7 Oct 2026: "agents should be allowed to work with connectors". In a local live run (`just live-e2e`,
`just live-run`) the connector adapters are today recording mocks (`tilo_api.dev_run.mock_adapters()`). The flag
`--real-connectors` swaps them for REAL Google connectors using the user's own OAuth token, read-only in this slice.
The tests are the definition of done; this file is the interface they call. Do not rename.

Slice 1 is the factory and the guards only. Out of scope: the terminal write gate and `--allow-send` (CL-LIVE-2), the
consent flow and the token runbook (CL-LIVE-3), any unit that actually reads a mailbox during a run. No contract change
is needed: this is Python in `services/connectors`, `evals/`, one justfile comment and docs.

Tests: `services/connectors/tests/test_CL_LIVE_1_*.py` (helpers `_cl_live_lib.py`) and
`evals/tests/test_CL_LIVE_1_real_connectors_flag.py` (helpers `_cl_live_evals_lib.py`).
Run: `uv run pytest services/connectors -k CL_LIVE_1 -q` and `uv run pytest evals -k CL_LIVE_1 -q`.

## Files

| Path | What |
| --- | --- |
| `services/connectors/src/tilo_connectors/real.py` | New. `real_adapters`, `real_connector_plan`, `REAL_SCOPES`, `READ_METHODS`, `RealConnectorsRefused`, `RealWritesDisabled`. |
| `evals/src/tilo_evals/live_e2e.py`, `live_topic.py` | The flag, the guards in the run, the factory seam, the printed lines. |
| `justfile`, `docs/live-e2e.md` | `--real-connectors` in the documented flag lists (the comment above `live-run`; the doc's flag section). |

Constraints on `real.py` that the tests scan for: it never names a side-effect method as an attribute or a call
argument (SEC-03 static scan: it may *define* `execute_side_effect`, nothing may call it but `outbox.py`); its text
holds none of these fragments, not even in a comment: `.env`, `dotenv`, `gmail.send`, `gmail.modify`, `mail.google.com`,
`gmail.metadata`, `gmail.insert`, `gmail.labels`, `gmail.settings`, `drive.readonly`, `drive.metadata`, `drive.appdata`,
`drive.photos`, `calendar.events`, `calendar.settings`. It wraps the transport in no `RecordingTransport`.

## Module `tilo_connectors.real`

```python
REAL_SCOPES: Mapping[str, tuple[str, ...]] = {
    "gmail": ("https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"),
    "google_drive": ("https://www.googleapis.com/auth/drive.file",),
    "google_calendar": ("https://www.googleapis.com/auth/calendar.readonly",),
}   # the minimum config/connectors.yaml already declares; order = the plan's order; derive from config, never widen

READ_METHODS: Mapping[str, frozenset[str]] = {
    "gmail": {"list_threads", "search_threads", "get_thread", "get_message", "list_labels", "recent_inbox", "list_history"},
    "google_drive": {"get_metadata", "list_folder", "download"},
    "google_calendar": {"list_events"},
}   # exactly the public methods of the returned Google adapters, besides `id`, `sent` and `execute_side_effect`

class RealConnectorsRefused(Exception):   # fixed text; `.code` below; never a token, secret, id from config or mail text
    code: str
class RealWritesDisabled(SideEffectRefused):   # str(exc) == "writes are not enabled until CL-LIVE-2"

def real_connector_plan(registry: ConnectorRegistry) -> list[dict]
    # one row per Google connector in REAL_SCOPES order: {"connector": str, "scopes": tuple[str, ...], "mode": "read_only"}

def real_adapters(
    broker: TokenBroker, registry: ConnectorRegistry, transport: Transport, *,
    user_id: str,
    environ: Mapping[str, str] | None = None,       # None: os.environ. LIVE and the CI/Cloud Run markers are read here
    mode: str = "live",                              # anything but "live" (replay, dry-run, record, "") is refused
    providers_fake: bool = False,                    # True is refused
    picks: InMemoryPicks | None = None,              # Drive: the ids the user typed; None: an empty set
    clock: Callable[[], str] | None = None,          # RFC 3339; None: the wall clock
    emit: Callable[[dict], None] | None = None,      # connection.* parts; None: dropped
    sleep: Callable[[float], None] | None = None,    # retry waits; None: time.sleep
) -> dict[str, adapter]
```

Result: the same dict shape as `dev_run.mock_adapters()`: one entry for every id in `registry.ids()`.

* `gmail`, `google_drive`, `google_calendar`: a read-only wrapper over the existing `GmailAdapter`, `DriveAdapter`,
  `CalendarAdapter`, built on the injected `broker` and `transport`. Its public callables are `READ_METHODS[id]` plus
  `execute_side_effect`; `id` is the connector id; `sent` is an empty sequence (the run's `bank_run.drive` calls
  `len(adapter.sent)` on every adapter). `watch` and `stop_watch` (POSTs) are not exposed; `send_reply` does not exist.
  The declaration given to the Gmail adapter has no `send` scope. Reads need no grant and no gate.
* every other id (`lovable`, `meeting_host`): a stub with `id`, `sent` and the refusing `execute_side_effect` only.
* `execute_side_effect(entry, grant)` of every adapter raises `RealWritesDisabled` for any entry and any grant (even
  `None`), before the broker, the transport, the artifacts or the grant are touched. Through the outbox
  (`enqueue` + `dispatch_due`) a `send_email`, `create_draft`, `save_file` or `save_as_google_file` entry ends `failed`,
  with no request of any kind sent and no `data.transfer`.

### Guards (all raise `RealConnectorsRefused`; nothing is sent and no token is asked for, except `no_token`)

| `code` | When |
| --- | --- |
| `live_not_enabled` | `environ["LIVE"] != "1"` exactly (`"true"`, `"01"`, `" 1"`, `"1 "`, `""` all refuse). The switch is read from `environ` only; never assumed, never set. |
| `ci_refused` | `CI` or `GITHUB_ACTIONS` non-empty in `environ` or in `os.environ`. |
| `deployed_refused` | `K_SERVICE` or `CLOUD_RUN_JOB` present (even empty) in `environ` or in `os.environ`. |
| `not_live_mode` | `mode != "live"`. |
| `fake_providers` | `providers_fake` is true. |
| `replay_transport` | `transport` is a `recording.ReplayTransport` or `recording.RecordingTransport`. |
| `scope_widened` | a non-`send` capability of `gmail`, `google_drive` or `google_calendar` in the given registry declares a scope outside `REAL_SCOPES[id]`. The shipped `send` scope is declared but never requested. |
| `no_token` | any of the three Google connectors yields no token for its first `REAL_SCOPES` scope: not connected, expired or refresh rejected, or a grant without that scope. Checked with `broker.access_token_for_adapter(user_id, id, required_scopes=[scope])`; no Google request. No fallback to a mock. |

Messages are fixed text. They hold no token, client secret, mail/Drive/Calendar text, config value or traceback chain
that does (tests scan `str`, `repr`, `.code` and the formatted traceback).

Other rules: it sets nothing in `os.environ`; it never opens, reads or writes a `.env`; it adds no logging; real
adapter output is not written anywhere (no recording, fixture, cache or log; events are the broker/adapter `connection.*`
parts with counts and ids only, e.g. `connection.rate_limited` `{connector, retry_after_s}`).

## The run: evals

New flag `--real-connectors` (`store_true`, dest `real_connectors`, default false) on `live_e2e._parser()` and on the
`live_run` parser (`live_topic.main`). Documented in the comment above the `live-run` recipe and in `docs/live-e2e.md`.

```python
# tilo_evals.live_e2e
def run_live_e2e(..., real_connectors: bool = False,
                 real_connectors_factory: Callable[[], dict[str, Any]] | None = None) -> LiveE2EReport
def main(argv=None, *, environ=None, live_provider_factory=None, safety=None,
         real_connectors_factory: Callable[[], dict[str, Any]] | None = None) -> int
# tilo_evals.live_topic
def main(argv=None, *, environ=None, live_provider_factory=None, safety=None, read=None, tty=None,
         real_connectors_factory: Callable[[], dict[str, Any]] | None = None) -> int
def run_topic(..., real_connectors: bool = False, real_connectors_factory=None) -> LiveE2EReport
```

`real_connectors_factory` is a zero-argument callable returning the adapters dict (what `real_adapters(...)` returns).
It is the only way the run gets real adapters. `None` with the flag on means the default: build `LiveTransport`,
`LiveHttpClient`, the broker and the consent flow in memory (BQ-CLLIVE-1); that default is CL-LIVE-3's and is not
exercised by these tests (no network), so until it lands it may refuse with `real_connectors_no_token`.

Order and behaviour, flag on:

1. The existing gate first (`live_not_enabled`, `ci_refused`, `deployed_refused`, ... exactly as without the flag).
2. `--replay` refuses: `real_connectors_not_live`. `run_live_e2e(fake_record=True, real_connectors=True)` (the
   `record_with_fake` path) refuses: `real_connectors_fake_providers`, before the factory is called.
3. `--dry-run`: no switch needed, the factory is not called, no client, broker or listener is built, no model call.
   Stdout gets, besides the estimate:
   `real-connectors: read_only (dry run: nothing built, nothing sent)` and one line per connector of
   `real_connector_plan`: `real-connector <id>: scopes=<url>,<url> mode=read_only` (comma-joined, no spaces). Exit 0.
   (`live-run --dry-run` prints them after its `safety screen named` line.)
4. Live: the factory is called exactly once, after the gate and before the first model call and before the
   Director's intake (the safety screen of `live-run` is not a model call of the run). The returned dict replaces
   `dev_run.mock_adapters()` in `_app` (`deps.get_connector_adapters`).
5. `RealConnectorsRefused` from the factory becomes `LiveE2ERefused("real_connectors_<code>", fixed text)`
   (e.g. `real_connectors_no_token`); any other exception becomes `LiveE2ERefused("real_connectors_failed", fixed
   text)` and its words are never printed. Both: exit 2, `REFUSED <code>: ...` on stderr, no model call, no report, no
   `outcome=` line, no run on mocks.
6. Report: `side_effects == "real_read_only"` (default stays `"mock_only"`); stdout line (before `outcome=`)
   `connectors: real_read_only (gmail, google_drive, google_calendar)` listing the real ids; the `faked:` list drops
   "connectors and recipient: recording mocks" and keeps a line naming the recipient as the dev stand-in. In
   `live-run` the report's `faked` is overwritten from `TOPIC_FAKED`: that override must follow the same rule.
7. Without the flag nothing changes, even if a factory is passed (it is never called).

Refusal codes added: `real_connectors_not_live`, `real_connectors_fake_providers`, `real_connectors_no_token`,
`real_connectors_failed`; any other `RealConnectorsRefused.code` maps to `real_connectors_<code>`.

Privacy in the run: nothing the real adapters read is written to a recording (`TILO_RECORD=1` included), an event, the
report (`--report-json`), a log, stdout or stderr; only counts and redacted summaries may appear. No `.env` is opened,
with the flag or without it.

## Test map

| Acceptance criterion (ticket scope) | Tests |
| --- | --- |
| 1 factory, dict shape of `mock_adapters()` | `test_CL_LIVE_1_returns_one_adapter_per_configured_connector_in_the_mock_adapters_shape`, `..._real_adapters_signature_is_the_pinned_one`, `evals: ..._real_adapters_module_is_the_one_the_run_uses` |
| 2 read-only by construction; reads reach the transport with no gate | `..._gmail_reads_reach_the_transport_and_need_no_gate`, `..._drive_read_of_a_typed_id_...`, `..._calendar_read_reaches_...`, `..._every_adapters_write_door_refuses_with_the_named_error_...`, `..._a_plan_that_asks_for_a_send_or_a_save_through_the_outbox_changes_nothing_at_google[*]`, `..._the_public_surface_is_the_pinned_reads_and_the_one_refusing_door`, `..._no_non_get_request_goes_out_over_the_whole_read_surface`, `..._real_module_exists_and_never_references_a_side_effect_name` |
| 3 guards (LIVE exactly "1" and the flag; replay, fake providers, dry-run, CI; no `.env`; fail closed; clean messages) | `test_CL_LIVE_1_guards.py` (all), evals: `..._without_live_1_...`, `..._only_exactly_1_counts_...`, `..._in_ci_or_on_cloud_run_...`, `..._replay_with_the_flag_...`, `..._the_fake_provider_path_...`, `..._a_missing_token_refuses_...`, `..._any_other_connector_failure_...`, `..._the_run_never_reads_or_writes_a_dotenv_file`, `..._the_entry_points_exit_non_zero_without_live_1_...` |
| 4 scopes pinned, no widening | `test_CL_LIVE_1_scopes_and_privacy.py` scope tests, `..._refuses_a_registry_that_widens_a_scope_...` |
| 5 privacy | `..._read_content_reaches_no_event_log_stdout_or_file`, `..._events_from_real_reads_carry_counts_and_ids_only`, `..._the_adapters_do_not_wrap_the_transport_in_a_recorder`, evals: `..._what_the_real_adapters_read_is_in_no_recording_event_report_log_or_output`, `..._the_reports_events_hold_no_connector_content` |
| 6 flag wired and documented; `--dry-run` plan | evals: `..._flag_is_parsed_and_off_by_default`, `..._run_live_e2e_takes_the_flag_and_the_factory_seam`, `..._flag_is_in_the_documented_flag_lists`, `..._dry_run_prints_the_plan_...`, `..._with_the_guards_passed_the_run_uses_real_adapters_...`, `..._the_default_run_is_unchanged_...` |
| 7 decision defaults | `docs/open-questions.md` BQ-CLLIVE-1 to BQ-CLLIVE-5 (docs only) |

## Ambiguities resolved by default (also BQ-CLLIVE-5)

* "Replay/fake providers": replay and dry-run modes, `fake_record`, `providers_fake=True` and a recorded transport
  refuse. An injected `live_provider_factory` (the test seam; the CLI cannot inject) stays allowed, otherwise the pass
  path could not be tested.
* `lovable` and `meeting_host` are in the dict as refusing stubs so the map has the mock map's shape.
* "A token can be obtained" means all three Google connectors, each for its first pinned scope; no subset option.
* Scopes: the pinned set is the config's own minimum; the config's `send` capability stays declared but is never
  requested. A wider scope in any other capability is `scope_widened`.
* Nothing in a run reads a connector yet (units call models only), so privacy is pinned on what the factory and the
  adapters emit; no summariser is added in this slice.
