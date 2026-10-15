// The town summary, the card grid, its still loading state and the dashed empty box of the Worlds page
// (STUDIO-3, "Tilo S Worlds.dc.html"). The town's counts are the list's own; its picture is the shell's city,
// drawn still (no motion on this page).
import type { ReactNode } from "react";
import { backdropScene } from "../../shell/scene";
import { type TownCounts, plural } from "./model";

/** A still placeholder in the card's own size; no invented world data or motion. */
export function CardSkeleton() {
  return (
    <div aria-hidden="true" className="park-worlds-card park-worlds-skeleton">
      <span className="park-worlds-skeleton__art" />
      <span className="park-worlds-skeleton__line" />
      <span className="park-worlds-skeleton__line" />
    </div>
  );
}

export function LoadingWorlds() {
  return (
    // biome-ignore lint/a11y/useSemanticElements: loading status contains a block card grid, not a form output
    <div role="status" aria-label="Loading worlds" className="park-worlds-section">
      <span className="park-worlds-section__title">Loading worlds…</span>
      <div aria-hidden="true" className="park-worlds-grid">
        {[0, 1, 2].map((n) => (
          <CardSkeleton key={n} />
        ))}
      </div>
    </div>
  );
}

export function Section({ count, children }: { count: number; children: ReactNode }) {
  return (
    <section aria-label="Your worlds" className="park-worlds-section">
      <h2 className="park-worlds-sr">{`Your worlds, ${plural(count, "world", "worlds")} shown`}</h2>
      <div className="park-worlds-grid">{children}</div>
    </section>
  );
}

const LEGEND: ReadonlyArray<readonly [keyof TownCounts, string, string]> = [
  ["working", "Working", "run"],
  ["needs", "Needs you", "needs"],
  ["scheduled", "Scheduled", "sch"],
  ["done", "Done", "ok"],
];

/** "Your town": every world and the helpers still at work, by state; `spent` is the ledger's total when it was read. */
export function TownHero({
  counts,
  night,
  spent,
}: { counts: TownCounts; night: boolean; spent: string | null }) {
  const title =
    counts.worlds === 0
      ? "No worlds yet"
      : `${plural(counts.worlds, "world", "worlds")}, ${plural(counts.helpers, "helper", "helpers")} out and about`;
  return (
    <section aria-label="Your town" className="park-worlds-town">
      <div className="park-worlds-town__art" aria-hidden="true">
        <div className="park-worlds-town__scene">
          {backdropScene(night ? "night" : "day", "still").el}
        </div>
      </div>
      <div className="park-worlds-town__card">
        <span className="park-worlds-town__eyebrow">YOUR TOWN</span>
        <span className="park-worlds-town__title">{title}</span>
        <span className="park-worlds-town__spacer" />
        {spent ? <span className="park-worlds-town__spent">{`${spent} spent so far`}</span> : null}
        <ul className="park-worlds-town__legend">
          {LEGEND.map(([key, label, tone]) => (
            <li key={key} className="park-worlds-town__row">
              <span className={`park-worlds-dot park-worlds-dot--${tone}`} />
              <span className="park-worlds-town__label">{label}</span>
              <span className="park-worlds-town__n">{counts[key]}</span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

export function EmptyBox({ title, body }: { title: string; body?: string }) {
  return (
    <div className="park-worlds-empty">
      <div className="park-worlds-empty__title">{title}</div>
      {body ? <div className="park-worlds-empty__body">{body}</div> : null}
    </div>
  );
}
