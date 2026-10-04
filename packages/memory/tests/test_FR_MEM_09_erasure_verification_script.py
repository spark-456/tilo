"""FR-MEM-09: "... verified by a script" (PRD 13.5). The script re-reads every store and reports whether any record of
the user is left; it never trusts what a delete call said. `python -m tilo_memory.erasure verify <user_id>` exits 0
only when every required store is clean, 1 otherwise (same convention as `python -m tilo_archive.verify`).

`tilo_memory` does not exist yet, so these fail at import. Fake stores only (API_FR_MEM_03_09.md). SECURITY: the
script's output and errors carry store names and counts only (PRD 16.1, 16.4).
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from datetime import timedelta

import pytest
from _memory_lib import NOW, LyingStore, Rec, ago, build_registry
from tilo_memory.erasure import (
    REQUIRED_STORES,
    IncompleteRegistry,
    erase_user,
    main,
    request_erasure,
    verify_erasure,
)

ALICE, BOB = "u_alice", "u_bob"


def registry_with(users_in_each_store=(ALICE, BOB)):
    registry = build_registry(sorted(REQUIRED_STORES))
    for name, store in registry.items():
        for i, user in enumerate(users_in_each_store):
            store.add(Rec("run", f"{name}-{i}", ago(1), user, payload=f"{user} private text"))
    return registry


def run_cli(argv, registry):
    out = io.StringIO()
    code = main(argv, registry=registry, stdout=out)
    return code, out.getvalue()


def test_FR_MEM_09_verify_fails_while_the_user_still_has_data_in_a_store():
    registry = registry_with()
    result = verify_erasure(registry, ALICE)
    assert result.ok is False
    assert result.remaining == {name: 1 for name in registry}
    assert len(result.problems) == len(registry)
    for name in registry:
        assert any(name in p for p in result.problems)


def test_FR_MEM_09_verify_passes_after_erasure_and_after_erasure_only():
    registry = registry_with()
    assert verify_erasure(registry, ALICE).ok is False
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW + timedelta(days=3))
    result = verify_erasure(registry, ALICE)
    assert result.ok is True
    assert result.remaining == {name: 0 for name in registry}
    assert result.problems == []
    assert verify_erasure(registry, BOB).ok is False  # Bob was not erased


def test_FR_MEM_09_verify_catches_a_single_store_that_kept_one_record():
    registry = registry_with()
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    leaky = sorted(REQUIRED_STORES)[-1]
    registry[leaky].add(Rec("artifact", "late-write", ago(0), ALICE))  # e.g. a write that raced the deletion
    result = verify_erasure(registry, ALICE)
    assert result.ok is False
    assert result.remaining[leaky] == 1
    assert [n for n, c in result.remaining.items() if c] == [leaky]


def test_FR_MEM_09_verify_re_reads_the_store_instead_of_trusting_delete():
    registry = registry_with()
    lying = sorted(REQUIRED_STORES)[0]
    registry[lying] = LyingStore(registry[lying].records())
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    result = verify_erasure(registry, ALICE)
    assert result.ok is False
    assert result.remaining[lying] == 1


def test_FR_MEM_09_verify_with_a_missing_store_is_an_error_not_a_pass():
    """Checking fewer stores than the platform has would give false assurance."""
    registry = registry_with()
    for store in registry.values():
        for rec in list(store.records()):
            store.delete(rec.record_id)
    del registry[sorted(REQUIRED_STORES)[0]]
    with pytest.raises(IncompleteRegistry):
        verify_erasure(registry, ALICE)


@pytest.mark.parametrize("bad_id", ["", " ", "*", "u_*"])
def test_FR_MEM_09_verify_refuses_a_blank_or_wildcard_user(bad_id):
    with pytest.raises(ValueError):
        verify_erasure(registry_with(), bad_id)


def test_FR_MEM_09_verify_does_not_delete_anything():
    registry = registry_with()
    verify_erasure(registry, ALICE)
    for store in registry.values():
        assert store.delete_calls == []
        assert len(store.ids()) == 2


def test_FR_MEM_09_cli_exits_1_and_names_the_stores_that_still_hold_data():
    registry = registry_with()
    code, out = run_cli(["verify", ALICE], registry)
    assert code == 1
    report = json.loads(out)
    assert report["ok"] is False
    assert set(report["stores"]) == set(registry)
    assert all(count == 1 for count in report["stores"].values())
    assert report["problems"]


def test_FR_MEM_09_cli_exits_0_once_every_store_is_clean():
    registry = registry_with()
    erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    code, out = run_cli(["verify", ALICE], registry)
    assert code == 0
    report = json.loads(out)
    assert report["ok"] is True
    assert report["stores"] == {name: 0 for name in registry}
    assert report["problems"] == []


def test_FR_MEM_09_cli_output_never_contains_record_content():
    registry = registry_with()
    _, out = run_cli(["verify", ALICE], registry)
    assert "private text" not in out


def test_FR_MEM_09_cli_exits_non_zero_on_a_blank_user_and_deletes_nothing():
    registry = registry_with()
    code, _ = run_cli(["verify", ""], registry)
    assert code != 0
    for store in registry.values():
        assert len(store.ids()) == 2


def test_FR_MEM_09_cli_exits_non_zero_when_a_store_is_missing():
    registry = registry_with()
    del registry[sorted(REQUIRED_STORES)[0]]
    code, _ = run_cli(["verify", ALICE], registry)
    assert code != 0


def test_FR_MEM_09_module_runs_as_a_script():
    """`python -m tilo_memory.erasure --help` works with no stores configured and no network."""
    proc = subprocess.run(
        [sys.executable, "-m", "tilo_memory.erasure", "--help"], capture_output=True, text=True, timeout=60, check=False
    )
    assert proc.returncode == 0, proc.stderr
    assert "verify" in proc.stdout
