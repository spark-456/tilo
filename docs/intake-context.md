# Screened uploads in task intake (I3, FR-INT-02)

Thinking-mode `/intake` extracts and screens attached files before asking the
Director for the brief. Clean converted Office/CSV text is delimited as source
data; clean PDF, PNG and JPEG files use the provider layer's native media parts.
The Director can use that content when drafting the goal, deliverables and
questions. Code adds the accepted artifact references to the brief afterwards.

Attached-file durable intake binds both stores before the Director. The artifact
store owns one file screen: native bytes, CSV stored text, or extracted Office text
through the same safety text path. Intake reuses that stored verdict and version;
Office bytes are not sent to an unsupported native-media screen. Flagged,
unscreened or unreadable content never reaches the
Director. Native inputs use the provider layer's existing per-file, total-byte
and measured PDF-page caps; the router enforces capability and input-token caps.
Converted text shares the existing extraction character cap across the request;
files past that cap receive a failed status rather than being silently truncated.
A failed Director call removes prepared upload versions and creates no task;
append-only attempt metadata remains. Quick mode still offers Thinking
for files and creates no task.

This slice does not create KnowledgeItems, new lifecycle events, persistent
knowledge, deletion controls or memory citations. Deployed upload artifacts use
the scoped run-artifact/archive bridge described in `intake-storage.md`; local
dev and demo uploads remain in memory.
Deploy and native live pricing must be verified by CX-MERGE before claiming that
people can use these inputs on the deployed site.
