"""E-RED hidden-text injection pages (PRD 16.2, 16.3, 19.2 E-RED; 6.2 red
kind). One page per technique; the seed's own `manifest` is the harness's
ground truth, also exposed live at /manifest.json.
"""

from __future__ import annotations

import pytest
from _sandbox_web_testlib import RED_SLUG, load_seed, technique_ok

MANIFEST = load_seed(RED_SLUG)["manifest"]

TECHNIQUES = {
    "display-none",
    "visibility-hidden",
    "zero-font-size",
    "white-on-white",
    "offscreen-position",
    "html-comment",
    "alt-title-attr",
    "aria-hidden",
    "zero-width-chars",
    "homoglyph-bidi",
    "link-smuggling",
}


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["id"] for e in MANIFEST])
def test_E_RED_technique_hides_the_payload_from_a_sighted_reader(client, entry):
    resp = client.get(f"/s/{RED_SLUG}/{entry['page']}")
    assert resp.status_code == 200
    assert technique_ok(resp.text, entry), f"{entry['id']} ({entry['technique']}) is not actually hidden"


def test_E_RED_all_eleven_techniques_are_registered_in_manifest_json(client):
    injections = client.get("/manifest.json").json()["injections"]
    red = [i for i in injections if i["id"].startswith("RED-")]
    assert {i["technique"] for i in red} == TECHNIQUES
    assert len(red) == 11


def test_E_RED_every_bait_in_manifest_json_is_on_the_invalid_domain(client):
    injections = client.get("/manifest.json").json()["injections"]
    for inj in injections:
        for bait in inj["bait"]:
            domain = bait.rsplit("@", 1)[-1]
            assert domain.endswith(".invalid"), f"{inj['id']} bait {bait!r} is not on .invalid"
