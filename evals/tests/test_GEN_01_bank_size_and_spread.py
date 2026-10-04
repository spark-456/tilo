"""GEN-01, GEN-05 (issue #272): the bank is big enough, spread across domains and shapes, and frozen."""

from collections import Counter

import pytest
from _evals_lib import REPO_ROOT
from tilo_evals.bank import BANK_SCHEMA_PATH, BankError, bank_digest, load_bank

BANK = REPO_ROOT / "evals" / "bank"


def test_GEN_01_the_bank_has_30_plus_cases_across_8_plus_domains_and_every_shape_twice() -> None:
    import json

    cases = load_bank(BANK)
    assert len(cases) >= 30
    assert len({c.domain for c in cases}) >= 8
    shapes = json.loads(BANK_SCHEMA_PATH.read_text(encoding="utf-8"))["properties"]["shapes"]["items"]["enum"]
    per_shape = Counter(s for c in cases for s in c.shapes)
    thin = {s: per_shape[s] for s in shapes if per_shape[s] < 2}
    assert not thin, f"every shape needs two cases: {thin}"
    outcomes = Counter(c.outcome for c in cases)
    assert set(outcomes) == {"completed", "held_at_gate", "refused", "needs_answers"}
    assert all(n >= 2 for n in outcomes.values())


def test_GEN_01_ids_are_unique_and_run_without_gaps() -> None:
    ids = [c.id for c in load_bank(BANK)]
    assert ids == [f"B-{n:03d}" for n in range(1, len(ids) + 1)]


def test_GEN_05_the_bank_is_frozen_by_its_manifest() -> None:
    digest, _, count = (BANK / "MANIFEST.sha256").read_text(encoding="utf-8").strip().partition("  ")
    assert digest == bank_digest(BANK), "the bank changed: a change needs the user's approval and a new manifest"
    assert count == f"{len(load_bank(BANK))} cases"


def test_GEN_05_a_case_file_with_crlf_digests_like_lf(tmp_path) -> None:
    (tmp_path / "B-001.yaml").write_bytes(b"id: B-001\r\n")
    lf = tmp_path / "lf"
    lf.mkdir()
    (lf / "B-001.yaml").write_bytes(b"id: B-001\n")
    assert bank_digest(tmp_path) == bank_digest(lf)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.pop("director"),
        lambda c: c.update(domain="astrology"),
        lambda c: c.update(shapes=[]),
        lambda c: c.update(brief=""),
        lambda c: c["expect"].update(outcome="delivered"),
        lambda c: c.update(files=[{"name": "../x.csv", "text": "a"}]),
        lambda c: c.update(unexpected=True),
    ],
)
def test_GEN_01_the_loader_refuses_a_case_that_breaks_the_schema(tmp_path, mutate) -> None:
    import yaml

    case = yaml.safe_load((BANK / "B-001.yaml").read_text(encoding="utf-8"))
    mutate(case)
    (tmp_path / "B-001.yaml").write_bytes(yaml.safe_dump(case).encode("utf-8"))
    with pytest.raises(BankError):
        load_bank(tmp_path)


def test_GEN_01_the_loader_refuses_a_misnamed_file_and_a_duplicate_id(tmp_path) -> None:
    import shutil

    shutil.copy(BANK / "B-001.yaml", tmp_path / "B-002.yaml")  # id B-001 in a file named B-002
    with pytest.raises(BankError):
        load_bank(tmp_path)
