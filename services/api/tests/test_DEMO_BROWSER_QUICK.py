"""DEMO-BROWSER: a person who asks Quick to use the browser is offered a world, which has Tilo's browser.

Quick answers with one cheap model call and opens no browser. "browser" was not one of config/quick.yaml's tool words,
so "Use the browser to open wikipedia.org and summarise today's featured article" went to the model classifier,
which may call it simple. A text that names the browser is work that needs tools: Quick offers to make a world.
"""

from __future__ import annotations

from tilo_api.quick_rules import Verdict, classify, load_quick_rules


def test_DEMO_BROWSER_a_browser_task_is_offered_a_world_by_rules():
    rules = load_quick_rules()
    text = "Use the browser to open wikipedia.org and summarise today's featured article"
    assert classify(rules, text, max_chars=2000, has_files=False, scenario=False) == Verdict("work", "needs_tools")


def test_DEMO_BROWSER_a_plain_question_is_still_simple():
    rules = load_quick_rules()
    assert classify(rules, "What is the capital of France?", max_chars=2000, has_files=False, scenario=False) == (
        Verdict("simple")
    )
