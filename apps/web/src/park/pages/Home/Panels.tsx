// The Home page's panels, as the reference draws them (design_handoff_tilo_web_app/design/
// Tilo App Home.dc.html): map pins, the greeting panel, the Today panel and the composer's panels.
// Presentation only: HomePage.tsx owns the data, the composer state and every navigation call.
import type { MouseEvent, ReactNode } from "react";
import type { Dec, Decision, Ledger } from "../../api/types";
import { kpis } from "../../app/ledgerKpis";
import { KpiTile } from "../../components";
import {
  type LiveRow,
  type NextEvent,
  type PlacedPin,
  type Spend,
  decisionsWaiting,
} from "./homeData";
import { icon, needsAgent, worldArt } from "./homeKit";

export function Pins({
  pins,
  onOpen,
}: { pins: readonly PlacedPin[]; onOpen: (id: string) => void }) {
  return (
    <>
      {pins.map((p) => (
        <div
          key={p.worldId}
          className="park-home-pin"
          style={{ left: `${p.x}px`, top: `${p.y}px` }}
        >
          <button type="button" className="park-home-pin__card" onClick={() => onOpen(p.worldId)}>
            <span className={`park-home-pin__icon park-home-pin__icon--${p.tone}`}>
              {icon(p.icon, 16)}
            </span>
            <span className="park-home-pin__text">
              <span className="park-home-pin__name">{p.world.short}</span>
              <span className="park-home-pin__sub">{p.sub}</span>
            </span>
          </button>
          <div className="park-home-pin__stem" />
          <div className="park-home-pin__dot" />
        </div>
      ))}
    </>
  );
}

export interface HeroProps {
  readonly dateLine: string;
  readonly greeting: string;
  readonly summary: string;
  readonly needs: number;
  /** False on the live path when no decisions were served: nothing is claimed either way. */
  readonly needsKnown?: boolean;
  readonly night: boolean;
  /** The world the waiting decisions are in, from the Api's worlds; null names none. */
  readonly worldName: string | null;
  readonly onReview: () => void;
}

export function Hero({
  dateLine,
  greeting,
  summary,
  needs,
  needsKnown = true,
  night,
  worldName,
  onReview,
}: HeroProps) {
  return (
    <div className="park-home-hero park-home-glass">
      <div className="park-home-date">{dateLine}</div>
      <h1 className="park-home-h1">{greeting}</h1>
      {summary ? <p className="park-home-summary">{summary}</p> : null}
      {needs > 0 ? (
        <button type="button" className="park-home-needs" onClick={onReview}>
          <span className="park-home-needs__tile">{needsAgent(30, night)}</span>
          <span>
            <span className="park-home-needs__bold">{decisionsWaiting(needs)}</span>
            {worldName ? ` in ${worldName}` : ""}
          </span>
          <span className="park-home-needs__review">Review</span>
        </button>
      ) : needsKnown ? (
        <div className="park-home-caught">
          <span className="park-home-caught__disc">{icon("check", 14)}</span>
          You’re all caught up
        </div>
      ) : null}
    </div>
  );
}

/** A link of the reference: a real address (so it can be read and copied), but a click goes through app.go. */
function GoLink({ href, onGo, children }: { href: string; onGo: () => void; children: ReactNode }) {
  const click = (e: MouseEvent<HTMLAnchorElement>) => {
    // Only a plain left click is ours; a modified or non-primary click is the browser's (new tab, window).
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    onGo();
  };
  return (
    <a className="park-home-link" href={href} onClick={click}>
      {children}
    </a>
  );
}

export interface TodayProps {
  readonly rows: readonly LiveRow[];
  readonly events: readonly NextEvent[];
  readonly spend: Spend;
  readonly night: boolean;
  readonly onWorld: (id: string) => void;
  readonly onWorlds: () => void;
  readonly onAgenda: () => void;
  readonly onLedger: () => void;
}

export function TodayPanel({
  rows,
  events,
  spend,
  night,
  onWorld,
  onWorlds,
  onAgenda,
  onLedger,
}: TodayProps) {
  return (
    <aside aria-label="Today" className="park-home-today park-home-glass">
      <div className="park-home-head">
        <span className="park-home-title">Live now</span>
        <GoLink href="#worlds" onGo={onWorlds}>
          All worlds
        </GoLink>
      </div>
      {rows.map((r) => (
        <button
          key={r.world.id}
          type="button"
          className="park-home-live"
          onClick={() => onWorld(r.world.id)}
        >
          <span className={`park-home-tile park-home-tile--${r.needs ? "needs" : "run"}`}>
            {worldArt(r.world, night)}
          </span>
          <span className="park-home-live__text">
            <span className="park-home-live__name">{r.world.short}</span>
            <span className={`park-home-live__sub${r.needs ? " park-home-live__sub--needs" : ""}`}>
              {r.sub}
            </span>
          </span>
          <span className="park-home-track">
            <span
              className={`park-home-bar park-home-bar--${r.needs ? "needs" : "run"}`}
              style={{ width: `${r.prog}%` }}
            />
          </span>
        </button>
      ))}
      <div className="park-home-rule" />
      <div className="park-home-head park-home-head--next">
        <span className="park-home-title">Up next today</span>
        <GoLink href="#agenda" onGo={onAgenda}>
          Agenda
        </GoLink>
      </div>
      {events.map((e) => (
        <button key={e.id} type="button" className="park-home-event" onClick={onAgenda}>
          <span className="park-home-event__time">{e.time}</span>
          <span className={`park-home-event__body park-home-event__body--${e.tone}`}>
            <span className="park-home-event__title">{e.title}</span>
            <span className="park-home-event__sub">{e.sub}</span>
          </span>
        </button>
      ))}
      <div className="park-home-rule" />
      <button type="button" className="park-home-spend" onClick={onLedger}>
        <span className="park-home-spend__head">
          <span className="park-home-title">
            {spend.month ? `${spend.month} spend` : "Spend so far"}
          </span>
          <span className="park-home-spend__link">Ledger</span>
        </span>
        <span className="park-home-spend__figures">
          <span className="park-home-spend__amount">{spend.spent}</span>
          <span className="park-home-spend__of">{spend.of}</span>
        </span>
        <span className="park-home-spend__bar">
          <span className="park-home-spend__spent" style={{ width: `${spend.spentPct}%` }} />
          <span className="park-home-spend__waiting" style={{ width: `${spend.waitingPct}%` }} />
        </span>
        <span className="park-home-spend__note">{spend.forecast}</span>
      </button>
    </aside>
  );
}

/**
 * The five spend tiles of the Ledger (FR-SPD-01), the same `kpis()` and `KpiTile`, read from the ledger this
 * page loaded. "Waiting on you" is the one control: it opens the world its decision is in, or else the world
 * that needs you.
 */
export function KpiStrip({
  ledger,
  dec,
  decisions,
  fallbackWorld,
  onWorld,
}: {
  ledger: Ledger;
  dec: Dec;
  decisions: readonly Decision[];
  fallbackWorld: string | undefined;
  onWorld: (id: string) => void;
}) {
  return (
    <section aria-label="Spend at a glance" className="park-home-kpis park-home-glass">
      {kpis(ledger, dec, decisions).map((k) => {
        const world = k.tone === "amber" ? (k.opensWorld ?? fallbackWorld) : undefined;
        return (
          <KpiTile
            key={k.label}
            label={k.label}
            value={k.value}
            {...(k.sub ? { sub: k.sub } : {})}
            {...(k.tone ? { tone: k.tone } : {})}
            {...(world ? { onClick: () => onWorld(world) } : {})}
          />
        );
      })}
    </section>
  );
}
