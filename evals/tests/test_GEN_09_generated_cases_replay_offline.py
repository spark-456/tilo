"""GEN-09 (issue #272 (b); PRD 6.6 EFF-01 record and replay, 16.1 rule 4 redaction): each generated case is written to
`evals/generated/<date>/<id>.yaml` with its brief and the recorded, redacted model replies of its own run, and replays
offline through the existing bank runner to the same outcome class with no live call.

Criteria covered:
  (1) the file is `<out-dir>/<date>/<id>.yaml` (date: `--date`, default today UTC), the file stem is the case id, ids
      are unique and none is a bank id; it loads with the bank loader (`load_bank`, `bank.schema.json`, which the
      builder may extend inside evals/, no contract change) and holds the brief that was run;
  (2) it holds the Director's replies of that run (`director: {brief, approaches, plan}`, the same data a bank case
      scripts) and `expect.outcome`, the outcome class the live run reached (one of the bank's four classes);
  (3) the replies are redacted before they are saved: an email address, a phone number, a token or an Authorization
      header that a model echoed is in no file;
  (4) replay: `run_bank` and `python -m tilo_evals bank --bank <dir>` over the generated folder, with LIVE unset and a
      provider layer that raises on any live call, reach each case's recorded outcome class (also when the live run
      ended in an honest stop, such as a Director that could not answer), pass every hard check, and give the same
      result on a repeat.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
from _generator_lib import (
    BANK,
    BRIEFS,
    DATE,
    PROJECT,
    brief_at,
    cli_args,
    env,
    gen_world,
    generated_files,
    invoke_generate,
    live_generate,
    load_generated,
    network_guard,  # noqa: F401  (autouse fixture)
    replay_bank,
    run_direct,
)
from _live_e2e_lib import EMAIL_RE, PHONE_RE, SECRET_RE, fake_secret, leak_text
from tilo_evals.bank import load_bank

OUTCOMES = {"completed", "held_at_gate", "refused", "needs_answers"}


@pytest.fixture
def no_live_call(monkeypatch: pytest.MonkeyPatch):
    """Returns a function that, once called, makes any use of the provider layer's live path a failure (EFF-01).
    Call it after the generation step (which goes live on a fake) and before the replay."""

    def poison() -> None:
        from tilo_providers import replay  # noqa: PLC0415

        def boom(*_args, **_kwargs):
            raise AssertionError("a live call was attempted during an offline replay")

        monkeypatch.setattr(replay.RecordReplayProvider, "_live", boom)
        monkeypatch.setattr(replay.RecordReplayProvider, "_is_live", boom)

    return poison


def _generate(tmp_path: Path, **cli):
    report, world = run_direct(tmp_path, **cli)
    return report, world, tmp_path / "generated" / DATE


def test_GEN_09_generated_cases_replay_offline(tmp_path: Path, no_live_call) -> None:
    """The headline: generate, then replay the folder through the bank runner to the recorded outcome class."""
    report, world, folder = _generate(tmp_path, world=gen_world(briefs=BRIEFS[:3]), n=3)
    files = generated_files(tmp_path / "generated")
    assert len(files) == 3 and [p.parent for p in files] == [folder] * 3
    no_live_call()
    cases = load_bank(folder)  # the bank loader accepts every generated file
    assert {c.brief for c in cases} == {b["brief"] for b in BRIEFS[:3]}

    results = replay_bank(folder)
    assert len(results) == 3
    for result in results:
        assert result.runs[0].outcome == result.case.outcome == "completed"
        assert result.passed, [f"{f.check}: {f.detail}" for f in result.findings if f.hard]
    assert sorted(r.case.id for r in results) == sorted(c.id for c in report.cases)
    assert {c.outcome_class for c in report.cases} == {"completed"}


def test_GEN_09_the_command_line_bank_runner_replays_the_folder_with_the_live_switch_off(
    tmp_path: Path, no_live_call
) -> None:
    _generate(tmp_path, n=2)
    no_live_call()
    import tilo_evals.__main__ as cli  # noqa: PLC0415

    with env():
        code = cli.main(["bank", "--bank", str(tmp_path / "generated" / DATE), "--results-md", str(tmp_path / "r.md")])
    assert code == 0
    assert "2 of 2" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_GEN_09_each_file_is_named_by_its_id_and_ids_are_unique_and_not_bank_ids(tmp_path: Path) -> None:
    _, _, folder = _generate(tmp_path, world=gen_world(briefs=BRIEFS[:5]), n=5)
    ids = []
    for path in generated_files(tmp_path / "generated"):
        raw = load_generated(path)
        assert path.stem == raw["id"]
        ids.append(raw["id"])
    assert len(ids) == 5 and len(set(ids)) == 5
    assert not set(ids) & {c.id for c in load_bank(BANK)}


def test_GEN_09_a_run_with_no_date_flag_writes_under_todays_utc_date(tmp_path: Path) -> None:
    argv = cli_args(tmp_path, n=1)
    at = argv.index("--date")
    del argv[at : at + 2]
    before = datetime.datetime.now(datetime.UTC).date()
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT):
        result = invoke_generate(argv, world=gen_world())
    after = datetime.datetime.now(datetime.UTC).date()
    assert result.code in (0, 1), result.err
    folders = [p.name for p in (tmp_path / "generated").iterdir() if p.is_dir()]
    assert len(folders) == 1 and folders[0] in {before.isoformat(), after.isoformat()}


def test_GEN_09_the_file_holds_the_brief_and_the_directors_replies_of_its_run(tmp_path: Path) -> None:
    world = gen_world(briefs=[BRIEFS[0]])
    report, world, _ = _generate(tmp_path, world=world, n=1)
    (path,) = generated_files(tmp_path / "generated")
    raw = load_generated(path)
    assert raw["brief"] == BRIEFS[0]["brief"]
    assert raw["domain"] == BRIEFS[0]["domain"] and raw["shapes"] == BRIEFS[0]["shapes"]
    director = raw["director"]
    assert director["brief"]["goal"] == world.script["brief"]["goal"]
    assert [u["id"] for u in director["plan"]["units"]] == [u["id"] for u in world.script["plan"]["units"]]
    assert isinstance(director["approaches"], dict) and len(director["approaches"]["approaches"]) == 3
    assert raw["expect"]["outcome"] in OUTCOMES


def test_GEN_09_a_reply_a_model_echoed_is_redacted_before_it_is_saved(tmp_path: Path, no_live_call) -> None:
    world = gen_world(briefs=BRIEFS[:2], leak=leak_text())
    _, _, folder = _generate(tmp_path, world=world, n=2)
    files = generated_files(tmp_path / "generated")
    assert files
    no_live_call()
    text = "\n".join(p.read_text(encoding="utf-8") for p in files)
    for kind in ("email", "phone", "access_token", "bearer", "api_key"):
        assert fake_secret(kind) not in text, f"a {kind} was saved"
    assert not (EMAIL_RE.search(text) or PHONE_RE.search(text) or SECRET_RE.search(text))
    for result in replay_bank(folder):  # redaction does not break the replay
        assert result.runs[0].outcome == result.case.outcome


def test_GEN_09_a_run_that_ends_in_an_honest_stop_replays_to_that_same_class(tmp_path: Path, no_live_call) -> None:
    """The Director of bank case B-012 cannot propose approaches: the live run stops honestly, the file records the
    class it reached, and the replay (which has no approaches reply either) reaches the same class."""
    report, _, folder = _generate(tmp_path, world=gen_world(case="B-012", briefs=BRIEFS[:2]), n=2)
    assert report.cases, "an honest stop is still a result worth keeping"
    no_live_call()
    for path in generated_files(tmp_path / "generated"):
        assert load_generated(path)["expect"]["outcome"] in OUTCOMES
    for result in replay_bank(folder):
        assert result.runs[0].outcome == result.case.outcome
        assert result.case.outcome == "refused"  # a Director with no approaches reply stops in the bank runner too
    recorded = {
        load_generated(p)["id"]: load_generated(p)["expect"]["outcome"] for p in generated_files(tmp_path / "generated")
    }
    assert {c.id: c.outcome_class for c in report.cases} == recorded  # the report and the file say the same class


def test_GEN_09_a_replay_is_deterministic_on_a_repeat(tmp_path: Path, no_live_call) -> None:
    from tilo_evals.bank import load_bank as load  # noqa: PLC0415
    from tilo_evals.bank_report import run_bank  # noqa: PLC0415

    _, _, folder = _generate(tmp_path, n=2)
    no_live_call()
    with env():
        results = run_bank(load(folder), repeat=2)
    assert results and all(r.deterministic and r.passed for r in results)


def test_GEN_09_the_generated_files_and_the_replay_make_no_network_connection(tmp_path: Path, no_live_call) -> None:
    """The autouse `network_guard` fails any non-loopback connection; here the whole round trip runs under it."""
    result, world = live_generate(tmp_path, n=2)
    assert result.code in (0, 1), result.err
    folder = tmp_path / "generated" / DATE
    no_live_call()
    assert replay_bank(folder)
    assert not re.search(r"https?://", "\n".join(p.read_text(encoding="utf-8") for p in folder.glob("*.yaml")))


def test_GEN_09_a_generated_brief_that_was_not_run_is_not_written(tmp_path: Path) -> None:
    rejected = brief_at(3, brief="")
    report, _, _ = _generate(tmp_path, world=gen_world(briefs=[rejected, brief_at(4)]), n=2)
    assert [r.reason for r in report.rejected] == ["length"]
    assert len(generated_files(tmp_path / "generated")) == 1
