"""PRD 15.3 (Firestore layout), D-11, ticket brief items 8-10: `run_skeleton` against a real
`FirestoreStore` writes the full stream and its views at exactly
`orgs/{org}/worlds/{world}/events/{seq:08d}` and
`orgs/{org}/worlds/{world}/views/{scope}/events/{vseq:08d}`, and the `python -m
tilo_harness.skeleton` CLI does the same, printing one JSON line and exiting 0.

@pytest.mark.emulator: needs Java (the Firestore emulator binary) and firebase-tools (pinned
root devDependency, run through `pnpm exec`). Run explicitly with
`uv run pytest services/harness/tests -m emulator`; excluded from the default suite the same
way `slow`-marked tests are in the root pyproject.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.emulator


def test_PRD_15_3_emulator_skeleton_writes_full_stream_and_views_at_the_prd_15_3_paths(
    emulator_host: str, repo_root
) -> None:
    from google.cloud import firestore
    from tilo_harness.skeleton import run_skeleton
    from tilo_harness.store import FirestoreStore

    org_id, world_id = "org_demo", "w_emulator_skel_1"
    store = FirestoreStore(project_id="demo-tilo")
    events = run_skeleton(store, org_id=org_id, world_id=world_id, run_id="r_emulator_skel_1")
    assert events, "run_skeleton must write at least one event"

    client = firestore.Client(project="demo-tilo")
    stream_docs = list(client.collection(f"orgs/{org_id}/worlds/{world_id}/events").stream())
    assert len(stream_docs) == len(events)
    doc_ids = sorted(d.id for d in stream_docs)
    assert doc_ids == [f"{seq:08d}" for seq in range(1, len(events) + 1)], (
        f"PRD 15.3: full-stream doc ids must be zero-padded seq, got {doc_ids}"
    )
    for doc in stream_docs:
        assert doc.to_dict()["seq"] == int(doc.id), "the doc id must equal its own seq, zero-padded"

    shared_docs = list(client.collection(f"orgs/{org_id}/worlds/{world_id}/views/shared/events").stream())
    assert shared_docs, "the shared view must hold at least the vis='all' events"
    shared_ids = sorted(d.id for d in shared_docs)
    assert shared_ids == [f"{vseq:08d}" for vseq in range(1, len(shared_docs) + 1)], (
        f"PRD 15.3: view doc ids must be zero-padded, dense vseq starting at 1, got {shared_ids}"
    )
    for doc in shared_docs:
        assert doc.to_dict()["seq"] == int(doc.id), "a view doc's seq field must equal its own vseq (its doc id)"


def test_PRD_15_3_cli_prints_one_json_line_and_exits_0(emulator_host: str, repo_root) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tilo_harness.skeleton",
            "--org",
            "org_demo",
            "--world",
            "w_emulator_cli_1",
            "--run",
            "r_emulator_cli_1",
            "--lease-s",
            "30",
            "--step-delay",
            "0",
        ],
        cwd=repo_root,
        env={**os.environ, "FIRESTORE_EMULATOR_HOST": emulator_host},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"CLI must exit 0, stderr:\n{result.stderr}"
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"CLI must print exactly one JSON line, got:\n{result.stdout!r}"
    payload = json.loads(lines[0])
    assert set(payload) == {"written", "world_id", "last_seq"}, payload
    assert payload["world_id"] == "w_emulator_cli_1"
    assert payload["written"] == payload["last_seq"] > 0
