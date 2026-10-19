"""DEMO-BROWSER-MASK: card and OTP fields stay secure without autocomplete hints."""

from _browser_lib import textbox
from tilo_browser.login import is_secure_node


def test_DEMO_BROWSER_MASK_detects_card_and_otp_names_without_autocomplete():
    assert is_secure_node(textbox("card", "Card number", name="payment_card"))
    assert is_secure_node(textbox("code", "Code", dom_id="account_otp"))
    assert is_secure_node(textbox("pw", "Password", type="text"))
