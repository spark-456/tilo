# ADR-0025: DraftContext thread participants (the L2 name slot)

- Status: Accepted (user, 2026-10-07). The user's own message: "I accept ADR-0025 (DraftContext
  thread participants, PR #536) as written: names come only from the draft's recipients and the
  mailbox, and I accept the residual risk. #525 is already merged". It changes what may ride the L2
  undo window, which is a T3 path, so its build ticket (CHN-GATE-E) still gets a security review and
  the user's yes before merge (root `CLAUDE.md`). Numbered 0025 because ADR-0024 is taken by PR #501.
- Deciders: user (approval), architect (proposal)
- Requirement: FR-CHN-11 and FR-CHN-12 (PRD 10.4: L2 is for T2 only, and "money, contract or legal
  terms" is T3). Related: issue #298 (the name slot), PR #525 (CHN-GATE-D), BQ-224,
  BQ-154/BQ-223, BQ-274, ADR-0013.

## Context
1. A draft rides L2 only if `t3_content_signal` (`tilo_channels/autopilot_t3.py` in
   `services/channels`) finds nothing. Its allowlist (BQ-224) admits scheduling words, times of day
   and names. The gate has no list of names, so it guesses them by position: a Title-case run of up
   to two words after the greeting or at the signature, plus repeats of those words.
2. So anything in that position counts as a name: "Hi Fifty Thousand, works for us." rode L2
   (#298). PR #525 (head 24b6475f) closed this over four security rounds by adding rules: run
   endings (`_name_run`), clause openers (`_opens_clause`) and number words (`_NUMBER_WORDS`,
   `_numberish` rules a to c, `_NUMBER_ONLY`, `_NUMBER_START`, `_MAGNITUDE_INSIDE`,
   `_NAME_WORD_MAX`). Round 4 passed, but still lists forms sent at L2 ("Rmten", "Tenyen", "Tenkk",
   "Agrand", "Tenish", "Ninty", "Tenner") and real names sent to T3 (Crowe, Fournier, Lakhani).
   Both reviewers, and #298 itself, name the real fix: check the slot against the participants.
3. `DraftContext` is a frozen dataclass in `tilo_channels/autopilot.py` (instruction_id, thread_id,
   instruction, mailbox, mode). It is **not a contract**: no schema in `contracts/`, no generated
   type. It is never stored (the card keeps its own copy of each field) and never leaves the
   process. Four places build it: `Autopilot.edit`, `meeting_followup` (no thread, mode "new",
   always T3), `plate_reply` (empty instruction, never L2) and the callers of `preview`.
4. Each decision already reads the thread twice through the quarantined `ThreadReader`: in `_known`
   (trusted recipients, BQ-154/BQ-223) and in `inbound_is_clean` (BQ-274).
5. Someone chooses every name in a mail header. A sender picks its own From display name and local
   part, and can write any display name for anyone else in To or Cc.

## Decision
1. **The field.** `DraftContext` gains `participants: tuple[Participant, ...] = ()`, where
   `Participant(address: str, names: frozenset[str])` holds a bare lower-case ASCII address (as
   `drafting._address` makes it) and the lower-case name words that pass the filter in 4. Nothing
   else is kept: no subject, body, date, message id or label.
2. **Who fills it.** Only the Autopilot. Before `_decision`, `Autopilot._card` replaces the field
   with `read_participants(self._reader, user_id, context.thread_id, context.mailbox)` (new module
   `tilo_channels/participants.py`). A caller's value is thrown away: no route, request body,
   card, model output or drafter result ever fills it. An Edit reads the thread again. The builder
   may share one fetch with `_known` and `inbound_is_clean`; their trust rules do not change.
3. **Where names come from.** The last `MAX_MESSAGES` messages, headers parsed with the same bounded
   parser and caps as `_addresses`. Names come only from the draft's recipients and the mailbox
   owner:
   - To and Cc display names on the mailbox's own `SENT` messages (the user's client wrote them);
   - the words of every participant's address local part, split on `. _ - +`;
   - for the mailbox: its local part, and its From display name on `SENT` messages only (the user's
     own SENT mail, not inbound mail).
   An inbound participant's own From display name is NOT a name source, and neither is a display
   name a third party wrote for someone else (an inbound To or Cc): both name nobody. No thread, or
   a failed read: the only names are the mailbox's local part (fail closed).
4. **Name filter.** A display name or local part is split into words on spaces, `.`, `,` and `-`,
   and dropped whole unless: every word is 2 to 24 ASCII letters (one inner apostrophe allowed);
   there are at most 4 words; `inbound_signal` finds nothing in the words joined with spaces or
   with nothing; and no word, nor two neighbouring words joined, is `_numberish` (moved from
   PR #525 unchanged; it now reads short header names, not the body).
5. **The gate.** `t3_content_signal(text, names=frozenset())`; every existing check stays. In
   `_unlisted` a word passes if it is in `_WORDS` (the `_GREETING` and `_SIGN_OFF` words added) or
   in `names`. A row of name words is still at most two long, and every join still runs through
   `_FAMILIES`. `names` holds the names of the draft's own To and Cc and of the mailbox, so a name
   a sender chose only ever goes back to that sender. No names (the default) fails closed.
6. **Numbers and amounts.** The thread never makes one allowed. A digit that is not a time of day,
   and any number word, stays "unlisted" even when the thread holds the same amount: repeating an
   amount back is still agreeing to money terms (PRD 10.4, T3).
7. **Privacy and caps.** Participants live in memory for one `_card` call only, and are never
   written to the card, the draft store, events, logs (counts only), exception messages or the
   model. Caps: 100 participants (newest message first, one per base address), 8 name words each;
   anything past a cap is dropped (fewer names, so more T3). No new connector scope, no contact
   names.
8. **No contract change.** Nothing in `contracts/` changes: no schema, generated type, version or
   fixture. If drafting ever moves to another process, a new ADR turns this shape into
   `contracts/draft_context.schema.json` 1.0.0.

## Heuristics this retires (code from PR #525)
- Guessing names by position: `_names`, `_name_run`, `_opens_clause`, `_CLAUSE_MARKS`, the
  signature-line detection in `_unlisted`, and the Title-case rule.
- Number checks on the body: `_numberish(j)` on body runs and joins. `_numberish` and its patterns
  stay only inside the name filter, frozen: no new unit or spelling gets added.
- These stay: `_WORDS`, `_FAMILIES` (with the join check on name runs), the two-word cap,
  `SHORT_BODY_MAX`, digit and link checks, obfuscation checks, the inbound checks (BQ-274) and the
  recipient trust rules (BQ-154, BQ-223).

## Alternatives considered
1. Keep adding body rules (the #525 path): each round closed one class, round 4 lists more, and
   every rule adds false positives.
2. Callers fill `participants`: rejected, a stamp taken from input (a recurring security finding).
3. A model or the SafetyProvider judges the greeting: rejected. Tiers are deterministic, and a model
   never decides authorisation (PRD 10.4).
4. No names at L2 (only "Hi," and "Hi there,"): safest and simplest, but most real drafts greet by
   name, so L2 would rarely apply. It is the fallback if this ADR is rejected.
5. Names from Google Contacts: needs a new scope and a contacts-port change; later, if wanted.
6. Names from every thread participant's own From display name: rejected by the user (2026-10-07),
   because it lets an inbound sender choose a name that then rides L2 back to it (see the residual
   risk below).

## Consequences
- A word the thread does not vouch for never fills a name slot, however it is spelled. The round 4
  forms above go to T3, and the number-word list stops growing.
- New safe false positives (T3, a person decides): a nickname in no header ("Dave" for David), a
  name of more than 4 words or with non-letters, a recipient the thread never names.
- Residual risk, accepted by the user (2026-10-07): a sender can still name itself through its own
  address local part (it chooses it), and an amount-like token the name filter misses (a glued form,
  as in the BQ-274 word-edge gap) could be sent back in a reply to a clean inbound message. The
  inbound From display name is no longer a source, which removes the widest channel. The name filter
  runs `inbound_signal`, and the BQ-274 word-edge fix landed as PR #550 (CHN-GATE-F), so
  CHN-GATE-E does not depend on it. What is left is the filter's own gaps, which the user accepts.
- One more thread read per decision, unless the fetch is shared.
- Migration: `participants` defaults to `()`, so every constructor still works. The channels
  benches (`services/channels/tests/_chn11_lib.py`, the GATE-C and GATE-D files) give their threads
  the display names their L2 bodies use; the #525 number-word bodies stay pinned as T3. No contract
  regeneration, fixture or schema bump.

## Tests it enables (build ticket CHN-GATE-E: tests first, names carry FR_CHN_11)
- Not in the thread is T3: "Hi Fifty Thousand, works for us." with only David in the thread; a
  property test: any word neither in `_WORDS` nor a participant name gives "unlisted".
- A recipient rides L2: "Hi David, works for us." with a `SENT` message `To: David Lee
  <david@example.com>`, and with only the address `david@example.com` (local part).
- Trust: an inbound `Cc: Fifty Thousand <david@example.com>` does not name David; an inbound
  `From: Fifty Thousand <sender@example.com>` does not name that sender (an inbound From name is
  not a source); an inbound `To: Tenk <mailbox>` does not name the user; a thread member who is not
  a recipient is T3. The mailbox's From name counts only on its own `SENT` mail.
- Filter: display names "Fifty Thousand", "Refunds Team", "Tenk" and "Legal Dept" name nobody.
- A caller's `participants` is thrown away; a failing reader leaves no names.
- Privacy: no participant name in the card, events or captured logs.
- Caps and time: a 101st participant, a 25-letter word and a 5-word name are cut; 50 messages of 50
  addresses stay within today's time per call.
- An amount or number word that appears in the thread is still "unlisted" in the draft.

## Decisions (user, 2026-10-07)
The user accepted this ADR in their own message (quoted under Status). Their answers to the three
questions below replace the supervisor's relayed answers.
1. The user ACCEPTS the residual self-echo risk. This is the ADR's original default and supersedes
   the supervisor's relayed answer 1 (do not accept it). The BQ-274 inbound word-edge fix landed
   anyway as PR #550 (CHN-GATE-F), so CHN-GATE-E no longer depends on it.
2. Names come only from the draft's recipients and the mailbox owner: the From name only on the
   user's own SENT mail, To and Cc names there, and address local parts. An inbound participant's own
   From display name is not a name source. Decision 3 above is edited to say exactly this, so the ADR
   does not contradict itself.
3. PR #525 merged as the interim fix (already done); CHN-GATE-E builds on it.

## Questions for the user (resolved by the user, 2026-10-07)
No row goes into `docs/open-questions.md`: all three are answered, and this ADR is the record.
1. Accept the residual risk, or land the BQ-274 inbound word-edge fix before CHN-GATE-E merges?
   Resolved: accepted; the BQ-274 fix merged anyway as PR #550.
2. Names only from the draft's recipients and the mailbox (decision 5), or from every thread
   participant? Resolved: recipients and mailbox only.
3. Merge PR #525 first as the interim fix? Resolved: yes, already merged.
