// Shared pieces of the Needs-you sheets (needs-you/CardView, GateSheet). Every figure on them comes from the client or
// the recorded events (HR-1, HR-5). Look after the card, chip and row language of design/source "Tilo Worlds.dc.html"
// and "Tilo Team.dc.html". UX-SMOOTH: the old screens' page, section, stats and event-list parts went with the old
// screens; only what the sheets use is left.
import type { Authz } from "@tilo/contracts";
import type { ReactNode } from "react";
import { Placeholder } from "./Placeholder";

/** "send_email" -> "Send email": machine names never reach the screen as they are. */
export const words = (id: string): string =>
  id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** Brand and channel names as people write them ("Google Drive", "Email"). */
const NAMES: Readonly<Record<string, string>> = {
  gmail: "Gmail",
  google_drive: "Google Drive",
  email: "Email",
};
export const nameOf = (id: string): string => NAMES[id] ?? words(id);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-29T09:30:02.000Z" -> "29 Sep 2026". */
function longDate(ts: string): string {
  const d = new Date(ts);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** "2026-09-29T09:32:09.500Z" -> "29 Sep 2026, 09:32 UTC". */
export const stamp = (ts: string): string => `${longDate(ts)}, ${ts.slice(11, 16)} UTC`;

/** Who authorised an action, in words (PRD 10.4 `authz`): never a colour alone, never an id. */
export const authzText = (a: Authz): string =>
  ({ person: "You", policy: "Your rule", team_lead: "A Team Lead" })[a.by];

/** Controls that do nothing yet, in one compact row (AGW-08): visible, aria-disabled. */
export function Soon({
  labels,
  className = "",
}: { labels: readonly string[]; className?: string }) {
  return (
    <div className={`soon-row ${className}`.trim()}>
      {labels.map((l) => (
        <Placeholder key={l} label={l} compact />
      ))}
    </div>
  );
}

/** A state in words, tinted by tone: the colour never carries the meaning alone. */
export function Chip({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span className="btag" data-tone={tone}>
      {children}
    </span>
  );
}
