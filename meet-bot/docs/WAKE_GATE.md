# FR-MTG-15 wake gate

The live session loads the aliases, the 30-second attention window and the 15-second after-reply window from
`config/meeting-wake.json`.

Owner decision (21 Oct 2026): "Its okay to answer everything on one on ones but even when its not, tilo must be able
to understand if we are calling it, there are chances of the word not being heard clearly."

- **One-on-one** (exactly one other person in the call): every spoken line of three words or more, and every typed
  line, is for Tilo. No name is needed.
- **Group calls**: a line is for Tilo when a sentence opens or ends by calling it. Caption mishearings count: the
  closed aliases, two-word splits ("tea low", "t low"), a close first-word match that is not an ordinary word (tile,
  till, Tyler and the like stay ordinary), and "assistant," / "notetaker," / "bot," said straight to it. A mention
  ("the Tilo report") is not a call.
- **Follow-ups**: the same speaker may follow up without the name for 30 seconds after addressing Tilo, and anyone's
  question in the 15 seconds after Tilo spoke is a follow-up to Tilo.
- **Typed chat**: one-on-one, or calling Tilo, or right after Tilo's reply. Direct typed input keeps the
  directed-chat marker. Unknown speakers cannot claim an attention window.

The gate is pure: transcript text, speaker, time and immutable attention state produce a decision without I/O or
providers. Group-call speech that does not call Tilo never reaches a model. Every `build_brain` live path installs
this gate; the shared brain's older standalone prototype behaviour remains for its replay fixtures. Proactive chat
and voice are off by default; the owner-managed `VOICE_NUDGES` setup flag opts in. Mandatory recording disclosure and
lifecycle notices keep their existing guards.

No real Meet or paid provider acceptance is claimed by the fake replay tests.
