"""DEMO-BROWSER: a taught skill keeps its browser step, and the catalog says it uses Tilo's browser.

Live taught skills (20 Oct) described "Open youtube.com in a new tab, click the first video" and were saved as
web_search or fetch_url steps, so no browser ever opened, while Home and the Skills drawer refused to run any skill
whose words mention opening a site ("Needs browser control (coming)"). Now:
* a browse step keeps a site the person typed even when the model writes it with "www." or leaves hosts out (TS-18:
  hosts still come only from the person's own words);
* `needs_browser_control` means the skill has a browse_web step (it uses Tilo's browser), never a guess from wording.
"""

from __future__ import annotations

from _skills4_lib import ORG, PRIYA, SAVE
from test_FR_SKL_02_ADR51_tool_allocation import BROWSE, _version, _with_browse

TYPED = "Open youtube.com and read the titles of the top videos, then save a summary in my Drive."


def test_DEMO_BROWSER_a_www_spelling_of_a_typed_site_keeps_the_browse_step(skills4):
    _with_browse(skills4)
    body = _version(skills4, (BROWSE, SAVE), text=TYPED, hosts=["www.youtube.com"]).json()
    assert [s["action"] for s in body["plan_steps"]] == ["browse_web", "save_file"]
    assert body["hosts"] == ["youtube.com"]
    assert skills4.store.get(ORG, body["capture_id"])["hosts"] == ["youtube.com"]


def test_DEMO_BROWSER_a_browse_step_with_no_model_host_takes_the_site_the_person_typed(skills4):
    _with_browse(skills4)
    body = _version(skills4, (BROWSE, SAVE), text=TYPED).json()
    assert [s["action"] for s in body["plan_steps"]] == ["browse_web", "save_file"]
    assert body["hosts"] == ["youtube.com"]


def test_DEMO_BROWSER_a_host_nobody_typed_is_still_dropped(skills4):
    _with_browse(skills4)
    body = _version(skills4, (BROWSE, SAVE), text="Open the supplier page and save a summary.", hosts=["evil.example"])
    assert [s["action"] for s in body.json()["plan_steps"]] == ["save_file"]
    assert body.json()["cannot"][0] == {"text": BROWSE[0], "reason": "no_host"}


def _taught(*steps):
    rows = [
        {"text": text, "tool": tool, "action": action, "verb": verb, "ask_first": False, "must_ask": False}
        for text, tool, action, verb in steps
    ]
    return {
        "id": "tsk_browser", "owner": PRIYA, "name": "Site check", "status": "learning", "version": 1, "plan": rows,
        "scope": {"kind": "just_me", "team": None}, "inputs": [],
    }  # fmt: skip


def test_DEMO_BROWSER_the_catalog_flags_a_skill_with_a_browse_step():
    from tilo_api.skills_route import taught_entries

    entry = taught_entries([_taught(("Open youtube.com", "web", "browse_web", "read"))], PRIYA)[0]
    assert entry["needs_browser_control"] is True


def test_DEMO_BROWSER_wording_alone_does_not_flag_a_skill():
    from tilo_api.skills_route import taught_entries

    worded = _taught(("Open youtube.com and click the first video", "web", "web_search", "read"))
    assert taught_entries([worded], PRIYA)[0]["needs_browser_control"] is False
