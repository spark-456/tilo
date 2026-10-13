# First-run sample eligibility (HR-1, FR-UX-13)

Import `useFirstRun` from `park/sample/useFirstRun` inside `ParkProvider`.
It returns a shared boolean: true for a demo session, or after the existing
worlds route confirms that the person has no non-sample world. Loading and
failed reads return false. All consumers share one initial read.

An accepted real start or a later worlds read containing personal work turns
the boolean off on the next render. An empty or stale response cannot restore
it in that provider. A new provider has independent state; nothing is stored,
written, charged, sent to a model, or shared across people.

This hook does not substitute fixtures into API results. Pages must label
sample panels, keep sample actions read-only, and use real Connectors/Profile
state. Those page changes and tour prompts consume this seam separately.

The shell banner can be dismissed for each person and page on this device.
An empty, successfully read live notification list gets labelled sample rows
until the first real start. Clicking those rows only explains sample mode:
it never opens a world, approves a decision or sends anything to the API.
Actual notifications continue to use their existing actions and unread count.
Tour prompts and the per-page sample panels are separate follow-up slices.
