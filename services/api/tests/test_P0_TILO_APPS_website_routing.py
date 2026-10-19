"""P0_TILO_APPS: Deliverable routing for websites, landing pages, forms, and questionnaires.

Verifies that:
1. 'make a website questionnaire', 'build a landing page for X', and 'create a signup form'
   produce native website deliverables with format 'website' and make_with 'native', never markdown.
2. deliverable kinds aliases are loaded from config/deliverable_kinds.yaml.
3. makers.make_choices keeps signup forms and landing pages as native Tilo deliverables rather than large sites.
"""

from __future__ import annotations

import pytest
from tilo_api import makers
from tilo_api.intake import safe_app_brief
from tilo_planning.deliverable_kinds import load_deliverable_kinds


class _Views:
    def view(self, owner: str, connector: str):
        return None, [], None


def _brief(title: str = "Deliverable", fmt: str = "markdown") -> dict:
    return {"goal": "Build it", "deliverables": [{"title": title, "format": fmt}]}


@pytest.mark.parametrize(
    "task_text",
    [
        "make a website questionnaire",
        "Make a website questionnaire for our customers",
        "build a landing page for X",
        "Build a landing page for our new product",
        "create a signup form",
        "Create a signup form for newsletter",
        "create a sign up form",
    ],
)
@pytest.mark.parametrize("model_format", ["markdown", "app"])
def test_P0_TILO_APPS_safe_app_brief_routes_to_website(model_format: str, task_text: str) -> None:
    requested = _brief("Product", model_format)
    result = safe_app_brief(requested, task_text, [])
    assert result["deliverables"][0]["format"] == "website"


def test_P0_TILO_APPS_deliverable_kinds_config_includes_website_aliases() -> None:
    kinds = load_deliverable_kinds()
    website = next((k for k in kinds if k.format == "website"), None)
    assert website is not None
    aliases = {a.lower() for a in website.aliases}
    assert {"questionnaire", "landing page", "signup form", "form"} <= aliases


@pytest.mark.parametrize(
    "goal,title",
    [
        ("Make a website questionnaire for our customers", "Customer questionnaire"),
        ("Build a landing page for our new product", "Landing page"),
        ("Create a signup form for newsletter", "Signup form"),
        ("Create a sign up form", "Sign up form"),
    ],
)
def test_P0_TILO_APPS_makers_choice_defaults_to_native(goal: str, title: str) -> None:
    brief = {
        "goal": goal,
        "deliverables": [{"title": title, "format": "website"}],
    }
    choices = makers.make_choices(brief, "u_test", views=_Views())
    assert len(choices) == 1
    assert choices[0]["selected"] == "native"
    assert not any(o["suggested"] for o in choices[0]["options"] if o["make_with"] != "native")
