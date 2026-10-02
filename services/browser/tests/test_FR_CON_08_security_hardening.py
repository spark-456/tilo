"""FR-CON-08 security hardening (PR #140 security round 1; PRD 12.3, 16.1 rule 1).

"A login page produces the card, never a filled field" has to hold for what real pages do:
fields with no id, fields the accessibility tree hides but a selector still reaches, fields
injected after load, and trees nested deeper than a recursive walk survives. Detection keys on
the NODE (not its id), `type()` re-reads and re-inspects the page, and anything it cannot prove
is an ordinary editable input is refused (fail closed).
"""

from __future__ import annotations

import json

import pytest
from _browser_lib import FakeDriver, FakeEngine, FakeWeb, button, doc, fake_secrets, node, password_box, textbox

S = fake_secrets()


def _idless_password(value: str | None = None) -> dict:
    n = node("textbox", "Password", type="password", autocomplete="current-password")
    if value is not None:
        n["value"] = value
    return n


# -- 5. secure fields are keyed on the node, not on a ref -------------------------------------------


def test_FR_CON_08_an_idless_password_field_is_a_login_page():
    from tilo_browser.login import detect_login

    sig = detect_login(
        chain=["https://example.com/a"], tree=doc(textbox("user", "Username"), _idless_password()), text=""
    )
    assert sig is not None and sig.kind == "password_field" and sig.refs == ()


@pytest.mark.parametrize(
    "field",
    [
        node("textbox", "Code", autocomplete="one-time-code"),
        node("textbox", "Enter the 6-digit code we texted you", inputmode="numeric", maxlength="6"),
    ],
    ids=["autocomplete", "label"],
)
def test_FR_CON_08_an_idless_otp_field_is_a_login_page(field):
    from tilo_browser.login import detect_login

    sig = detect_login(chain=["https://example.com/a"], tree=doc(field), text="")
    assert sig is not None and sig.kind == "otp_field"


def test_FR_CON_08_an_idless_password_page_raises_the_card_and_types_nothing(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add(
        "https://example.com/account", title="Account", tree=doc(textbox("user", "Username"), _idless_password())
    )
    out = rig.worker.navigate("https://example.com/account")
    assert out["login_required"] is True and out["login_kind"] == "password_field"
    assert len(rig.cards) == 1
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("user", "someone")
    assert rig.driver.typed == []


def test_FR_CON_08_a_secure_field_without_a_ref_makes_screenshot_fail_closed(make_rig):
    from tilo_browser.worker import ScreenshotRefused

    rig = make_rig()
    cvc = node("textbox", "CVC", autocomplete="cc-csc")
    rig.web.add("https://example.com/pay", title="Pay", tree=doc(textbox("q", "Search"), cvc))
    rig.worker.navigate("https://example.com/pay")
    with pytest.raises(ScreenshotRefused):
        rig.worker.screenshot()
    with pytest.raises(ScreenshotRefused):
        rig.worker.capture()
    assert rig.driver.screenshot_mask_refs == []


def test_FR_CON_08_a_secure_field_with_a_ref_is_still_screenshotted_with_its_mask(make_rig):
    rig = make_rig()
    rig.web.add("https://example.com/pay", title="Pay", tree=doc(textbox("q", "Search"), password_box("pw")))
    rig.worker.navigate("https://example.com/pay")
    rig.worker.screenshot()
    assert rig.driver.screenshot_mask_refs[-1] == ["pw"]


@pytest.mark.parametrize(
    "secure",
    [
        _idless_password("hunter-" + "x" * 8),
        node("textbox", "CVC", autocomplete="cc-csc", value="hunter-" + "x" * 8),
        node("textbox", "Code", autocomplete="one-time-code", value="hunter-" + "x" * 8),
    ],
    ids=["password", "cc-csc", "otp"],
)
def test_FR_CON_08_the_value_of_an_idless_secure_node_is_dropped_from_the_tree(make_rig, secure):
    rig = make_rig()
    rig.web.add("https://example.com/s", title="S", tree=doc(textbox("q", "Search", value="boots"), secure))
    rig.worker.navigate("https://example.com/s")
    tree = rig.worker.read_accessibility_tree()
    assert "hunter-" not in repr(tree) and "boots" in repr(tree)


# -- 6. type() only into an editable input that is in the fresh tree ---------------------------------


class _AxDriver(FakeDriver):
    """Real accessibility trees drop aria-hidden nodes, yet a DOM selector still reaches them."""

    def read_accessibility_tree(self):
        def strip(n):
            n["children"] = [strip(c) for c in n.get("children", []) if c.get("attrs", {}).get("aria-hidden") != "true"]
            return n

        return strip(super().read_accessibility_tree())


class _AxEngine(FakeEngine):
    def new_context(self, gate):
        driver = _AxDriver(self.web, gate, len(self.contexts))
        self.contexts.append(driver)
        return driver


def test_FR_CON_08_an_aria_hidden_password_field_reached_by_selector_is_refused(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    web = FakeWeb()
    hidden = password_box("pw", "Password")
    hidden["attrs"]["aria-hidden"] = "true"
    web.add("https://example.com/a", title="Account", tree=doc(textbox("q", "Search"), hidden))
    rig = make_rig(web, engine=_AxEngine(web))
    assert rig.worker.navigate("https://example.com/a")["login_required"] is False
    ref = rig.worker.find_element("#pw")["ref"]
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type(ref, S["password"])
    assert rig.driver.typed == []


@pytest.mark.parametrize("ref", ["nope", "", "q2"])
def test_FR_CON_08_a_ref_that_is_not_in_the_fresh_tree_is_refused(make_rig, ref):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/a", title="A", tree=doc(textbox("q", "Search")))
    rig.worker.navigate("https://example.com/a")
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type(ref, "x")
    assert rig.driver.typed == []


def test_FR_CON_08_a_ref_that_is_not_an_editable_input_is_refused(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/a", title="A", tree=doc(button("go", "Go"), textbox("q", "Search")))
    rig.worker.navigate("https://example.com/a")
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("go", "x")
    rig.worker.type("q", "boots")
    assert rig.driver.typed == [("q", "boots")]


def test_FR_CON_08_two_nodes_sharing_a_ref_are_refused_if_either_is_secure(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/a", title="A", tree=doc(textbox("dup", "Search"), password_box("dup")))
    rig.worker.navigate("https://example.com/a")
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("dup", "x")


# -- 7. type() re-inspects the page, so a field injected after load is caught -------------------------


def test_FR_CON_08_a_credential_field_injected_after_load_is_refused_and_raises_the_card(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/p", title="Page", text="Welcome", tree=doc(textbox("q", "Search")))
    out = rig.worker.navigate("https://example.com/p")
    assert out["login_required"] is False and rig.cards == []
    rig.driver.page.tree = doc(textbox("q", "Search"), textbox("pw2", "Password", type="text"))
    rig.driver.page.text = "Session expired. Enter your password to continue."
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("pw2", S["password"])
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("q", "boots")  # the whole page is a login wall now
    assert rig.driver.typed == []
    assert len(rig.cards) == 1 and json.dumps(rig.cards[0]).count(S["password"]) == 0


def test_FR_CON_08_a_password_asked_for_in_injected_page_text_alone_refuses_typing(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/p", title="Page", text="Welcome", tree=doc(textbox("q", "Search")))
    rig.worker.navigate("https://example.com/p")
    rig.driver.page.text = "Please type your password in the box below."
    with pytest.raises(CredentialEntryRefused):
        rig.worker.type("q", "boots")
    assert len(rig.cards) == 1 and rig.driver.typed == []


def test_FR_CON_08_the_injected_page_raises_one_card_per_host_however_often_typing_is_tried(make_rig):
    from tilo_browser.login import CredentialEntryRefused

    rig = make_rig()
    rig.web.add("https://example.com/p", title="Page", tree=doc(textbox("q", "Search")))
    rig.worker.navigate("https://example.com/p")
    rig.driver.page.tree = doc(textbox("q", "Search"), _idless_password())
    for _ in range(3):
        with pytest.raises(CredentialEntryRefused):
            rig.worker.type("q", "x")
    assert len(rig.cards) == 1


# -- a tree nested deeper than the walk allows fails closed, never with a RecursionError ---------------


def _deep_tree(depth: int) -> dict:
    deep = password_box("pw")
    for _ in range(depth):
        deep = node("generic", "", deep)
    return doc(deep)


def test_FR_CON_08_a_very_deep_tree_fails_closed_without_a_recursion_error(make_rig):
    from tilo_browser.login import CredentialEntryRefused, TreeTooDeep

    rig = make_rig()
    rig.web.add("https://example.com/deep", title="Deep", tree=_deep_tree(400))
    with pytest.raises(TreeTooDeep):
        rig.worker.navigate("https://example.com/deep")
    with pytest.raises((CredentialEntryRefused, TreeTooDeep)):
        rig.worker.type("pw", "x")
    with pytest.raises(TreeTooDeep):
        rig.worker.read_accessibility_tree()
    assert rig.driver.typed == []


def test_FR_CON_08_a_reasonably_deep_tree_is_still_walked(make_rig):
    rig = make_rig()
    rig.web.add("https://example.com/deep", title="Deep", tree=_deep_tree(100))
    out = rig.worker.navigate("https://example.com/deep")
    assert out["login_kind"] == "password_field"
    assert "pw" in repr(rig.worker.read_accessibility_tree())


def test_FR_CON_08_secure_field_refs_and_detection_survive_a_deep_tree_without_recursing():
    from tilo_browser.login import detect_login, secure_field_refs

    tree = _deep_tree(200)
    assert secure_field_refs(tree) == ["pw"]
    sig = detect_login(chain=["https://example.com/"], tree=tree, text="")
    assert sig is not None and sig.refs == ("pw",)
