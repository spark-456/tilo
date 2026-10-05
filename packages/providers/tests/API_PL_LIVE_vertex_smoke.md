# API pinned by the PL_LIVE Vertex smoke tests (ticket PL-LIVE-vertex-smoke, Req: PL-02)

The tests in `test_PL_LIVE_*.py` are the definition of done. This file is the interface they call; do not rename.
No contract change is needed: everything below is Python in `packages/providers` (`GenerateRequest` and the
adapter are code, not `contracts/`). Location uses the existing `GOOGLE_LOCATION` variable (see "Open point").

## Files

| Path | What |
| --- | --- |
| `packages/providers/src/tilo_providers/vertex_smoke.py` | `run_vertex_smoke`, `main`, constants, exceptions. Importable with no Google library installed or imported. |
| `packages/providers/scripts/live_vertex_smoke.py` | Thin entry point: `raise SystemExit(main())`. `--help` works with no live switch. |
| `packages/providers/src/tilo_providers/interfaces.py` | `GenerateRequest.thinking_level` (new optional field). |
| `packages/providers/src/tilo_providers/google_adapter.py` | maps `thinking_level`, counts thought tokens as output, `redact()`. |

## Module `tilo_providers.vertex_smoke`

```python
SMOKE_ROLES = ("director", "lead", "specialist", "verifier", "writer", "narrator", "autopilot")  # run in this order
SMOKE_PROMPT: str  # fixed, synthetic, <= 40 words, one line, no environment text
THINKING_MINIMUM = None  # corrected 5 Oct 2026: Vertex answers 400 to "minimal"; no level is the verified setting
DEFAULT_MAX_OUTPUT_TOKENS = 64
HARD_MAX_OUTPUT_TOKENS: int  # 64 <= x <= 256; a flag above it (or below 1) is refused
DEFAULT_MAX_TOTAL_CREDITS: float  # 0 < x <= 2.0 (<= US$0.01)
HARD_MAX_TOTAL_CREDITS: float  # DEFAULT <= x <= 100.0 (US$0.50); a flag above it (or <= 0) is refused


@dataclass
class RoleRow:  # one served call
    role: str
    profile_id: str
    fallback_from: str | None  # primary id when a fallback served it, else None
    latency_ms: float
    tokens_in: int
    tokens_out: int
    credits: float


@dataclass
class SmokeReport:
    rows: list[RoleRow]
    total_credits: float
    ceiling_credits: float
    max_output_tokens: int
    mode: Literal["live", "replay"]


class SmokeRefused(Exception):  # a precondition failed; nothing was sent
    code: str  # see "Codes"
    missing: list[str]  # prices_unset only: the keys to confirm, in the order below


class SmokeFailed(Exception):  # a role failed; earlier rows are in .report
    role: str
    code: str
    fix: str
    report: SmokeReport


def run_vertex_smoke(
    *,
    environ: Mapping[str, str] | None = None,  # None -> os.environ
    models_path: Path | str | None = None,  # None -> tilo_providers.config.resolve_models_path()
    prices_path: Path | str | None = None,  # None -> <repo>/config/prices.yaml
    fixtures_dir: Path | str | None = None,  # None -> <repo>/fixtures
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    max_total_credits: float = DEFAULT_MAX_TOTAL_CREDITS,
    replay: bool = False,
) -> SmokeReport: ...


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int: ...
```

Flags of `main`: `--max-output-tokens N`, `--max-credits X`, `--replay`, `--models-file PATH`, `--prices-file PATH`,
`--fixtures-dir PATH`. Exit codes: 0 done, 1 a role failed or the ceiling stopped the run, 2 refused before any call.

### Order of checks (live)

1. `environ.get("LIVE") == "1"` (exactly; `"true"`, `"0"`, `""`, `" 1"` all refuse). This is the FIRST and only
   thing looked at: no other environ key, no config file, no import of `google.*`/`vertexai`/`tilo_providers.google_adapter`,
   no credential file. Else `SmokeRefused("live_not_enabled")`.
2. Caps in range (`cap_out_of_range`).
3. Config loaded; `GOOGLE_API_KEY` / `GEMINI_API_KEY` present and non-empty -> `api_key_present`
   (names the variable, never the value; ADC only).
4. `GOOGLE_CLOUD_PROJECT` missing -> `missing_project` (names the variable).
5. Prices: `status != "set"` -> `prices_unset`. `.missing` is `["status", "effective_date", "source"]` followed by
   `"<profile>.input", "<profile>.output"` for every profile the seven roles use (primary, fallback, cascade), sorted by
   profile id. No number is ever printed or computed from anywhere but the prices file.
6. Only now, one `Router.generate(role, request, budget=<credits left>)` per role.

`replay=True` (`--replay`) skips the live gate and the project/key checks, never goes live: if `LIVE == "1"` it
refuses `replay_with_live`. It serves each role from `<fixtures>/model-recordings/<role>/<key>.json`, with no Google
import and no network. Prices are still required (credits are printed). A missing recording -> `SmokeFailed("replay_miss")`.

### The request (one per role, through the normal router; the role-to-profile mapping is whatever the models file says)

```python
GenerateRequest(prompt=SMOKE_PROMPT, max_output_tokens=<cap, default 64>,
                thinking_level=THINKING_MINIMUM)  # None: no thinking config is sent
```

Nothing else (no system text, tools, schema, json_mode). The smoke code names no model id and no profile id. The
level is decided from the role's PRIMARY profile caps; the role's configured `thinking` (director: high) is NOT used.
A fallback profile gets the same request, so the adapter ignores `thinking_level` for a profile without the `thinking`
capability (see below): the SDK sees no thinking config for any profile (a live run showed `minimal` is a 400 for the director profile).

The Vertex client is whatever the router builds: `genai.Client(vertexai=True, project=$GOOGLE_CLOUD_PROJECT,
location=$GOOGLE_LOCATION or "global")`. Exactly those three arguments: ADC, never `api_key`, never a credentials object.

### Ceiling

`Router.generate(..., budget=ceiling - spent)` per role, so the router refuses (never sends) a call whose
estimate does not fit; the smoke turns that into `SmokeFailed("ceiling")` for that role and stops. Spend is the
router's, from reported usage, in credits (`credits = usd / prices.credit_usd`, `usd = (in*price_in + out*price_out)/1e6`).

### Output (stdout rows, stderr problems; every line ends with a newline, nothing else is printed)

```
role=director profile=flash-38 latency_ms=123.4 tokens_in=20 tokens_out=30 credits=0.1600
role=lead profile=flash-37 latency_ms=98.0 tokens_in=20 tokens_out=30 credits=0.0800 fallback_from=flash-38
total credits=1.2000 ceiling=50.0000
```

Row regex: `^role=(\w+) profile=(\S+) latency_ms=(\d+(\.\d+)?) tokens_in=(\d+) tokens_out=(\d+) credits=(\d+\.\d{4})( fallback_from=(\S+))?$`.
`total` is printed last, also after a failure (what was spent so far). `latency_ms` is the served attempt's wall time.

stderr, exactly these shapes:

```
REFUSED <code>: <one-line message>                        # exit 2
  confirm <key>                                           # prices_unset only, one per key of .missing, in order
FAIL role=<role> reason=<code>: <one-line message> Fix: <one-line hint>   # exit 1, ONE line
```

Codes. Refused: `live_not_enabled` (message names `LIVE`), `cap_out_of_range`, `api_key_present`, `missing_project`,
`prices_unset` (message names `config/prices.yaml`; no dollar amount, no price), `replay_with_live`.
Failed: `quota` (429 on every candidate, fix mentions quota), `permission` (403 PERMISSION_DENIED, fix mentions
`roles/aiplatform.user`), `api_disabled` (403 SERVICE_DISABLED / "has not been used", fix mentions
`aiplatform.googleapis.com`), `location` (404 NOT_FOUND, fix mentions `GOOGLE_LOCATION`), `auth` (401 or missing ADC, fix
mentions `gcloud auth application-default login`), `ceiling` (fix mentions `--max-credits`), `replay_miss` (fix mentions
`TILO_RECORD`), `rejected` (HTTP 400 or a `RequestError`; the message adds the adapter's redacted reason, scrubbed again,
one line, at most 200 characters; fix: adjust the role or profile settings), `unknown` (anything else). Classify by walking the `__cause__` chain of the `RouterError`
(status/message text and exception class name), check `api_disabled` before `permission`. The run stops at the first failed
role. No traceback, no header, no token, no `Authorization` text ever reaches stdout, stderr or logging (scrub the
server's message with the same redaction as recordings, or do not print it). The one exception is `rejected`: its
reason is printed on the same line after control and format characters are dropped and a labelled-value scrub (token, key,
secret, signature, Authorization/Bearer in plain, quoted or escaped-JSON form), scrub before the 200 character cap.

### Recordings

Live with `TILO_RECORD=1` (set by the user) is handled by the existing `RecordReplayProvider`: one file per role under
`<fixtures>/model-recordings/<role>/<key>.json`, `key = recording_key(role, profile_id, request)`. Without it nothing
is written. A failed call writes nothing.

## `GenerateRequest.thinking_level`

`thinking_level: Literal["minimal", "low", "medium", "high"] | None = None`. Default None, so `recording_key`
(which dumps with `exclude_none`) does not change for any existing request or recording. Any other value is a
`ValidationError`.

## `GoogleModelProvider` (google_adapter.py)

- `thinking_level` set -> `GenerateContentConfig(thinking_config=types.ThinkingConfig(thinking_level=<level>))`
  (the SDK's `ThinkingLevel` enum names are upper case; the tests accept either spelling, a dict or an object).
  Unset, or the profile has no `thinking` capability -> no `thinking_config` at all.
- `usage["output_tokens"] = candidates_token_count + (thoughts_token_count or 0)`; `input_tokens` and `total_tokens`
  unchanged. Thinking tokens are billed as output, so metering would otherwise under-report.
- `redact(text)` replaces Google OAuth access tokens (`ya29.` followed by token characters) and Google API keys
  (`AIza` followed by 35 key characters) with `[redacted]`; other text is returned unchanged.

## Open point (for the orchestrator)

Location is not a field of `contracts/providers.schema.json` `$defs.profile` (`additionalProperties: false`), so
"location from config" is read as the existing `GOOGLE_LOCATION` environment variable defaulting to `global` (PRD 6.5;
`factory._build_live_provider` already does this). If the user wants it in `config/models.yaml`, that is a contract change.
