// Shared pieces of the AGW-08 group B screens (S-13..S-24). Every figure on those screens comes
// from the client or the recorded events (HR-1, HR-5); what the client does not have is an honest
// empty state. Screens outside a world address show the fixture world, the only one the client
// knows (HR-4: the shell's replay banner says so on every screen). Look after the card, chip and
// row language of design/source "Tilo Worlds.dc.html" and "Tilo Team.dc.html".
import type { Authz, Event } from "@tilo/contracts";
import type { CSSProperties, ReactNode, Ref } from "react";
import { useClient } from "../api/ClientProvider";
import { elapsed, useRunLog } from "../world/runLog";
import { useWorldContext } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { Placeholder } from "./Placeholder";

/** The recorded events of the screen's world as they arrive: the world its address names
 * (`?world=`, world/worldContext.ts), else the fixture world. */
export function useFixtureRun(): { events: readonly Event[]; worldId: string } {
  const worldId = useWorldContext();
  return { events: useRunLog(useClient(), worldId), worldId };
}

/** A payload field the event registry types per event type. */
export const field = (e: Event, key: string): unknown => (e.data as Record<string, unknown>)[key];

/** "send_email" -> "Send email": machine names never reach the screen as they are. */
export const words = (id: string): string =>
  id.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** Real plurals: "1 level", "2 levels". */
export const plural = (n: number, one: string, many = `${one}s`): string =>
  `${n} ${n === 1 ? one : many}`;

/** Brand and channel names as people write them ("WhatsApp", "Google Drive"). */
const NAMES: Readonly<Record<string, string>> = {
  gmail: "Gmail",
  google_drive: "Google Drive",
  whatsapp: "WhatsApp",
  email: "Email",
};
export const nameOf = (id: string): string => NAMES[id] ?? words(id);

/** "2026-09-29T09:30:02.000Z" -> "29 Sep 2026". */
export function longDate(ts: string): string {
  const d = new Date(ts);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-09-29T09:32:09.500Z" -> "29 Sep 2026, 09:32 UTC". */
export const stamp = (ts: string): string => `${longDate(ts)}, ${ts.slice(11, 16)} UTC`;

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

/** Controls that do nothing yet, in one compact row (AGW-08): visible, aria-disabled. Put it
 * where the real controls will sit: a section's `action`, a filter bar, or the end of a section. */
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

/** A static empty isometric tile, in neutral role tokens: a drawing, not a render of any world. */
function EmptyGlyph() {
  return (
    <svg
      className="empty-glyph"
      viewBox="0 0 80 60"
      width="56"
      height="42"
      aria-hidden="true"
      focusable="false"
    >
      <polygon points="40,6 72,22 40,38 8,22" fill="var(--color-surface-2)" />
      <polygon points="8,22 40,38 40,54 8,38" fill="var(--color-fog)" />
      <polygon points="72,22 40,38 40,54 72,38" fill="var(--color-ink-3)" opacity="0.5" />
      <polygon
        points="40,14 58,22 40,30 22,22"
        fill="none"
        stroke="var(--color-brand-primary)"
        strokeWidth="2"
        strokeDasharray="4 3"
      />
    </svg>
  );
}

/** What a screen shows when there is nothing to list yet: an isometric glyph, a title, one line that
 * says what is true and why, and at most one action. It fills the reserved box it sits in, so
 * loading, empty and ready never move what is around them (CLS, UX-1). `compact` drops the card
 * for a short list inside another section. */
export function EmptyState({
  testid,
  title,
  line,
  action,
  compact = false,
}: {
  testid: string;
  title: string;
  line: string;
  action?: { label: string; to: string };
  compact?: boolean;
}) {
  return (
    <div className="empty-state" data-testid={testid} data-compact={compact ? "true" : undefined}>
      <EmptyGlyph />
      <p className="empty-title">{title}</p>
      <p className="empty-line">{line}</p>
      {action && (
        <AppLink className="secondary" to={action.to}>
          {action.label}
        </AppLink>
      )}
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
  action,
  headingRef,
  children,
}: {
  title: string;
  note?: string;
  reserve?: Lines;
  action?: ReactNode;
  /** Makes the heading focusable (tabindex -1) and hands it back, to move focus there. */
  headingRef?: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  const [wide, narrow] = typeof reserve === "number" ? [reserve, reserve] : (reserve ?? []);
  return (
    <section className="screen-section card" aria-label={title}>
      <div className="card-head">
        <h2 ref={headingRef} tabIndex={headingRef ? -1 : undefined}>
          {title}
        </h2>
        {action}
      </div>
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
    <li className="bitem">
      <div className="bitem-main">
        <b>{name}</b>
        {sub && <span className="bitem-sub">{sub}</span>}
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
    <ul className="blist">
      {events.map((e) => (
        <Row key={e.seq} name={e.summary} sub={elapsed(all, e)} state={extra?.(e)} />
      ))}
    </ul>
  );
}
