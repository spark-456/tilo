"""FR-CON-02 / ADR-0035 L7: the live-connector settings and the outbox index are documented and pinned.

tilo-api and tilo-connectors have `ignore_env`, so Terraform cannot own their settings:
`docs/deploy-dev.md` must name every
one, in `gcloud` form, with the secret references, and must say the index comes before `TILO_OUTBOX_STORE=firestore`.
Static only: no terraform, no gcloud.
"""

from __future__ import annotations

import pathlib
import re

CONNECTORS = (
    "GOOGLE_OAUTH_REDIRECT_BASE_URL",
    "TILO_TOKEN_STORE=firestore",
    "TILO_FIRESTORE_PROJECT",
    "TILO_TOKEN_DATABASE=tilo-tokens",
    "TILO_KMS_KEY",
    "TILO_CONNECTORS_AUDIENCE",
    "TILO_MEETING_HOST_CALLER",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
)
API = ("TILO_OUTBOX_STORE=firestore", "TILO_CONNECTORS_URL")


def _section(repo_root: pathlib.Path) -> str:
    text = (repo_root / "docs" / "deploy-dev.md").read_text(encoding="utf-8")
    start = text.index("## Live connectors: OAuth client, index, settings")
    return text[start : text.index("\n## ", start + 4)]


def test_FR_CON_02_ADR35_L7_doc_lists_every_connectors_and_api_setting(repo_root: pathlib.Path) -> None:
    section = _section(repo_root)
    connectors = section[section.index("4. Set `tilo-connectors`") :]
    for name in CONNECTORS:
        assert name in connectors, name
    for name in API:
        assert name in section, name
    assert "workspace-oauth-client:1" in section and "workspace-oauth-client:2" in section
    assert "--update-secrets" in section and "^#^" in section


def test_FR_CON_02_ADR35_L7_doc_keeps_the_live_switch_and_separate_rollouts_out(repo_root: pathlib.Path) -> None:
    section = _section(repo_root)
    set_calls = re.findall(r"--update-env-vars \"([^\"]*)\"", section)
    assert [c for c in set_calls if "LIVE=1" in c] == ["LIVE=1"], "LIVE=1 only in its own, last, connectors command"
    assert 'LIVE=1" `' not in section
    api_call = next(c for c in set_calls if "TILO_OUTBOX_STORE" in c)
    for name in ("LIVE", "TILO_API_STORE", "TILO_PEOPLE_STORE", "OAUTH"):
        assert name not in api_call, name
    assert "Never on `tilo-api`" in section


def test_FR_CON_02_ADR35_L7_doc_says_the_index_comes_before_the_outbox_switch(repo_root: pathlib.Path) -> None:
    section = _section(repo_root)
    assert "outbox_transfer_pending" in section and "PI-17" in section
    assert section.index("outbox_transfer_pending") < section.index("TILO_OUTBOX_STORE=firestore#")
    access = (repo_root / "infra" / "ACCESS.md").read_text(encoding="utf-8")
    assert "https://essential-wares-510320-f0.web.app/oauth/google/callback" in access
    assert "calendar.events.owned" in access and "tilotesting@gmail.com" in access and "7 days" in access
