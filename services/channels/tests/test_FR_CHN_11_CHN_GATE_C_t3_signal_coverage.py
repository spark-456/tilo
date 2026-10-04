"""CHN-GATE-C (issue #256, "T3 signal coverage"; FR-CHN-11; PRD 10.4 T3 "money, contract or legal terms", 11.4):
the deterministic money / legal / commitment signal must not let plain-ASCII commitments ride the L2 undo window.
The policy port here always answers L2, so only the autopilot's own tiering can stop an auto-send.

Defaults applied (BQ-186, the user delegated the decision):
 (a) L2 auto-send is an ALLOWLIST: a short body made only of ordinary scheduling talk (greeting, a sign-off, names,
     weekdays, thanks, "works for us", "see you then"), no digits other than a time of day (2pm, 3:30pm, 10am: the
     existing FR-CHN-11 benign bodies carry "2pm"), no commitment / money / legal word, no link. Anything else that
     carries a reply is T3 (modifier `money_or_legal`, the only content condition in config/autonomy.yaml), so
     Spanish, German without umlauts, Indonesian / Malay, Tagalog, Swahili or romanised Hindi written in plain ASCII
     are T3 because their words are not on the list, not because a word list names them.
     "Short" is at most 2,000 characters: the existing FR-CHN-11 preview test (the 600-char excerpt one in
     test_FR_CHN_11_preview_and_undo.py) pins a 1,560-character benign body at tier T2, and an existing test wins.
 (b) The word lists grow (transfer, account number, sort code, paypal / venmo / zelle / btc, owe, loan, penalty,
     agree / accept / authorise / sign, solicitor, gdpr, bucks / grand / quid / Rs / RM, "5k" and bare amounts), and
     plain-ASCII paraphrases of a promise are T3.
 (c) Visible split or leetspeak words (re-fund, r.e.f.u.n.d, r3fund, c0ntract, re<CR>fund) are read after separators
     are dropped and digit look-alikes are mapped back, and are T3.
Existing FR-CHN-10/11/12/13 tests stay as they are; nothing here contradicts them (their benign lines are controls
below). API: API_FR_CHN_11.md (`t3_content_signal`, `Autopilot.preview`); no new name is needed."""

from __future__ import annotations

import pytest
from _chn11_lib import USER, autopilot_module, make_bench, pair, scripted_thread
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SHORT_BODY_MAX = 2_000  # BQ-186: the longest body that may ride L2; the existing test pins 1,560 characters at T2


def wrap(line: str) -> str:
    return f"Hi David,\n\n{line}\n\nBest,\nSarah"


def never_auto_sent(body: str) -> None:
    """Through the public interface: an L2 policy, a ready draft, and the card is T3, L1, nothing scheduled."""
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, body))
    assert card.tier == "T3" and "money_or_legal" in card.modifiers, f"auto-send allowed for {body!r}"
    assert (card.level, card.undo_window_s, card.outbox_id) == ("L1", 0, None)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}, "T3 is never scheduled without a person"


def auto_sent(body: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, body))
    assert card.tier == "T2" and card.modifiers == (), f"harmless reply made T3: {body!r}"
    assert (card.level, card.undo_window_s) == ("L2", 60) and card.outbox_id is not None


# ---- negative controls: short harmless scheduling replies stay eligible for L2 --------------------------------------

CONTROLS = [
    "Thanks, see you Tuesday.",
    "Thanks David, Friday 2pm works for us.",  # existing FR-CHN-11 line
    "Sounds good, talk soon.",  # existing
    "Happy to meet next week.",  # existing
    "See you then.",  # existing
    "Tuesday at 3:30pm works for us. See you then.",
    "10am Monday works, thanks.",
]


@pytest.mark.parametrize("text", CONTROLS)
def test_CHN_GATE_C_FR_CHN_11_short_harmless_scheduling_replies_give_no_signal(text: str) -> None:
    assert autopilot_module().t3_content_signal(text) == frozenset()
    assert autopilot_module().t3_content_signal(wrap(text)) == frozenset()


@pytest.mark.parametrize("text", CONTROLS)
def test_CHN_GATE_C_FR_CHN_11_short_harmless_scheduling_replies_still_ride_l2(text: str) -> None:
    auto_sent(wrap(text))


@settings(max_examples=40, deadline=None)
@given(st.lists(st.sampled_from(CONTROLS), min_size=1, max_size=4))
def test_CHN_GATE_C_FR_CHN_11_property_any_mix_of_harmless_lines_gives_no_signal(lines: list[str]) -> None:
    assert autopilot_module().t3_content_signal(wrap(" ".join(lines))) == frozenset()


# ---- (a) allowlist: digits, amounts, links, length -------------------------------------------------------------------

AMOUNTS = [
    "That works for 500.",
    "5k is fine.",
    "Let's say 5K.",
    "Ok, 1,200 it is.",
    "We can do 2.5 per unit.",
    "It is 95 all in.",
    "Make it 500 and we have a deal.",
]
LINKS = [
    "The agenda is at https://meet.example/abc",
    "See www.example.org for Friday.",
    "Details at example.com/agenda",
    "Friday 2pm works, join via http://meet.example/x",
]


@pytest.mark.parametrize("text", AMOUNTS + LINKS)
def test_CHN_GATE_C_FR_CHN_11_digits_amounts_and_links_give_the_signal(text: str) -> None:
    assert autopilot_module().t3_content_signal(wrap(text))


@pytest.mark.parametrize("text", AMOUNTS + LINKS)
def test_CHN_GATE_C_FR_CHN_11_digits_amounts_and_links_never_ride_l2(text: str) -> None:
    never_auto_sent(wrap(text))


def test_CHN_GATE_C_FR_CHN_11_a_body_over_the_short_limit_never_rides_l2() -> None:
    body = "Hi David,\n\n" + "Friday 2pm works for us. See you then. " * 100 + "\n\nBest,\nSarah"
    assert len(body) > SHORT_BODY_MAX
    never_auto_sent(body)


def test_CHN_GATE_C_FR_CHN_11_the_existing_1600_character_benign_preview_keeps_tier_t2() -> None:
    # The existing preview test pins this at L1 / T2; the allowlist limit must sit above it (BQ-186).
    body = "Hi David,\n\n" + "Friday 2pm works for us. See you then. " * 40 + "\n\nBest,\nSarah"
    assert len(body) <= SHORT_BODY_MAX
    assert autopilot_module().t3_content_signal(body) == frozenset()


# ---- (b) word-list additions -----------------------------------------------------------------------------------------

ADDED_WORDS = [
    "Please transfer it on Friday.",
    "Our account number is on the letterhead.",
    "Our sort code is on the letterhead.",
    "Send it by PayPal.",
    "Venmo me when you can.",
    "Use Zelle for that.",
    "We take BTC.",
    "I owe you one.",
    "They owe us for Friday.",
    "A loan would cover it.",
    "There is a penalty for late changes.",
    "We agree.",
    "I accept.",
    "Happy to authorise that.",
    "Please sign here.",
    "Our solicitor will call.",
    "This is covered by GDPR.",
    "That is fifty bucks.",
    "Ten grand should do it.",
    "Twenty quid, then.",
    "Rs 500 is fine.",
    "RM 200 is fine.",
    "5k works for us.",
]


@pytest.mark.parametrize("text", ADDED_WORDS)
def test_CHN_GATE_C_FR_CHN_11_added_money_legal_and_commitment_words_give_the_signal(text: str) -> None:
    assert autopilot_module().t3_content_signal(text)
    assert autopilot_module().t3_content_signal(wrap(f"Friday 2pm works for us. {text}"))


@pytest.mark.parametrize("text", ADDED_WORDS)
def test_CHN_GATE_C_FR_CHN_11_added_words_never_ride_l2(text: str) -> None:
    never_auto_sent(wrap(f"Friday 2pm works for us. {text}"))


PARAPHRASES = ["We agree.", "Consider it done.", "You have my word.", "I hereby accept."]


@pytest.mark.parametrize("text", PARAPHRASES)
def test_CHN_GATE_C_FR_CHN_11_plain_ascii_paraphrased_commitments_give_the_signal(text: str) -> None:
    assert autopilot_module().t3_content_signal(text)
    assert autopilot_module().t3_content_signal(wrap(text))


@pytest.mark.parametrize("text", PARAPHRASES)
@pytest.mark.parametrize("instruction", ["", "Tell David Friday 2pm works."])
def test_CHN_GATE_C_FR_CHN_11_plain_ascii_paraphrased_commitments_never_ride_l2(text: str, instruction: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, wrap(f"Friday 2pm works for us. {text}"), instruction=instruction))
    assert card.tier == "T3" and (card.level, card.outbox_id) == ("L1", None)
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}


# Plain-ASCII Latin-script replies. None of these needs a word list: their words are not ordinary English scheduling
# talk, so the allowlist rule alone makes them T3. The last of each pair carries a real commitment or payment.
FOREIGN = [
    ("es", "Hola David, el viernes nos viene bien. Nos vemos pronto, gracias."),
    ("es", "Hola David, le devolvemos el dinero manana sin falta."),
    ("de", "Hallo David, am Freitag passt es uns gut. Bis bald, danke schoen."),
    ("de", "Hallo David, wir erstatten Ihnen den Betrag am Freitag."),
    ("id", "Halo David, hari Jumat cocok untuk kami. Sampai jumpa, terima kasih."),
    ("id", "Halo David, kami kirim uangnya besok pagi."),
    ("ms", "Hai David, hari Jumaat sesuai untuk kami. Jumpa lagi, terima kasih."),
    ("ms", "Hai David, kami bayar semula wang itu esok."),
    ("tl", "Kumusta David, okay po sa amin ang Biyernes. Salamat, kita ulit tayo."),
    ("tl", "Kumusta David, babayaran namin kayo bukas."),
    ("sw", "Habari David, Ijumaa inatufaa sana. Tutaonana hivi karibuni, asante."),
    ("sw", "Habari David, tutakulipa kesho asubuhi."),
    ("hi", "Namaste David, Shukravar ko milte hain. Bahut dhanyavaad, jaldi baat karenge."),
    ("hi", "Namaste David, main paisa wapas kar dunga kal subah."),
]


@pytest.mark.parametrize(("lang", "text"), FOREIGN)
def test_CHN_GATE_C_FR_CHN_11_plain_ascii_latin_script_languages_give_the_signal(lang: str, text: str) -> None:
    assert autopilot_module().t3_content_signal(text), lang


@pytest.mark.parametrize(("lang", "text"), FOREIGN)
def test_CHN_GATE_C_FR_CHN_11_plain_ascii_latin_script_languages_never_ride_l2(lang: str, text: str) -> None:
    never_auto_sent(f"{text}\n\nBest,\nSarah")


# ---- (c) visible split and leetspeak words ---------------------------------------------------------------------------

SPLIT_OR_LEET = [
    "We can offer a re-fund.",
    "We can offer a r.e.f.u.n.d.",
    "We can offer a r-e-f-u-n-d.",
    "We can offer a re_fund.",
    "We can offer a re*fund.",
    "We can offer a r3fund.",
    "Please sign the c0ntract.",
    "Please sign the con-tract.",
    "The 1nvoice is below.",
    "The inv.oice is below.",
    "P@yment is due on receipt.",
    "No l3gal claim.",
    "Please w1re it.",
    "We can offer a re\rfund.",
    "We can offer a re\r\nfund.",
]


@pytest.mark.parametrize("text", SPLIT_OR_LEET)
def test_CHN_GATE_C_FR_CHN_11_split_and_leetspeak_words_give_the_signal(text: str) -> None:
    assert autopilot_module().t3_content_signal(text)


@pytest.mark.parametrize("text", SPLIT_OR_LEET)
def test_CHN_GATE_C_FR_CHN_11_split_and_leetspeak_words_never_ride_l2(text: str) -> None:
    never_auto_sent(wrap(f"Friday 2pm works for us. {text}"))


BANNED = [
    "refund",
    "invoice",
    "contract",
    "payment",
    "guarantee",
    "liability",
    "lawsuit",
    "deposit",
    "wire",
    "promise",
    "transfer",
    "penalty",
    "solicitor",
    "paypal",
    "agree",
    "accept",
    "authorise",
    "settlement",
    "commit",
]
LEET = {"o": "0", "e": "3", "a": "4", "i": "1", "s": "5", "t": "7"}


@st.composite
def disguised_banned_word(draw: st.DrawFn) -> str:
    word = draw(st.sampled_from(BANNED))
    out: list[str] = []
    for index, letter in enumerate(word):
        if letter in LEET and draw(st.booleans()):
            out.append(LEET[letter])
        else:
            out.append(letter.upper() if draw(st.booleans()) else letter)
        if index < len(word) - 1:
            out.append(draw(st.sampled_from(["", "", "-", ".", "_", "*"])))
    return "".join(out)


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    word=disguised_banned_word(),
    before=st.sampled_from(["Hi David,", "Thanks,", "Friday 2pm works for us."]),
    after=st.sampled_from(["See you then.", "Best, Sarah", "Talk soon."]),
)
def test_CHN_GATE_C_FR_CHN_11_property_a_banned_word_after_separator_and_leet_normalisation_is_t3(
    word: str, before: str, after: str
) -> None:
    assert autopilot_module().t3_content_signal(f"{before} {word} {after}"), word


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(word=disguised_banned_word())
def test_CHN_GATE_C_FR_CHN_11_property_a_disguised_banned_word_never_rides_l2(word: str) -> None:
    never_auto_sent(wrap(f"Friday 2pm works for us. {word}."))
