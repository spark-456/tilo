"""ADR35_L4 / FR_CON_02 (ADR-0035 LC-01 to LC-04): the Hosting headers of the Google callback path, the callback page's
"no third-party asset" rule, and the two texts that went stale when person calendar writes arrived.

Static only: no firebase, no network, no cloud credentials.
"""

from __future__ import annotations

import pathlib
import re

import test_P0_07e_hosting_routing as hosting

CALLBACK = "/oauth/google/callback"


def test_ADR35_L4_FR_CON_02_the_callback_path_is_served_with_no_referrer_and_no_store(repo_root: pathlib.Path) -> None:
    headers = hosting.effective_headers(repo_root, CALLBACK)
    assert headers["referrer-policy"].lower() == "no-referrer"  # the code in the address never leaves in a Referer
    assert headers["cache-control"].lower() == "no-store"


def test_ADR35_L4_FR_CON_02_the_callback_path_keeps_every_other_security_header(repo_root: pathlib.Path) -> None:
    here, home = hosting.effective_headers(repo_root, CALLBACK), hosting.effective_headers(repo_root, "/")
    for key in ("content-security-policy", "x-content-type-options"):
        assert here[key] == home[key], key
    assert hosting.rewrite_for(repo_root, CALLBACK) == hosting.SPA_DESTINATION  # the SPA answers there


def test_ADR35_L4_FR_CON_02_only_the_callback_path_changes(repo_root: pathlib.Path) -> None:
    home = hosting.effective_headers(repo_root, "/")
    assert home["referrer-policy"].lower() == "strict-origin-when-cross-origin" and home["cache-control"] == "no-cache"
    for path in (f"{CALLBACK}s", "/oauth", "/oauth/google", f"{CALLBACK}/x", "/connectors", "/assets/x.js"):
        assert hosting.effective_headers(repo_root, path).get("referrer-policy", "").lower() != "no-referrer", path


def test_ADR35_L4_FR_CON_02_the_callback_page_loads_no_third_party_asset(repo_root: pathlib.Path) -> None:
    web = repo_root / "apps" / "web" / "src"
    files = [p for p in (web / "oauth").iterdir() if p.is_file() and ".test." not in p.name]
    files += [web / "api" / "connect.ts", web / "api" / "connectEnv.ts"]
    assert len(files) >= 6
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"url\(|@import|<script|<link|<img|https?://(?!accounts\.google\.com)", text), path.name


def test_ADR35_L4_FR_CON_02_calendar_events_owned_is_no_longer_described_as_meeting_host_only(
    repo_root: pathlib.Path,
) -> None:
    content = (repo_root / "apps" / "web" / "src" / "legal" / "content.ts").read_text(encoding="utf-8")
    assert "meeting host only" not in content
    assert (
        "add events to your own calendar" in content.lower() or "add an event to your own calendar" in content.lower()
    )
    assert "guests" in content.lower()  # with guests it always needs the person's approval


def test_ADR35_L4_FR_CON_02_the_registry_comment_no_longer_says_person_calendar_grants_are_read_only(
    repo_root: pathlib.Path,
) -> None:
    text = (repo_root / "config" / "connectors.yaml").read_text(encoding="utf-8")
    assert "stays read-only" not in text and "stay read-only" not in text
