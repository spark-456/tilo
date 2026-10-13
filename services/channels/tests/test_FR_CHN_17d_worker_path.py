"""FR-CHN-17d: the service worker's allowlisted tap path is the one tilo-channels builds payload paths from."""

from __future__ import annotations

from pathlib import Path

from tilo_channels import web_push

WORKER = Path(__file__).resolve().parents[3] / "apps" / "web" / "public" / "push-sw.js"


def test_FR_CHN_17d_worker_allowlist_matches_the_payload_path_and_a_built_path_passes_it() -> None:
    src = WORKER.read_text(encoding="utf-8")
    assert f'const HOME = "{web_push.OPEN_PATH}";' in src
    assert "/^\\/park\\/home(\\?card=[A-Za-z0-9_-]{1,64})?$/" in src
    assert web_push.path_for("card_0001") == f"{web_push.OPEN_PATH}?card=card_0001"
