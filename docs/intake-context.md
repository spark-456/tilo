# Screened uploads in task intake (I3, FR-INT-02)

Thinking-mode `/intake` extracts and screens attached files before asking the
Director for the brief. Clean converted Office/CSV text is delimited as source
data; clean PDF, PNG and JPEG files use the provider layer's native media parts.
The Director can use that content when drafting the goal, deliverables and
questions. Code adds the accepted artifact references to the brief afterwards.

Files are screened once. Flagged or unreadable content never reaches the
Director. Native inputs use the provider layer's existing per-file, total-byte
and measured PDF-page caps; the router enforces capability and input-token caps.
Converted text shares the existing extraction character cap across the request;
files past that cap receive a failed status rather than being silently truncated.
A failed Director call stores no uploads or task. Quick mode still offers Thinking
for files and creates no task.

This slice does not create KnowledgeItems, new lifecycle events, persistent
knowledge, deletion controls or memory citations. Upload artifacts still use the
planning store; the scoped run-artifact/archive bridge is the separate I2 slice.
Deploy and native live pricing must be verified by CX-MERGE before claiming that
people can use these inputs on the deployed site.
