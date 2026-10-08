"""Shared helpers for the VERTEX-EVAL-1 evals-half tests (PR 1b; docs/design/VERTEX-EVAL-1.md section 3, ADR-0033).

Nothing here touches a network or Google auth. The judge is a recording fake `EvalProvider` handed to the CLI through
the one seam these tests pin (`main(argv, environ=..., eval_provider=...)`); the live switch is only ever set inside a
test's own patched environment (`_live_e2e_lib.env`), and a model id never appears (PL-01: judge model strings here
are made up). Every fake repo lives under `tmp_path`, never `evals/cases`.

Names the builder must match (all pinned by these tests, see the report):
  * CLI: `python -m tilo_evals vertex-eval export|run`, flags as in the design, plus `--settings P` on both
    (like `generate`), which defaults to `evals/vertex_eval.yaml`.
  * Test seam: `tilo_evals.__main__.main(argv, *, environ=None, eval_provider=None)`. An injected provider replaces
    `build_eval_provider` (live and `--fake`); the gate, the cap check, config and price checks still run first.
  * Refusals: stderr `REFUSED <code>: <text>` (as `generate`), exit 2; codes `live_not_enabled`, `ci_refused`,
    `deployed_refused`, `api_key_present`, `missing_project` (all from `live_e2e._gate`), `cap_out_of_range`,
    `config_invalid`, `cap_too_small`.
  * Pairs file (`evals/vertex-eval/pairs.local.yaml`): mapping with `candidate_label`, `baseline_label` (null when no
    baseline), `pairs` (list of `id`, `prompt`, `context`, `candidate_response`, and `baseline_response` only when a
    baseline exists) and `skipped` (list of `id`, `reason`).
  * Rubrics (`prompts/eval_judge/plan_pairwise.md`, `plan_groundedness.md`) use the evaluation service's own
    placeholders `{prompt}`, `{context}`, `{response}` (and `{baseline_model_response}` for pairwise), each once,
    each inside a `<<<NAME ... NAME>>>` fence.
  * stdout lines: `estimate credits=<4dp> cap=<4dp>` and `fit <k> of <n> cases` (dry run), `total credits=<4dp>
    cap=<4dp>` (after a run).
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml
from _live_e2e_lib import (  # noqa: F401  (re-exported for the tests)
    PROJECT,
    REPO_ROOT,
    Invocation,
    _capture_logs,
    env,
    network_guard,
)
from tilo_providers.interfaces import EvalProvider, EvalRequest, EvalScore

PROMPTS = REPO_ROOT / "prompts" / "eval_judge"
REAL_SETTINGS = REPO_ROOT / "evals" / "vertex_eval.yaml"
REAL_SETTINGS_SCHEMA = REPO_ROOT / "evals" / "vertex_eval.schema.json"
PAIRWISE_FILE, GROUNDED_FILE = "plan_pairwise.md", "plan_groundedness.md"
PAIRWISE_ID, GROUNDED_ID = "plan_pairwise", "plan_groundedness"
LIVE_ENV = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}  # the switch only ever lives in a patched environment
TRUNCATED = " [truncated]"
PAIR_PLACEHOLDERS = ("prompt", "context", "response", "baseline_model_response")

SETTINGS: dict[str, Any] = {  # the design's values (3.1), the ones the real evals/vertex_eval.yaml must hold
    "max_credits": 18,
    "max_cases": 20,
    "assumed_output_tokens": 512,
    "overhead_tokens": 400,
    "field_chars": {"prompt": 1500, "context": 3000, "response": 2500},
    "metrics": {
        "pairwise": {"id": PAIRWISE_ID, "template": PAIRWISE_FILE},
        "groundedness": {"id": GROUNDED_ID, "template": GROUNDED_FILE},
    },
}


# --- a recording judge ---------------------------------------------------------------------------------------------


class RecordingEvalProvider(EvalProvider):
    """A fake judge that records every request. Texts that start `CAND` are the candidate's, `BASE` the baseline's, so
    a pairwise verdict can be stated in real terms (`prefer`: case id -> candidate | baseline | tie) whatever position
    the runner sent them in. Pointwise scores come from `score_of(request)`; `fail_at` (1-based call number) raises."""

    def __init__(
        self,
        *,
        prefer: Mapping[str, str] | None = None,
        default_choice: str = "candidate",
        score_of: Callable[[EvalRequest], float] | None = None,
        fail_at: int | None = None,
        error: Exception | None = None,
        explanation: str = "recorded judgement",
    ) -> None:
        self.requests: list[EvalRequest] = []
        self.prefer = dict(prefer or {})
        self.default_choice = default_choice
        self.score_of = score_of or (lambda _request: 1.0)
        self.fail_at, self.error, self.explanation = fail_at, error, explanation

    def _evaluate(self, request: EvalRequest) -> EvalScore:
        self.requests.append(request)
        if self.fail_at is not None and len(self.requests) == self.fail_at:
            raise self.error or RuntimeError("unexpected")
        if request.kind == "pairwise":
            side = self.prefer.get(request.item.id, self.default_choice)
            if side == "tie":
                return EvalScore(choice="tie", explanation=self.explanation)
            candidate_is_response = request.item.response.startswith("CAND")
            wins_as_response = (side == "candidate") == candidate_is_response
            return EvalScore(choice="candidate" if wins_as_response else "baseline", explanation=self.explanation)
        return EvalScore(score=self.score_of(request), explanation=self.explanation)

    def kinds(self) -> list[str]:
        return [r.kind for r in self.requests]


class Boom(EvalProvider):
    """A provider that must never be called."""

    def _evaluate(self, request: EvalRequest) -> EvalScore:
        raise AssertionError("no provider call was expected")


# --- files ---------------------------------------------------------------------------------------------------------


def write_bytes(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def write_yaml(path: Path, data: Any) -> Path:
    return write_bytes(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def write_settings(tmp_path: Path, name: str = "settings.yaml", **over: Any) -> Path:
    return write_yaml(tmp_path / name, {**json.loads(json.dumps(SETTINGS)), **over})


def write_models(
    tmp_path: Path,
    *,
    provider: str = "fake",
    profile: str = "judge-fake",
    model: str = "zz-judge-model-under-test",
    role: bool = True,
    name: str = "models.yaml",
) -> Path:
    roles: dict[str, Any] = {"safety": {"primary": profile, "fallback": profile}}
    if role:
        roles["eval_judge"] = {"primary": profile, "fallback": profile}
    data = {
        "example": True,
        "profiles": {profile: {"provider": provider, "model": model, "context": 1000000, "caps": []}},
        "roles": roles,
        "rules": {"deny": []},
    }
    return write_yaml(tmp_path / name, data)


def write_prices(
    tmp_path: Path,
    *,
    profile: str = "judge-fake",
    input_rate: float = 1.0,
    output_rate: float = 5.0,
    credit_usd: float = 0.005,
    status: str = "set",
    with_profile: bool = True,
    name: str = "prices.yaml",
) -> Path:
    data = {
        "status": status,
        "effective_date": "2026-10-08",
        "source": "Test fixture only. Not a real price page.",
        "currency": "USD",
        "credit_usd": credit_usd,
        # without the judge's own row the loader must refuse (PL-06): a different profile keeps the file valid
        "profiles": {(profile if with_profile else "other-profile"): {"input": input_rate, "output": output_rate}},
    }
    return write_yaml(tmp_path / name, data)


def case_doc(
    case_id: str,
    *,
    brief: str,
    director: Any,
    files: list[dict[str, str]] | None = None,
    answers: dict[str, str | None] | None = None,
    title: str = "A case",
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": case_id,
        "title": title,
        "domain": "research",
        "shapes": ["single_deliverable"],
        "brief": brief,
        "director": director,
        "expect": {"outcome": "completed"},
    }
    if files:
        doc["files"] = files
    if answers:
        doc["answers"] = answers
    return doc


def director_of(side: str, case_id: str) -> dict[str, Any]:
    """Plain ASCII Director output, different for the two sides, free of anything a redactor would touch."""
    return {
        "brief": {"goal": f"{side} reading of {case_id}"},
        "approaches": "standard",
        "plan": {"units": [{"id": "U1", "title": f"{side} first step for {case_id}"}]},
    }


NO_OUTPUT = {"brief": None, "approaches": None, "plan": None}


def write_case(folder: Path, case_id: str, **kw: Any) -> Path:
    return write_yaml(folder / f"{case_id}.yaml", case_doc(case_id, **kw))


def write_side(folder: Path, side: str, ids: list[str], **over: Any) -> Path:
    """A bank-format folder: one case per id, the same brief on both sides, a Director output that names the side."""
    folder.mkdir(parents=True, exist_ok=True)
    for case_id in ids:
        kw = {
            "brief": f"Brief for {case_id}: plan a small neighbourhood event.",
            "director": director_of(side, case_id),
        }
        write_case(folder, case_id, **{**kw, **over})
    return folder


def compact(director: Any) -> str:
    return json.dumps(director, sort_keys=True, separators=(",", ":"))


def pair_row(
    case_id: str, *, baseline: bool = True, size: int = 40, prompt: str | None = None, context: str = ""
) -> dict[str, Any]:
    """A hand-made pairs-file row. Equal-sized texts on every row, so every row quotes the same."""
    pad = "x" * size
    row: dict[str, Any] = {
        "id": case_id,
        "prompt": prompt if prompt is not None else f"Brief for {case_id}",
        "context": context,
        "candidate_response": f"CAND plan {case_id} {pad}",
    }
    if baseline:
        row["baseline_response"] = f"BASE plan {case_id} {pad}"
    return row


def write_pairs(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    *,
    baseline_label: str | None = "baseline",
    candidate_label: str = "candidate",
    name: str = "pairs.yaml",
) -> Path:
    doc = {"candidate_label": candidate_label, "baseline_label": baseline_label, "pairs": rows, "skipped": []}
    return write_yaml(tmp_path / name, doc)


def ids_of(n: int) -> list[str]:
    return [f"B-{i:03d}" for i in range(1, n + 1)]


# --- running the CLI -----------------------------------------------------------------------------------------------


def invoke(
    argv: list[str],
    *,
    environ: Mapping[str, str] | None = None,
    process_env: Mapping[str, str] | None = None,
    provider: EvalProvider | None = None,
) -> Invocation:
    """`tilo_evals.__main__.main(argv, ...)` in process on a clean environment plus `environ` (also passed as the
    `environ` argument) and `process_env` (the real process only). An argparse exit is returned as its code."""
    import tilo_evals.__main__ as cli  # noqa: PLC0415

    kwargs: dict[str, Any] = {"environ": dict(environ or {})}
    if provider is not None:
        kwargs["eval_provider"] = provider
    out, err = io.StringIO(), io.StringIO()
    with env(**{**dict(environ or {}), **dict(process_env or {})}):
        with _capture_logs() as logs, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv, **kwargs)
            except SystemExit as exit_:
                code = int(exit_.code or 0) if isinstance(exit_.code, int | type(None)) else 2
    return Invocation(code, out.getvalue(), err.getvalue(), logs.getvalue())


def assert_refused(result: Invocation, code: str | None = None) -> None:
    """Exit 2 from the command itself, never from argparse not knowing `vertex-eval`; `code` is the pinned word."""
    assert result.code == 2, (result.code, result.err)
    assert "invalid choice: 'vertex-eval'" not in result.err, result.err
    assert "REFUSED" in result.err or "error:" in result.err, result.err
    if code is not None:
        assert f"REFUSED {code}" in result.err, result.err


def run_argv(
    tmp_path: Path,
    pairs: Path,
    *,
    mode: str = "--fake",
    cap: float | None = None,
    extra: tuple[str, ...] = (),
    settings: Path | None = None,
    models: Path | None = None,
    prices: Path | None = None,
    report: Path | None = None,
    report_json: Path | None = None,
) -> list[str]:
    argv = ["vertex-eval", "run", "--pairs", str(pairs)]
    if mode:
        argv.append(mode)
    argv += ["--settings", str(settings or write_settings(tmp_path))]
    argv += ["--models-file", str(models or write_models(tmp_path))]
    argv += ["--prices-file", str(prices or write_prices(tmp_path))]
    argv += ["--report-md", str(report or tmp_path / "report.md")]
    if report_json is not None:
        argv += ["--report-json", str(report_json)]
    if cap is not None:
        argv += ["--max-credits", str(cap)]
    return [*argv, *extra]


def live_models(tmp_path: Path) -> Path:
    return write_models(tmp_path, provider="vertex_eval", profile="judge-live", model="zz-judge-model-under-test")


def live_run_argv(tmp_path: Path, pairs: Path, **kw: Any) -> list[str]:
    models = live_models(tmp_path)
    prices = write_prices(tmp_path, profile="judge-live", **{k: kw.pop(k) for k in list(kw) if k.endswith("_rate")})
    return run_argv(tmp_path, pairs, mode="", models=models, prices=prices, **kw)


def export_argv(
    tmp_path: Path,
    candidate: Path,
    baseline: Path | None = None,
    *,
    out: Path | None = None,
    settings: Path | None = None,
    extra: tuple[str, ...] = (),
) -> list[str]:
    argv = ["vertex-eval", "export", "--candidate", str(candidate)]
    if baseline is not None:
        argv += ["--baseline", str(baseline)]
    argv += ["--out", str(out or tmp_path / "pairs.local.yaml")]
    argv += ["--settings", str(settings or write_settings(tmp_path))]
    return [*argv, *extra]


def load_pairs(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- reading what a run printed and wrote --------------------------------------------------------------------------

TOTAL_RE = re.compile(r"^total credits=(?P<credits>\d+\.\d{4}) cap=(?P<cap>\d+\.\d{4})$", re.MULTILINE)
ESTIMATE_RE = re.compile(r"^estimate credits=(?P<credits>\d+\.\d{4}) cap=(?P<cap>\d+\.\d{4})$", re.MULTILINE)
FIT_RE = re.compile(r"^fit (?P<k>\d+) of (?P<n>\d+) cases$", re.MULTILINE)
JUDGED_RE = re.compile(r"Judged (?P<k>\d+) of (?P<n>\d+) cases")


def total_credits(result: Invocation) -> float:
    match = TOTAL_RE.search(result.out)
    assert match, result.out
    return float(match["credits"])


def rubric(name: str) -> str:
    return (PROMPTS / name).read_bytes().decode("utf-8")


def render_rubric(template: str, **fields: str) -> str:
    out = template
    for name in PAIR_PLACEHOLDERS:
        out = out.replace("{" + name + "}", fields.get(name, ""))
    return out


def expected_credits(
    template: str,
    fields: Mapping[str, str],
    *,
    input_rate: float,
    output_rate: float,
    credit_usd: float,
    overhead: int,
    out_tokens: int,
) -> float:
    """The design's quote (3.3): B is the UTF-8 byte count of the rubric with the fields substituted."""
    size = len(render_rubric(template, **fields).encode("utf-8"))
    tokens = math.ceil(size / 3) + overhead
    return ((tokens * input_rate + out_tokens * output_rate) / 1e6) / credit_usd


def fences(text: str) -> list[str]:
    return re.findall(r"<<<([A-Z_]+)", text)


def planted() -> dict[str, str]:
    """Fake secrets and personal data, assembled at runtime (no secret-looking literal in the source)."""
    return {
        "email": "jane.doe" + "@" + "acme-test.example",
        "phone": "+" + "91 98765 43210",
        "oauth": "ya29." + "a0AfH6SMB" + "x9Qw7Er5Ty3Ui1Op",
        "apikey": "AIza" + "Sy" + "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"[:36],
        "sk": "sk-" + "proj-" + "Q7vLm2Zp9RtYw3KdFh8NcB5sJ1uXa4",
        "bearer": "Bearer " + "eyJhbGciOiJIUzI1NiJ9" + ".payloadpart.sigpart",
        "labelled": "api_" + "key" + "=" + "Zx9q8w7e6r5t4y3u2i1o",
        "project": "demo-vx-eval-project-77",
        "adc": "C:/Users/someone/AppData/Roaming/gcloud/" + "application_default_credentials" + ".json",
    }


# the fragments that must not survive, however a value was cut: not the whole value but its distinctive core
CORES = {
    "email": "jane.doe",
    "phone": "98765 43210",
    "oauth": "x9Qw7Er5Ty3Ui1Op",
    "apikey": "AbCdEfGhIjKlMnOp",
    "sk": "Q7vLm2Zp9RtYw3Kd",
    "bearer": "payloadpart",
    "labelled": "Zx9q8w7e6r5t4y3u2i1o",
    "project": "demo-vx-eval-project-77",
    "adc": "application_default_credentials",
}


def leaks(text: str) -> list[str]:
    values = planted()
    return [name for name, value in values.items() if value in text or CORES[name] in text]
