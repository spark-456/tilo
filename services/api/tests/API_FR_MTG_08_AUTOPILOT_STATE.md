# FR-MTG-08 durable scoped Autopilot state

`followup_autopilot_state.FirestoreCards` and `FirestoreStops` adapt the existing API Firestore client to the existing channels protocols. They do not open a client or register a route. The future factory must resolve `store_door`, require the existing durable outbox configuration, and bind current stored org/owner/world/run before constructing these adapters.

Each scope is SHA-256(JSON([owner, world, run])) under `orgs/{org}/followup_autopilot/{scope}`. Its `cards` and `stops` subcollections use hashed namespace/key identities. JSON preserves nested payloads. SDK create is atomic first-writer-wins; card updates require an existing document. The `#artifacts` index remains scope-bound and only accepts the bound owner. Pending stops are listed only in this scope.

Activation remains blocked on the scoped policy/outbox factory, M1/M2 fresh source and publication CAS, M3 default-off owner routes, M4 indexed retention/erasure integration, M5 whole-chain acceptance, and whole-chain security review. These adapters do not implement source tombstones, automatic cleanup, or card-answer delivery. Do not activate them independently or claim that update preconditions prevent a later create after source erasure. No provider call, send, or new environment variable is introduced.

Offline tests use a fake SDK. Emulator acceptance and production retention/erasure remain required before activation. An adapter IO failure is a fixed no-store 503; only AlreadyExists is interpreted as a lost create race.
