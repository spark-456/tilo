# API pinned by the CL-LIVE-2 tests (CONNECTORS-LIVE slice 2, Req: CL-LIVE-2)

Slice 1 (`API_CL_LIVE_1.md`) made the real Google connectors read-only. Slice 2 lets a local live run WRITE through
them, and only through the outbox, the deterministic policy engine and a typed approval at an interactive terminal.
No contract change: Python in `services/connectors`, `evals/`, docs. Tests: `services/connectors/tests/test_CL_LIVE_2_*.py`
(helpers `_cl_live2_lib.py`) and `evals/tests/test_CL_LIVE_2_write_flags.py`. Run: `uv run pytest services/connectors -k CL_LIVE_2 -q`.

## Flags (run level)

| Flags | Result |
| --- | --- |
| `--real-connectors` | exactly CL-LIVE-1: every write door refuses `RealWritesDisabled`, zero write requests. Report `side_effects: real_read_only`. |
| `--real-connectors --allow-writes` | Gmail DRAFT and Drive save (`save_file`, `save_as_google_file`, `drive.file`) can execute, each after a typed approval. Report `real_write_gated`. Calendar, Lovable and the meeting host still refuse. |
| `--real-connectors --allow-writes --allow-send` | also Gmail `send_email`, through the same gate. Report `real_write_gated_send`. |
| `--allow-writes` without `--real-connectors`; `--allow-send` without `--allow-writes` | refused (`allow_writes_needs_real_connectors`, `allow_send_needs_allow_writes`), before any call. |
| any of them under `--replay`, a fake provider, CI, Cloud Run, or without the user's `LIVE=1` | refused by the CL-LIVE-1 guards (same codes). `--allow-writes` in a run with no person (`live-e2e`) is refused: `allow_writes_needs_a_person`. |
| `--dry-run --real-connectors --allow-writes` | no switch needed; prints `real-writes: write_gated (dry run: nothing built, nothing sent)`, one `real-connector <id>: scopes=... mode=...` line per connector and one `real-write <id> <action>: typed terminal approval` line per gated write. Builds nothing. |

## Module `tilo_connectors.real_writes`

* `WriteFlags(allow_writes, allow_send)`, `.mode` is the report word; `WriteGate(flags)` with `.bind(resolve, redact)`,
  `.review(card) -> Review | None`, `.approve(review, *, said, interactive) -> bool`, `.authorise(entry, connector)`,
  `.complete(...)`, `.executed` (action names only). `WriteRefused(SideEffectRefused)` has a fixed text and a `.code`:
  `not_bound`, `action_off`, `not_a_person`, `content_unavailable`, `no_approval`, `approval_spent`.
* `real.real_adapters(..., allow_writes=False, allow_send=False)`, `write_gate_of(adapters)`, `is_real_write_gated(adapters)`,
  `real_write_plan(registry, flags)`. New refusal code `send_needs_writes`.

## Rules the tests pin

1. A write reaches Google only if all hold: the entry was enqueued through the outbox (the policy engine allowed it), a
   person typed exactly `yes` at an interactive terminal for the payload (the digest of connector, action, recipients,
   destination, item and content as read from the send itself), `entry.authz.by == "person"`, the broker holds the
   write-scope token, and the outbox called the door with its own grant. Hold, `no`, anything but `yes`, piped input and
   `--auto-approve-t1t2` never approve a real write. The word is exactly `yes` (`YES`, `Yes`: no). Right before the prompt the
   terminal's input buffer is discarded (`live_topic.drain_stdin`: Windows `FlushConsoleInputBuffer`, POSIX
   `termios.tcflush`), so paste or early typing cannot answer it; if it cannot be discarded the write is held. A control,
   zero-width or bidi character in the subject, body, file name, recipients or destination holds the write
   (`hidden_characters`). `WriteGate.clear()` drops unused approvals (on a hold and at the run's end). No approval, or an approval of another payload: the entry ends
   `failed`, no request of any kind goes out, nothing is retried.
2. Exactly once: an approval is spent by the first entry that uses it; a retry of that entry (an ambiguous failure,
   a second dispatch) goes through the adapter's own earlier-attempt lookup and never makes a second draft or send.
3. Scopes: drafts ask for `gmail.compose` (+ `gmail.readonly` for the lookup); the send scope only behind
   `allow_send`, and only if the registry declares exactly it; Drive `drive.file`; Calendar `calendar.readonly`. A
   widened registry scope is `scope_widened`. No token for a write scope is `no_token`, before an adapter is returned.
4. The run's dev destination `thread-dev-1` means "no thread / the Tilo folder": the card shows that, and the digest uses it.
5. Privacy: the gate card text is the only place content appears (recipients, subject, a 300-character preview, through the
   secret redactor); no content or token is in an event, `repr`, log, stdout or file. The inner adapter is in a closure.
6. The gated wrapper's public surface is `READ_METHODS[id]` plus the one door; `sent` is the actions executed, no content.
