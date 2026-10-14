# Tilo architecture

This is a repository design summary for the 17 October 2026 submission, based on
the [ADRs](adr/). A service or adapter listed here is not evidence of its deployment,
activation or a successful live call. The README records the limited hosted check.

## Services and storage

Firebase Hosting serves the React web client; Firebase Authentication supplies the
signed-in principal. The client submits work to the Cloud Run API. The API handles
intake, tasks, confirmation cards, approvals and scoped reads. The harness plans
and executes agent work and writes ordered events for World, Story and Trace.

| Repository service | Responsibility |
| --- | --- |
| `services/api` | Authenticated work and approval boundary; durable task/world state |
| `services/harness` | Planning, agent execution, handoffs and event writing |
| `services/connectors` | OAuth/token broker, Google adapters and MCP client boundary |
| `services/channels` | Notification and channel presentation paths |
| `services/browser` | Isolated browsing and controlled fetches |
| `services/render` | File rendering from deliverable specifications |
| `services/sandbox-web` | Fictional sites for offline scenarios |
| `meet-bot` | Separate meeting bot project |

[ADR-0026](adr/0026-api-durable-store-on-firestore.md) describes Firestore-backed
API records and event persistence. [ADR-0018](adr/0018-artifact-output-and-store.md)
describes artifact bytes, versions, hashes and provenance, using Cloud Storage and
Firestore metadata. Missing content must remain missing in the presentation.

## Providers and external actions

Business code requests a role through `packages/providers`; configuration selects
the model/provider profile. Offline runs use fakes or recordings. A configured
live provider requires separate owner activation and observed call evidence.

[ADR-0035](adr/0035-live-connectors-oauth-outbox-adapters.md) places real Google
adapters in connectors: the API sends authenticated internal requests rather than
holding provider tokens. The broker protects OAuth grants with KMS. External
side effects use the outbox and deterministic policy engine; T3 requires a person.
An approval alone does not prove delivery, and uncertain outcomes must not be
presented as sent or blindly retried.

[ADR-0031](adr/0031-tilo-mcp-server-on-cloud-run.md) describes assistants calling
Tilo's MCP server. That is separate from Tilo calling an external MCP provider,
including the held [Lovable preparation](connectors/lovable-mcp.md).

## Evidence and honesty

[ADR-0005](adr/0005-event-contract-and-registry.md) defines registered event
payloads and visible effects; unknown events remain Trace-only. World entities
and animation require their recorded events. A card, click or navigation does not
prove a run started; a completion event does not prove an external message sent.

Label live runs, samples and recorded replays explicitly. Preserve sequence numbers,
timestamps, actual artifacts and provider outcomes. Follow [the demo](demo.md) for
the evidence required at each step, and [connector status](connectors/README.md)
for the distinction between preparation, owner prerequisites and activation.
