# FR-MTG-15 wake gate

The live session loads the closed aliases and 30-second attention window from
`config/meeting-wake.json`. No fuzzy names, general questions or sole-attendee
shortcut can trigger a deployed reply. A follow-up request must come from the
same speaker inside the window. Room chat needs an explicit address; direct
typed input uses the existing directed-chat marker. Unknown speakers cannot
claim an attention window.

The gate is pure: transcript text, speaker, time and immutable attention state
produce a decision without I/O or providers. The shared brain's older standalone
prototype behavior remains available to its existing replay fixtures; every
`build_brain` live path installs the stricter gate. Proactive chat and voice are
off by default; the existing owner-managed `VOICE_NUDGES` setup flag opts in.
Mandatory recording disclosure and lifecycle notices retain their existing guards.

No real Meet or paid provider acceptance is claimed by the fake replay tests.
