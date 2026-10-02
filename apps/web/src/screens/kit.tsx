// Shared pieces of the AGW-08 group B screens (S-13..S-24). Every figure on those screens comes
// from the client or the recorded events (HR-1, HR-5); what the client does not have is an honest
// empty state. Screens outside a world address show the fixture world, the only one the client
// knows (HR-4: the shell's replay banner says so on every screen). Look after the card, chip and
// row language of design/source "Tilo Worlds.dc.html" and "Tilo Team.dc.html".
import type { Authz, Event } from "@tilo/contracts";
import type { CSSProperties, ReactNode } from "react";
import { useClient } from "../api/ClientProvider";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";
import { elapsed, useRunLog } from "../world/runLog";
import { Placeholder } from "./Placeholder";

/** The recorded events of the fixture world, as they arrive. */
export function useFixtureRun(): { events: readonly Event[]; worldId: string } {
  return { events: useRunLog(useClient(), FIXTURE_WORLD_ID), worldId: FIXTURE_WORLD_ID };
}

/** A payload field the event registry types per event type. */
export const field = (e: Event, key: string): unknown => (e.data as Record<string, unknown>)[key];

/** "send_email" -> "Send email": machine names never reach the screen as they are. */
export const words = (id: string): string =>
  id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** "2026-09-29T09:30:02.000Z" -> "29 Sep 2026". */
export function longDate(ts: string): string {
  const d = new Date(ts);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Who authorised an action, in words (PRD 10.4 `authz`): never a colour alone, never an id. */
export const authzText = (a: Authz): string =>
  ({ person: "You", policy: "Your rule", team_lead: "A Team Lead" })[a.by];

/** Title, one plain sentence and, optionally, the screen's one primary action (UX-1). */
export function Page({
  testid,
  title,
  sub,
  action,
  children,
}: { testid: string; title: string; sub: string; action?: ReactNode; children: ReactNode }) {
  return (
    <div className="screen-body wide page" data-testid={testid}>
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          <p className="page-sub">{sub}</p>
        </div>
        {action}
      </header>
      {children}
    </div>
  );
}

/** Every control that does nothing yet, in one compact row (AGW-08): visible, aria-disabled. */
export function Soon({ labels }: { labels: readonly string[] }) {
  return (
    <div className="soon-row">
      <Chip tone="soon">Coming soon</Chip>
      {labels.map((l) => (
        <Placeholder key={l} label={l} compact />
      ))}
    </div>
  );
}

/** A state in words, tinted by tone: the colour never carries the meaning alone. */
export function Chip({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span className="chip" data-tone={tone}>
      {children}
    </span>
  );
}

/** Key figures as labelled hero numbers. */
export function Stats({ items }: { items: ReadonlyArray<readonly [string, string | number]> }) {
  return (
    <ul className="stat-tiles hero-stats">
      {items.map(([label, value]) => (
        <li key={label}>
          <span className="stat-name">{label}</span>
          <b>{value}</b>
        </li>
      ))}
    </ul>
  );
}

/** Lines of body height: one number, or [wide screens, narrow screens]. */
export type Lines = number | readonly [number, number];

/** A card with a title. With `reserve` (a height in lines) the body has that fixed height and
 * scrolls, so data arriving inside it, however long, moves nothing around it (CLS, UX-1). */
export function Section({
  title,
  note,
  reserve,
  children,
}: { title: string; note?: string; reserve?: Lines; children: ReactNode }) {
  const [wide, narrow] = typeof reserve === "number" ? [reserve, reserve] : (reserve ?? []);
  return (
    <section className="screen-section card" aria-label={title}>
      <h2>{title}</h2>
      {note && <p className="section-note">{note}</p>}
      {wide ? (
        <section
          className="section-box reserved"
          aria-label={`${title} list`}
          // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard reachable (WCAG 2.1.1).
          tabIndex={0}
          style={
            {
              "--lines": wide,
              "--lines-narrow": narrow ?? wide,
            } as CSSProperties
          }
        >
          {children}
        </section>
      ) : (
        <div className="section-box">{children}</div>
      )}
    </section>
  );
}

/** One row of a list: a name with a muted line under it, an optional state and a trailing control. */
export function Row({
  name,
  sub,
  state,
  children,
}: { name: ReactNode; sub?: ReactNode; state?: ReactNode; children?: ReactNode }) {
  return (
    <li className="row">
      <div className="row-main">
        <b>{name}</b>
        {sub && <span className="row-sub">{sub}</span>}
      </div>
      {state}
      {children}
    </li>
  );
}

/** One row per recorded event with its recorded time; `empty` says what has not happened. */
export function EventList({
  events,
  all,
  empty,
  extra,
}: {
  events: readonly Event[];
  all: readonly Event[];
  empty: string;
  extra?: (e: Event) => ReactNode;
}) {
  if (events.length === 0) return <p className="empty-note">{empty}</p>;
  return (
    <ul className="rows">
      {events.map((e) => (
        <Row key={e.seq} name={e.summary} sub={elapsed(all, e)} state={extra?.(e)} />
      ))}
    </ul>
  );
}
