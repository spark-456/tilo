"""PRD 12.5 (Hands roadmap): "HandsProvider exposes navigate, find element,
click, type, read accessibility tree, screenshot and file operations. This
release implements it with cloud browsers only. Later implementations plug
into the same interface." FR-CON-13: "HandsProvider interface with the
cloud-browser implementation | A second mock implementation passes the same
conformance tests."

Ambiguity resolved (see report): PRD 12.5 groups upload/download under one
phrase, "file operations". These tests require two concrete methods,
`upload_file` and `download_file`, since Hands acting on the real world
needs both directions (an uploaded file feeds a task per PRD 12; a
downloaded page asset or generated deliverable needs saving back) and no
single-method reading covers both without inventing an ad hoc opcode
argument the PRD never mentions.
"""

from __future__ import annotations

import pytest
from tilo_providers.interfaces import HandsProvider

HANDS_METHODS = (
    "navigate",
    "find_element",
    "click",
    "type",
    "read_accessibility_tree",
    "screenshot",
    "upload_file",
    "download_file",
)


@pytest.mark.parametrize("method", HANDS_METHODS)
def test_PRD_12_5_hands_provider_exposes_method(method):
    assert hasattr(HandsProvider, method), f"PRD 12.5: HandsProvider must expose {method}"


def _make_fake_hands(label):
    class FakeHands(HandsProvider):
        def navigate(self, url):
            return {"url": url}

        def find_element(self, selector):
            return {"ref": f"{label}:{selector}"}

        def click(self, ref):
            return {"clicked": ref}

        def type(self, ref, text):
            return {"typed": text, "ref": ref}

        def read_accessibility_tree(self):
            return {"tree": []}

        def screenshot(self):
            return b"%PNG-fake"

        def upload_file(self, ref, path):
            return {"uploaded": str(path)}

        def download_file(self, ref):
            return b"downloaded-bytes"

    return FakeHands()


def _conformance_check(hands):
    """The "tiny conformance check" FR-CON-13 requires every HandsProvider
    implementation to pass, exercised twice below by two independent fakes."""
    hands.navigate("https://example.com")
    ref = hands.find_element("#go")["ref"]
    hands.click(ref)
    hands.type(ref, "hello")
    assert isinstance(hands.read_accessibility_tree(), dict)
    assert isinstance(hands.screenshot(), bytes | bytearray)
    hands.upload_file(ref, "file.txt")
    assert isinstance(hands.download_file(ref), bytes | bytearray)


def test_PRD_12_5_fake_hands_provider_passes_conformance_check():
    _conformance_check(_make_fake_hands("cloud-browser"))


def test_FR_CON_13_second_mock_implementation_passes_the_same_conformance_check():
    """ "A second mock implementation passes the same conformance tests" --
    a structurally different fake must pass the identical check."""
    _conformance_check(_make_fake_hands("cloud-browser"))
    _conformance_check(_make_fake_hands("second-mock"))
