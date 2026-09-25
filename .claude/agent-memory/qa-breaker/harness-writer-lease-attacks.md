---
name: harness-writer-lease-attacks
description: P0-09 WorldWriter lease keyed only on writer_id; same id = two live writers overwrite Firestore events. Attacks that found it.
metadata:
  type: project
---

P0-09 round 1 (2026-09-25): WorldWriter.open() lets a second writer with the SAME writer_id take a live lease, and the CLI derives writer_id from --run (`skeleton_{run_id}`) while `just harness-skeleton` hard-codes --run. Two concurrent recipe runs both exit 0; FirestoreStore.transact uses transaction.set on events/{seq:08d}, so events are overwritten silently (MemoryStore appends duplicates instead). _commit also never compares head.last_seq to event seq-1.

P0-09 round 2: lease fixed (per-instance token, create(), head.last_seq guard); kill/takeover, twice, concurrent CLI all clean on emulator. New finding: validator accepts credits NaN/Infinity (jsonschema minimum passes NaN), written to Firestore + views; 10**30 raises raw ValueError not EventRejected. Also: _commit never checks lease expiry (expired writer keeps writing, no renewal); rejection problems echo the full 2 MB value. Scratch: mem_attacks.py, emu_attacks.py.

P0-09 round 3: NaN/huge/path-id fixed; 199 tests green. Still: _commit (writer.py:211) checks lease token only, never expires_at, and nothing renews the lease -> writer writes 1h after expiry; healthy CLI with --lease-s 2 --step-delay 1 is taken over mid-run and dies WriterBusy. Also: hard-killing the CLI when it started its own emulator orphans the java emulator (taskkill /T never runs); each leak holds a websocket port (9150, 9151, ...). Emulator stop mid-run -> CLI exits 1 after ~60 s with "transaction has no transaction ID" ValueError. Scratch: p009_r3.py (steal, emustop), orphan_kill.py.

P0-09 round 4: expiry/renewal, orphan kill, steal, twice all clean. New: append() with seq 2.0 (integer-valued float) passes jsonschema "integer" and EV-10 (2.0 == 1+1): MemoryStore stores seq 2.0, FirestoreStore raises raw ValueError from f"{seq:08d}" (store.py:143) instead of EventRejected. Also EventRejected lives in writer.py, not tilo_harness.validator as the brief's API says. CLI --lease-s 2 --step-delay 1 dies alone (ADK cold start ~4 s after first commit). Scratch: p009_r4.py, p009_r4_replay.py, p009_r4_float.py.

P0-09 round 5: float seq fixed; kill/takeover, twice, float all clean; 207 green (first full run had 7 transient emulator-fixture errors, gone on rerun). New: a lone surrogate (json.loads('"\ud800"')) in summary passes EventValidator (problems == []), MemoryStore writes it, FirestoreStore raises raw UnicodeEncodeError (atomic, nothing written). Also run_skeleton returns store.read_events (whole world), so the CLI prints written 16 / 9 on a reused emulator or after a takeover, not the 8 events this run wrote. Scratch: p009_r5.py, p009_r5_cli.py.

P0-09 round 7 (after b97947a _segment fix): surrogate keys at every depth, NaN/inf/2**70 + bad key, escaped-text keys, 5000-char keys, tuple/set/bytes keys all reject printably, nothing stored; 220 green. New: an int over 4300 digits (credits=10**5000) makes _finiteness_problems' `{value!r}` (validator.py:90) raise ValueError, so append raises raw ValueError, not EventRejected. Pattern: every message formatter must be total -- check repr of huge ints, not only str keys. Scratch: attack_d11.py.

P0-09 round 8 (6ceabf7 bit_length fix): all 22 attack_d11 cases clean; 223 green. Still raw exceptions, not EventRejected (Python callers only; JSON-parsed depth up to 990 is fine): int key 10**5000 (_segment str(key), validator.py:69), tuple/frozenset holding 10**5000 (jsonschema message repr, :265), depth-3000 nesting or cyclic dict (RecursionError in walkers), object with raising __str__, complex/Decimal NaN. Root cause: no type gate for non-JSON types and no catch-all in problems(). Scratch: attack_d11b.py.

P0-09 round 9 (36ee509 _json_tree_problems + fail-closed problems()): d11/d11b all EventRejected; 71 valid fixtures pass; 239 green. New: MemoryStore.transact appends the caller's event object (append does only a shallow dict()), so mutating ev["data"] after a successful append/emit puts a lone surrogate into the stored stream -- validate-then-alias TOCTOU. Also emit(type=[...]) raises TypeError at registry_types.get(type) before validation. Scratch: attack_d11c.py.

P0-09 round 10 (6cdbca1 deep-copy + str-type guard): all d11/d11b/d11c clean, returned/read/view copies isolated, 241 green -> PASS for D-11 scope.

**Why:** single-writer and "never overwrite" are D-11 invariants; tests only use distinct writer ids.
**How to apply:** on any harness/writer re-review, first retry: two writers same writer_id; two concurrent CLI runs same --run; check transaction uses create() or a head.last_seq guard. Scratch repro scripts: same_writer.py, twice.py (spawn via running_emulator). Also note run_id must match ^r_... (schema).
