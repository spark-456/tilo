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
Agenda, Skills, Ledger and Team now have read-only previews for empty HTTP
accounts, using the existing fixtures with a Sample tag on every panel.
Team people are explicitly fictional. No preview data is substituted into API
results, personal counters or writes. Loading/failed worlds reads and accounts
with personal worlds keep the normal page. Real starts remove every preview
on the next render; the existing demo-session UI stays as it was.
Home adds labelled Needs you, Live now, Up next and Spend examples alongside
the real summary and composer. Worlds adds read-only City, Town and Village
examples without adding them to personal totals, filters or API results.
The existing recorded sample project and Hide/Show controls remain available.
Tour prompts are a separate slice.
