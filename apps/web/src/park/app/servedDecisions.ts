// The one count of "decisions waiting on a person" for the live path (BQ-UX11-1, FR-UX-11): the decisions the
// Api served that are still open. The sample `needsLeft` counts fixture decisions and is never shown as live
// (HR-1..HR-7, PRD 9.4). Nothing served (not loaded, a failed read, an empty list) is 0, which pages read as "no count".
import type { Dec, Decision } from "../api/types";

export const openServedCount = (served: readonly Decision[], dec: Dec): number =>
  served.filter((d) => !dec[d.k]).length;
