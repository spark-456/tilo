"""DEMO-BROWSER-FAKE: deterministic read-only actions for an offline skill demo."""

import json

from tilo_providers.interfaces import GenerateRequest


def test_DEMO_BROWSER_FAKE_searches_allowlisted_wikipedia_without_a_commit():
    from tilo_providers.fake_browser import FakeBrowserProvider

    model = FakeBrowserProvider()
    goal = "Search https://en.wikipedia.org for Ada Lovelace and summarize the top 3"
    first = json.loads(model.generate(GenerateRequest(prompt=f"Goal: {goal}\nCompleted browser actions: ")).text)
    assert first == {"kind": "navigate", "url": "https://en.wikipedia.org/wiki/Special:Search?search=Ada+Lovelace"}
    second = json.loads(
        model.generate(
            GenerateRequest(prompt=f"Goal: {goal}\nCompleted browser actions: navigate\nExtracted page text: ")
        ).text
    )
    assert second == {"kind": "extract"}
    third = json.loads(
        model.generate(
            GenerateRequest(
                prompt=f"Goal: {goal}\nCompleted browser actions: navigate, extract\nExtracted page text: Three results"
            )
        ).text
    )
    assert third == {"kind": "done"}
