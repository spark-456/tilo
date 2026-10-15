// UI-STUDIO-5 (design/studio-v2 "Tilo S Team"): the side card "Who can say yes" and the "Your helpers" cards on the
// live Team page. Both say only what is true for every team: the rules that always ask a person (the policy engine's
// must-ask switches) and the helper roles Tilo works with. No counts, names or backups are shown that the server
// does not send; what is missing says "Not available yet".
import type { ReactNode } from "react";
import { helperArt } from "./teamKit";

const HELPERS: readonly (readonly [
  string,
  string,
  { role?: string; rank?: string; expr: string },
  string,
])[] = [
  [
    "Director",
    "Plans the work and keeps it on track",
    { rank: "director", expr: "focused" },
    "hero",
  ],
  ["Researcher", "Finds and checks facts", { role: "research", expr: "delighted" }, "blue"],
  ["Writer", "Drafts replies, notes and reports", { role: "designer", expr: "talking" }, "lilac"],
  ["Planner", "Routes, schedules and timelines", { role: "builder", expr: "focused" }, "amber"],
  ["Money keeper", "Prices, invoices and budgets", { role: "finance", expr: "neutral" }, "green"],
  [
    "Messenger",
    "Talks to your apps, within your rules",
    { role: "connector", expr: "delighted" },
    "pink",
  ],
];

const ALWAYS_ASK: readonly (readonly [string, string])[] = [
  ["Spending money", "Always waits for a person’s yes"],
  ["Sharing outside the team", "Always waits for a person’s yes"],
  ["Anything that can’t be undone", "Always waits for a person’s yes"],
];

function SideCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="park-team-side" aria-label={label}>
      {children}
    </section>
  );
}

export function WhoCanSayYes() {
  return (
    <aside className="park-team-aside">
      <SideCard label="Who can say yes">
        <h2 className="park-team-sidetitle">Who can say yes</h2>
        <p className="park-team-sideline">
          These always wait for a person, whoever started the work. An Owner sets each person’s
          spend limit in Manage team settings.
        </p>
        <ul className="park-team-alwayslist">
          {ALWAYS_ASK.map(([what, sub]) => (
            <li key={what} className="park-team-always">
              <span className="park-team-alwaystitle">{what}</span>
              <span className="park-team-alwayssub">{sub}</span>
            </li>
          ))}
        </ul>
        <p className="park-team-sidenote">Backups for when someone is away: not available yet.</p>
      </SideCard>
      <SideCard label="Who helped Tilo learn">
        <h2 className="park-team-sidetitle park-team-sidetitle--sm">Who helped Tilo learn</h2>
        <p className="park-team-sideline">Not available yet.</p>
      </SideCard>
    </aside>
  );
}

export function Helpers({ night }: { night: boolean }) {
  return (
    <section className="park-team-helpers" aria-label="Your helpers">
      <div className="park-team-helpershead">
        <h2 className="park-team-helperstitle">Your helpers</h2>
        <span className="park-team-helpersnote">Tilo picks the right ones for each world</span>
      </div>
      <ul className="park-team-helpergrid">
        {HELPERS.map(([name, what, art, tone]) => (
          <li key={name} className="park-team-helper">
            <span
              className="park-team-helperart"
              style={{ background: `var(--${tone}Soft, var(--sunk))` }}
              aria-hidden="true"
            >
              {helperArt(art, night)}
            </span>
            <span className="park-team-helpertext">
              <span className="park-team-helpername">{name}</span>
              <span className="park-team-helperwhat">{what}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
