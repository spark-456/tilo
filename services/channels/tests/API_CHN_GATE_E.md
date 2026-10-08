# CHN-GATE-E: the API the tests pin (FR-CHN-11, ADR-0025)

Source of truth: `docs/adr/0025-draftcontext-thread-participants.md` (Accepted by the user, 2026-10-07). This file only
lists the names the tests import, so the builder does not guess them.

## `tilo_channels.participants` (new module)

- `Participant(address: str, names: frozenset[str])`: a frozen dataclass, exactly these two fields in this order.
  `address` is a bare lower-case ASCII address (`drafting._address`); `names` are lower-case words that passed the
  filter. The class lives in this module (the tests import it from here).
- `read_participants(reader, user_id, thread_id, mailbox) -> tuple[Participant, ...]`: reads the last `MAX_MESSAGES`
  messages through `reader.get_thread` only, newest first. Never raises. The mailbox owner is always one participant
  (address = the mailbox, names = its local part words plus its From name on `SENT` mail), even with no thread or a
  failed read: then `{mailbox: {local part}}` is the whole result.
- Name filter, caps: ADR-0025 decisions 4 and 7 (100 participants, one per base address, 8 name words each; a word is
  2 to 24 ASCII letters, at most 4 words, `inbound_signal` clean joined with spaces and with nothing, no `_numberish`
  word or neighbour join). Each source (display name, local part) is filtered on its own and dropped whole.

## `tilo_channels.autopilot`

- `DraftContext` gains the LAST field `participants: tuple[Participant, ...] = ()`. Still a frozen dataclass, no
  schema in `contracts/`.
- `Autopilot._card` replaces `context.participants` with `read_participants(self._reader, ...)` before `_decision`; a
  caller's value (any type) is thrown away. `_decision` calls `t3_content_signal(draft.body, names=...)` with the names
  of the participants whose address is the draft's own To or Cc, plus the mailbox's.
- Nothing about participants is stored in the card, the draft store, events or logs, or returned in `Preview`.

## `tilo_channels.autopilot_t3`

- `t3_content_signal(text, names=frozenset())`; `_unlisted` lets a word pass if it is in `_WORDS` (with `_GREETING` and
  `_SIGN_OFF` added) or in `names`. No position rules. A row of name words is at most 2 long and every join runs
  through `_FAMILIES` (answer: "unlisted", or the family). `_numberish` stays, used only by the name filter.

## Bench migration (tests only)

`_chn10_lib.Rig.own_mail` / `make_rig(own_mail=...)`, `_chn11_lib.named_rig()`, `make_bench()` (and the CHN-GATE-A,
CHN-WIRE-4 and FR-CHN-13 benches) start every thread with one SENT message from `Sarah Chen <ops@...>` to the mailbox
itself, so "Sarah" is vouched; "David" is vouched by the address local part `david.miller@...`. `scripted_thread(names=...)`
adds display names the user's SENT mail gives the draft's recipient. `_chn_gate_e_lib.make_bench` has no such note.
