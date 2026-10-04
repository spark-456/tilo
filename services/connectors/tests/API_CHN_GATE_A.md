# CHN-GATE-A: `tilo_connectors.Outbox` read port and revocation (issue #256, gates FR-CHN-11)

Pinned by `test_CHN_GATE_A_FR_CHN_11_outbox_read_port.py`. The channels side (the stop protocol and the sweeper) is in
`services/channels/tests/API_CHN_GATE_A.md`; defaults in BQ-186 to BQ-188 (`docs/open-questions.md`). The builder may
override a name or shape, updating the tests in the same PR. No `contracts/` change: these are Python methods of the
outbox, not schema; a revocation is not an entry.

```python
class Outbox:
    def get(self, outbox_id: str) -> dict | None: ...
    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None: ...
    def revoke(self, world_id: str, idempotency_key: str) -> dict | None: ...
```

- **Reads** return a copy of the stored entry, or None. They never write and never call `tilo_policy.check_entry`.
  A world-scoped outbox (`Outbox(world_id=w)`) returns None for another world's entry, as for an unknown one.
- **`revoke`** never creates an entry. With an entry stored under the key, a `scheduled` one becomes `cancelled`
  (atomically, like `cancel`) and the entry is returned in whatever state it is in (`sent` stays `sent`). With nothing
  stored, the key is recorded as revoked and None is returned; from then on `enqueue` of that
  `(world_id, idempotency_key)`, on any instance over the same store, raises `OutboxRefused` and stores nothing.
  Idempotent. Atomic against a concurrent `enqueue` of the same key: either the enqueue stored first and the
  revocation cancels it, or the revocation came first and the enqueue is refused. A world-scoped outbox refuses
  (`OutboxRefused`) or ignores another world's key: it never changes that world's entry or blocks its key.
- **Never pruned** (issue #256 assumption): stored keys and revocations answer the same way however old they are.
