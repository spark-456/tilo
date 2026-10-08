"""Every Google Meet selector lives here, and nowhere else.

Each selector is an ordered list of strategies, tried in turn until one matches a visible element.
Strategies match on role + accessible name, aria-label or visible text. Never CSS classes (Meet's are obfuscated
and change without notice).

Strategy forms (see browser.locate):
  ("role", "<aria role>", "<name regex>")
  ("text", "<regex>")
  ("aria", "<substring of aria-label>")   -> [aria-label*="..." i]
  ("aria_region", "<substring>")          -> [role="region"][aria-label*="..." i]
  ("placeholder", "<regex>")

Confidence notes are in README "Least certain selectors". Language is forced to en-US in the browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

Strategy = tuple[str, ...]


@dataclass(frozen=True)
class Sel:
    name: str
    strategies: tuple[Strategy, ...]


def _s(name: str, *strategies: Strategy) -> Sel:
    return Sel(name, tuple(strategies))


MEET_NEW_URL = "https://meet.google.com/new"
MEET_HOME_URL = "https://meet.google.com/"
MEETING_URL_RE = re.compile(r"https://meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})")
LOGIN_HOSTS = ("accounts.google.com",)

# --- pre-join screen -------------------------------------------------------------------------------------------
CONTINUE_WITHOUT_MEDIA = _s(
    "continue_without_media",
    ("role", "button", r"continue without (microphone|camera|audio)"),
    ("text", r"continue without (microphone|camera)"),
)
MIC_TURN_ON = _s("mic_turn_on", ("role", "button", r"turn on microphone"), ("aria", "Turn on microphone"))
MIC_TURN_OFF = _s("mic_turn_off", ("role", "button", r"turn off microphone"), ("aria", "Turn off microphone"))
CAM_TURN_OFF = _s("cam_turn_off", ("role", "button", r"turn off camera"), ("aria", "Turn off camera"))
JOIN_NOW = _s("join_now", ("role", "button", r"^(join now|switch here)$"), ("text", r"^join now$"))
ASK_TO_JOIN = _s("ask_to_join", ("role", "button", r"ask to join"), ("text", r"^ask to join$"))
CLOSE_DIALOG = _s("close_dialog", ("role", "button", r"^close$"))
GOT_IT = _s("got_it", ("role", "button", r"^(got it|dismiss|ok)$"))
ACCOUNT_BUTTON = _s("account_button", ("aria", "Google Account"))
SIGN_IN = _s("sign_in", ("role", "link", r"^sign in$"), ("role", "button", r"^sign in$"))

# --- waiting / ended states ------------------------------------------------------------------------------------
WAITING_TEXT = _s(
    "waiting_text",
    ("text", r"asking to be let in|someone will let you in|waiting for (the host|someone)|let you in soon"),
)
DENIED_TEXT = _s("denied_text", ("text", r"denied your request|no one responded|can.?t join this (video )?call"))
ENDED_TEXT = _s(
    "ended_text",
    ("text", r"you.ve been removed|the meeting has ended|you left the meeting|call ended|return to home screen"),
)

# --- in call ---------------------------------------------------------------------------------------------------
LEAVE_CALL = _s("leave_call", ("role", "button", r"leave call"), ("aria", "Leave call"))
CAPTIONS_ON = _s("captions_turn_on", ("role", "button", r"turn on captions"), ("aria", "Turn on captions"))
CAPTIONS_OFF = _s("captions_turn_off", ("role", "button", r"turn off captions"), ("aria", "Turn off captions"))
MORE_OPTIONS = _s("more_options", ("role", "button", r"more options"), ("aria", "More options"))
CAPTIONS_REGION = _s("captions_region", ("aria_region", "aption"))
CHAT_OPEN = _s("chat_open", ("role", "button", r"chat with everyone"), ("aria", "Chat with everyone"))
CHAT_INPUT = _s(
    "chat_input",
    ("role", "textbox", r"send a message"),
    ("aria", "Send a message to everyone"),
    ("placeholder", r"send a message"),
)
CHAT_SEND = _s("chat_send", ("role", "button", r"send a message"), ("aria", "Send a message"))
PEOPLE_BUTTON = _s("people_button", ("role", "button", r"^(people|show everyone)"), ("aria", "Show everyone"))

# Lines inside the captions region that are UI, not speech (compared case-insensitively, exact match).
CAPTION_NOISE_LINES = frozenset({"jump to bottom", "captions", "live captions", "arrow_downward"})
# Material icon ligatures leak into text as snake_case words, e.g. "format_size".
ICON_LIGATURE_RE = re.compile(r"^[a-z]+(_[a-z0-9]+)+$")

ALL_SELECTORS: tuple[Sel, ...] = tuple(v for v in globals().values() if isinstance(v, Sel))

# --- admitting and participants (added for auto-admit and the "required people are here" gate) ---------------------
ADMIT_PILL = _s("admit_pill", ("role", "button", r"admit \d+ guest|admit all|view all"))
# The row button's accessible name may include the person ("Admit John Regi"); the top pill is "Admit 1 guest".
ADMIT_BUTTON = _s(
    "admit_button",
    ("role", "button", r"^admit$|^admit (?!\d+ guests?|all)"),
    ("text", r"^admit$"),  # role-agnostic: the row control is not always exposed as a button
)
WAITING_MARK = _s("waiting_mark", ("text", r"waiting to join|waiting to be admitted"))
# Last resort: click any leaf element whose text is exactly "Admit" (not the "Admit N guest" pill).
ADMIT_CLICK_JS = r"""
(allowed) => {
  const rowOf = e => ((e.closest('[role="listitem"]') || e.parentElement.parentElement || e).innerText || '').trim();
  const els = [...document.querySelectorAll('button,[role="button"],a,span,div')]
    .filter(e => e.childElementCount === 0 && /^admit$/i.test((e.innerText || '').trim()))
    .filter(e => !allowed.length || allowed.some(a => rowOf(e).toLowerCase().includes(a)));
  els.forEach(e => e.click());
  return els.map(rowOf);
}
"""
PEOPLE_PANEL_MARK = _s("people_panel_mark", ("text", r"in the meeting|waiting to join|contributors"))
# Reads the People panel: every list item's text, and whether it has an Admit button (i.e. is waiting).
PARTICIPANTS_JS = r"""
() => [...document.querySelectorAll('[role="listitem"]')].map(li => ({
  text: (li.innerText || '').trim(),
  waiting: [...li.querySelectorAll('button')].some(b => /^admit( |$)/i.test((b.innerText || b.getAttribute('aria-label') || '').trim()) && !/^admit (\d+ guest|all)/i.test((b.getAttribute('aria-label') || b.innerText || '').trim()))
}))
"""
# Text of the row that holds an Admit button, so we can check the name against an allowlist.
ROW_TEXT_JS = "el => ((el.closest('[role=\"listitem\"]') || el.parentElement.parentElement).innerText || '').trim()"
# First-line noise in participant rows that is not part of the name.
PARTICIPANT_NOISE = ("(you)", "meeting host", "host", "co-host", "presentation", "you")

# Reads the chat panel: message nodes if Meet tags them, plus the panel's plain text (parsed in chatread.py) and its HTML
# (saved once to debug/ so the parser can be checked against the real DOM).
CHAT_READ_JS = r"""
() => {
  const items = [...document.querySelectorAll('[data-message-id]')].map(n => ({
    id: n.getAttribute('data-message-id') || '', sender: n.getAttribute('data-sender-name') || '',
    text: (n.innerText || '').trim() }));
  const box = document.querySelector('textarea[aria-label*="Send a message" i]');
  let panel = null;
  if (box) { let p = box; for (let i = 0; i < 10 && p.parentElement; i++) { p = p.parentElement;
    if (/in-call messages/i.test(p.innerText || '')) { panel = p; break; } } }
  return { items, panelText: panel ? panel.innerText : null, panelHtml: panel ? panel.outerHTML.slice(0, 80000) : null };
}
"""
