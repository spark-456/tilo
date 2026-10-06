"""Shared helpers for the GEN-07..GEN-10 tests (issue #272 (b), the live scenario generator).

Nothing here talks to a network and nothing makes a paid call. The generator is handed a fake "live" model through the
same seam `live_e2e` uses (`live_provider_factory(role, profile_id)`), so the real Router, the real record-and-replay
provider and the real pipeline run on top of fakes. The live switch is only ever set inside a test's own patched
environment (`_live_e2e_lib.env`), and the provider is always a fake.

Roles the fakes answer: `generator` (a JSON object `{"briefs": [...]}`), `autorater` (a JSON object with the two
scores) and, for everything the pipeline calls, the same case-scripted fakes as the PL-LIVE-E2E tests, driven by the
`director` script of one bank case (the same script for every generated brief).

API pinned for the implementer: `API_GEN_07_10.md` in this directory.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from _live_e2e_lib import (  # noqa: F401  (re-exported for the tests)
    BANK,
    ESTIMATE_RE,
    PROJECT,
    REPO_ROOT,
    CaseFakeModel,
    FakeCall,
    FakeWorld,
    Invocation,
    _capture_logs,
    bank_case,
    env,
    network_guard,
    write_prices,
)
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import GenerateRequest, GenerateResponse, SafetyProvider, SafetyResult
from tilo_providers.safety import FakeSafetyProvider

GENERATOR_ROLE = "generator"
AUTORATER_ROLE = "autorater"
DATE = "2026-10-06"
REAL_SETTINGS = REPO_ROOT / "evals" / "generator.yaml"
REAL_SETTINGS_SCHEMA = REPO_ROOT / "evals" / "generator.schema.json"
REAL_MODELS_FILES = sorted((REPO_ROOT / "config").glob("models*.yaml"))

SCORES_RE = re.compile(r"live, N=(?P<n>\d+), (?P<date>\d{4}-\d{2}-\d{2})")
TOTAL_RE = re.compile(r"^total credits=(?P<credits>\d+\.\d{4}) cap=(?P<cap>\d+\.\d{4})$", re.MULTILINE)

# Eight novel briefs on purpose far from every bank brief (no six-word run is shared with the bank).
BRIEFS: list[dict[str, Any]] = [
    {
        "title": "Pick a self-checkout kiosk vendor",
        "domain": "procurement",
        "shapes": ["single_deliverable"],
        "brief": "Our community library wants to replace its ageing self-checkout kiosks. Compare three vendors on "
        "price, access for wheelchair users and the length of the maintenance contract, then recommend one with a "
        "short rationale for the board of trustees.",
    },
    {
        "title": "Video calls course for grandparents",
        "domain": "education",
        "shapes": ["multi_deliverable"],
        "brief": "Plan a four week evening course that teaches retired neighbours to hold video calls with their "
        "grandchildren. I need a weekly outline, a one page handout for every week and a short feedback form for "
        "the last session.",
    },
    {
        "title": "Honey co-op payout check",
        "domain": "operations",
        "shapes": ["gated_send"],
        "brief": "Reconcile the beekeeping co-op's honey sales sheet against the member payout list for September, "
        "flag any member paid for more jars than were sold, and draft a polite note to the treasurer about them.",
    },
    {
        "title": "Warehouse onboarding checklist",
        "domain": "hr",
        "shapes": ["single_deliverable"],
        "brief": "A part time warehouse worker joins us next Monday, so write a first-week checklist for them. It "
        "should cover safety training, boot fitting, payroll forms and a buddy assignment, and then go to the shift "
        "supervisor.",
    },
    {
        "title": "Cluster login complaints",
        "domain": "support",
        "shapes": ["single_deliverable"],
        "brief": "Group the latest two hundred support tickets about the phone app's sign-in screen into themes, "
        "rank the themes by how many customers they touch, and write a summary the engineering lead can read in "
        "two minutes.",
    },
    {
        "title": "Bakery cash forecast",
        "domain": "finance",
        "shapes": ["single_deliverable"],
        "brief": "Prepare a quarterly cash forecast for a small bakery that has just bought two new ovens. Assume "
        "flour prices rise by five percent, show the month in which the ovens pay for themselves and list the "
        "assumptions plainly.",
    },
    {
        "title": "Licence and passport paperwork",
        "domain": "personal_admin",
        "shapes": ["multi_deliverable"],
        "brief": "Gather the paperwork I need to renew my driving licence and my passport this year, list every "
        "deadline in order, and set a reminder a week before each one so nothing lapses.",
    },
    {
        "title": "Flaky test audit",
        "domain": "engineering",
        "shapes": ["single_deliverable"],
        "brief": "Audit last month's flaky tests in our build pipeline, group them by root cause, and propose a "
        "ranked list of fixes with a rough effort estimate for each one.",
    },
]


def brief_at(index: int, **overrides: Any) -> dict[str, Any]:
    return {**BRIEFS[index], **overrides}


# --- fakes -----------------------------------------------------------------------------------------------------


@dataclass
class GenWorld(FakeWorld):
    """A `FakeWorld` that also answers the `generator` and `autorater` roles. `briefs` is what the generator replies
    on every call (dicts, normally); `scores` is the autorater's reply."""

    briefs: list[Any] = field(default_factory=list)
    scores: tuple[float, float] = (0.8, 0.6)
    raw_reply: str | None = None  # when set, the generator replies with exactly this text (garbage, not JSON, ...)
    requests: list[tuple[str, GenerateRequest]] = field(default_factory=list)

    def factory(self, role: str, profile_id: str) -> Any:
        self.built.append((role, profile_id))
        if role == GENERATOR_ROLE:
            return GeneratorFake(self, role, profile_id)
        if role == AUTORATER_ROLE:
            return AutoraterFake(self, role, profile_id)
        return CaseFakeModel(self, role, profile_id)

    def calls_of(self, role: str) -> list[FakeCall]:
        return [call for call in self.calls if call.role == role]

    def director_briefs(self) -> int:
        """How many times the pipeline's Director was asked to read a brief: one per brief that was really run."""
        return sum(1 for call in self.calls if call.role == "director" and call.kind == "brief")


class _TextFake(CaseFakeModel):
    def _reply(self, request: GenerateRequest) -> str:
        raise NotImplementedError

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        world: GenWorld = self._world  # type: ignore[assignment]
        if world.stdout_at_first_call is None:
            out = sys.stdout
            world.stdout_at_first_call = out.getvalue() if isinstance(out, io.StringIO) else ""
        time.sleep(world.delay_s)
        world.calls.append(FakeCall(self._role, self._profile_id, "text", world.call_credits()))
        world.requests.append((self._role, request))
        if (error := world.fail_roles.get(self._role)) is not None:
            raise error
        tin, tout = world.usage
        usage = {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout}
        return GenerateResponse(text=self._reply(request), profile_id=self._profile_id, usage=usage)


class GeneratorFake(_TextFake):
    def _reply(self, request: GenerateRequest) -> str:
        world: GenWorld = self._world  # type: ignore[assignment]
        return world.raw_reply if world.raw_reply is not None else json.dumps({"briefs": world.briefs}, sort_keys=True)


class AutoraterFake(_TextFake):
    def _reply(self, request: GenerateRequest) -> str:
        fit, useful = self._world.scores  # type: ignore[attr-defined]
        return json.dumps({"plan_fit": fit, "question_usefulness": useful, "rationale": "synthetic"}, sort_keys=True)


def gen_world(*, case: str = "B-007", briefs: list[Any] | None = None, **fields: Any) -> GenWorld:
    """A world whose Director follows bank case `case`'s own script for every generated brief."""
    return GenWorld(
        script=bank_case(case).director, briefs=list(briefs if briefs is not None else BRIEFS[:3]), **fields
    )


class RecordingSafety(SafetyProvider):
    """The dev safety screen plus a log of every text it was asked about (a real screen is a model call)."""

    def __init__(self, inner: SafetyProvider | None = None) -> None:
        self.inner, self.checked = inner or FakeSafetyProvider(), []

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
        self.checked.append(text)
        return self.inner.check(text, content=content, mime_type=mime_type)


class BrokenSafety(SafetyProvider):
    """A screen that is down: it must fail closed (a brief it could not screen is never run)."""

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
        raise ProviderError("the safety service is unavailable")


# --- files -----------------------------------------------------------------------------------------------------


def write_settings(
    tmp_path: Path, *, max_inr: float = 150.0, inr_per_usd: float = 100.0, name: str = "gen.yaml"
) -> Path:
    """A generator settings file holding only the two keys the API requires (`max_inr`, `inr_per_usd`)."""
    path = tmp_path / name
    path.write_text(yaml.safe_dump({"max_inr": max_inr, "inr_per_usd": inr_per_usd}), encoding="utf-8")
    return path


def copy_bank(tmp_path: Path, case_ids: tuple[str, ...] = ("B-001", "B-007")) -> Path:
    """A small private copy of the bank, so a test can prove nothing was written to the bank."""
    target = tmp_path / "bank"
    target.mkdir(exist_ok=True)
    for case_id in case_ids:
        (target / f"{case_id}.yaml").write_bytes((BANK / f"{case_id}.yaml").read_bytes())
    return target


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` (relative posix path -> bytes): to prove a run changed nothing, or wrote only here."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def generated_files(out_dir: Path, date: str = DATE) -> list[Path]:
    folder = out_dir / date
    return sorted(folder.glob("*.yaml")) if folder.is_dir() else []


def load_generated(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- running the module under test -------------------------------------------------------------------------------


def generator() -> Any:
    import importlib  # noqa: PLC0415

    return importlib.import_module("tilo_evals.generator")


def cli_args(
    tmp_path: Path,
    *,
    n: int = 3,
    dry_run: bool = False,
    max_inr: float | None = None,
    inr_per_usd: float = 100.0,
    settings_max_inr: float = 150.0,
    per_million: float = 1.0,
    credit_usd: float = 0.005,
    bank: Path | None = None,
    date: str = DATE,
    extra: tuple[str, ...] = (),
) -> list[str]:
    """`generate` arguments with every path under `tmp_path`: settings, prices, bank copy, output root and report."""
    settings = write_settings(tmp_path, max_inr=settings_max_inr, inr_per_usd=inr_per_usd)
    prices = write_prices(tmp_path, per_million=per_million, credit_usd=credit_usd)
    argv = ["generate", "--n", str(n), "--settings", str(settings), "--prices-file", str(prices)]
    argv += ["--bank-dir", str(bank or copy_bank(tmp_path)), "--out-dir", str(tmp_path / "generated")]
    argv += ["--report-md", str(tmp_path / "report.md"), "--date", date]
    if dry_run:
        argv.append("--dry-run")
    if max_inr is not None:
        argv += ["--max-inr", str(max_inr)]
    return [*argv, *extra]


def invoke_generate(
    argv: list[str],
    *,
    world: GenWorld | None = None,
    safety: SafetyProvider | None = None,
    environ: Mapping[str, str] | None = None,
) -> Invocation:
    """`tilo_evals.__main__.main(argv, ...)` in process, capturing stdout, stderr and logging. A bad command line
    (argparse exits with 2) is returned as code 2, like any other refusal."""
    import tilo_evals.__main__ as cli  # noqa: PLC0415

    kwargs: dict[str, Any] = {"safety": safety or FakeSafetyProvider()}
    if world is not None:
        kwargs["live_provider_factory"] = world.factory
    if environ is not None:
        kwargs["environ"] = environ
    out, err = io.StringIO(), io.StringIO()
    with _capture_logs() as logs, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv, **kwargs)
        except SystemExit as exit_:
            code = int(exit_.code or 0) if isinstance(exit_.code, int | type(None)) else 2
    return Invocation(code, out.getvalue(), err.getvalue(), logs.getvalue())


LIVE_ENV = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}


def live_generate(
    tmp_path: Path,
    *,
    world: GenWorld | None = None,
    safety: SafetyProvider | None = None,
    extra_env: Mapping[str, str] | None = None,
    **cli: Any,
) -> tuple[Invocation, GenWorld]:
    """One `generate` run in live mode with the fake provider: the live switch is only set inside a patched
    environment. Prices and the world's price per million tokens always agree."""
    world = world or gen_world(per_million_usd=cli.get("per_million", 1.0), credit_usd=cli.get("credit_usd", 0.005))
    argv = cli_args(tmp_path, **cli)
    with env(**{**LIVE_ENV, **(extra_env or {})}):
        result = invoke_generate(argv, world=world, safety=safety)
    return result, world


def run_direct(
    tmp_path: Path, *, world: GenWorld | None = None, safety: SafetyProvider | None = None, **cli: Any
) -> tuple[Any, GenWorld]:
    """`tilo_evals.generator.run_generate(...)` called directly (live mode, fake provider): the report object."""
    module = generator()
    world = world or gen_world(per_million_usd=cli.get("per_million", 1.0), credit_usd=cli.get("credit_usd", 0.005))
    argv = cli_args(tmp_path, **cli)
    flags = {argv[i]: argv[i + 1] for i in range(1, len(argv) - 1) if argv[i].startswith("--")}
    kwargs: dict[str, Any] = {
        "mode": "dry-run" if "--dry-run" in argv else "live",
        "bank_dir": Path(flags["--bank-dir"]),
        "out_dir": Path(flags["--out-dir"]),
        "settings_path": Path(flags["--settings"]),
        "prices_path": Path(flags["--prices-file"]),
        "live_provider_factory": world.factory,
        "safety": safety or FakeSafetyProvider(),
    }
    if "--max-inr" in flags:
        kwargs["max_inr"] = float(flags["--max-inr"])
    import datetime  # noqa: PLC0415

    kwargs["today"] = datetime.date.fromisoformat(flags["--date"])
    with env(**LIVE_ENV):
        report = module.run_generate(int(flags["--n"]), **kwargs)
    return report, world


def replay_bank(directory: Path) -> list[Any]:
    """The existing bank runner over a directory of generated cases, with the live switch off."""
    from tilo_evals.bank import load_bank  # noqa: PLC0415
    from tilo_evals.bank_report import run_bank  # noqa: PLC0415

    with env():
        return run_bank(load_bank(directory))
