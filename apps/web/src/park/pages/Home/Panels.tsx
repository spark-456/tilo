// The Home page's panels in the Studio layout (UI-STUDIO-2, design/studio-v2 "Tilo S Home", canvas section 02): the
// greeting with its decorative crew, Your worlds as cards, Chat history, and the side column (Needs you, Up next
// today, Just finished, spend and the spend tiles). Presentation only: HomePage.tsx owns the data, the composer state
// and every navigation call.
import type { MouseEvent, ReactNode } from "react";
import type { Dec, Decision, Ledger, World } from "../../api/types";
import { kpis } from "../../app/ledgerKpis";
import { KpiTile } from "../../components";
import { SampleBadge, SampleNote } from "../../sample/SampleBadge";
import { Buddy } from "../../studio/Buddy";
import { type LiveRow, type NextEvent, type Spend, decisionsWaiting } from "./homeData";
import { icon, needsAgent, worldArt } from "./homeKit";

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
    <div className="park-home-hero">
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

/** The greeting's little crew: decoration only (still, no speech, no claim about any run). */
export function Crew() {
  return (
    <div className="park-home-crew" aria-hidden="true">
      <span className="park-home-crew__floor" />
      <Buddy kind="research" mood="done" size={74} />
      <Buddy kind="director" size={100} />
      <Buddy kind="designer" size={70} />
      <Buddy kind="finance" mood="reading" size={62} />
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

const PILL: Record<"needs" | "run" | "new", string> = {
  needs: "Needs you",
  run: "Working",
  new: "Starting",
};
const RING = 2 * Math.PI * 19;

export interface WorldsProps {
  /** True only when the cards come from the served worlds: sample cards are titled as a sample (HR-1). */
  readonly served: boolean;
  readonly rows: readonly LiveRow[];
  /** STARTER-1: the recorded sample project, when the Api served it and the person has not hidden it. */
  readonly sample?: World | undefined;
  readonly night: boolean;
  readonly onWorld: (id: string) => void;
  readonly onWorlds: () => void;
}

/** Your worlds: the worlds that run or need you, as cards (three at most; All worlds has the rest). */
export function WorldsSection({ served, rows, sample, night, onWorld, onWorlds }: WorldsProps) {
  const title = served ? "Your worlds" : "Sample worlds";
  return (
    <section aria-label={title} className="park-home-section">
      <div className="park-home-section__head">
        <h2 className="park-home-h2">{title}</h2>
        <GoLink href="/worlds" onGo={onWorlds}>
          All worlds
        </GoLink>
      </div>
      {rows.length === 0 && !sample ? (
        <p className="park-home-none">
          Nothing is running. Describe a bigger job above and Tilo builds a world for it.
        </p>
      ) : (
        <div className="park-home-cards">
          {rows.slice(0, 3).map((r) => {
            const state = r.needs ? "needs" : r.world.isNew ? "new" : "run";
            const known = !(served && r.world.prog === undefined) && !r.world.isNew;
            return (
              <button
                key={r.world.id}
                type="button"
                className="park-home-live"
                onClick={() => onWorld(r.world.id)}
              >
                <span className="park-home-live__art">
                  <span className="park-home-live__pic">{worldArt(r.world, night, 84)}</span>
                  <span className={`park-home-pill park-home-pill--${state}`}>
                    <span className="park-home-pill__dot" aria-hidden="true" />
                    {PILL[state]}
                  </span>
                </span>
                <span className="park-home-live__foot">
                  <span className="park-home-live__text">
                    <span className="park-home-live__name">{r.world.short}</span>
                    <span
                      className={`park-home-live__sub${r.needs ? " park-home-live__sub--needs" : ""}`}
                    >
                      {r.sub}
                    </span>
                  </span>
                  {known ? (
                    <span className="park-home-ring" aria-hidden="true">
                      <svg
                        width="48"
                        height="48"
                        viewBox="0 0 48 48"
                        aria-hidden="true"
                        focusable="false"
                      >
                        <circle cx="24" cy="24" r="19" className="park-home-ring__track" />
                        <circle
                          cx="24"
                          cy="24"
                          r="19"
                          className={`park-home-ring__fill park-home-ring__fill--${state}`}
                          strokeDasharray={RING.toFixed(1)}
                          strokeDashoffset={(RING * (1 - r.prog / 100)).toFixed(1)}
                        />
                      </svg>
                      <span className="park-home-ring__pct">{`${r.prog}%`}</span>
                    </span>
                  ) : null}
                </span>
              </button>
            );
          })}
          {sample ? (
            <button
              type="button"
              className="park-home-live park-home-live--sample"
              onClick={() => onWorld(sample.id)}
            >
              <span className="park-home-live__art">
                <span className="park-home-live__pic">{worldArt(sample, night, 84)}</span>
              </span>
              <span className="park-home-live__foot">
                <span className="park-home-live__text">
                  <span className="park-home-live__name">
                    {sample.short}
                    <SampleBadge />
                  </span>
                  <SampleNote className="park-home-live__sub" />
                </span>
              </span>
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

/**
 * Chat history. The server keeps no Quick question or answer (COST-FAST-1), so there is nothing it can list: the
 * section says so plainly and links to the Chat page, never a sample conversation.
 */
export function ChatHistory({ onChat }: { onChat: () => void }) {
  return (
    <section aria-label="Chat history" className="park-home-section">
      <div className="park-home-section__head">
        <div className="park-home-section__title">
          <h2 className="park-home-h2">Chat history</h2>
          <span className="park-home-section__sub">Quick answers from your single helper</span>
        </div>
        <GoLink href="/chat" onGo={onChat}>
          Open chat
        </GoLink>
      </div>
      <div className="park-home-history">
        <span className="park-home-history__face" aria-hidden="true">
          <span className="park-home-history__visor">
            <span />
            <span />
          </span>
        </span>
        <span className="park-home-history__text">
          <span className="park-home-history__title">No saved chats yet</span>
          <span className="park-home-history__line">
            Quick answers are not kept after you leave, so there is nothing to list here. Ask one
            above or on the Chat page.
          </span>
        </span>
      </div>
    </section>
  );
}

export interface TodayProps {
  readonly served: boolean;
  /** The open decisions to list (titles only; Home never approves). */
  readonly open: readonly Decision[];
  /** The served open count, or null when none was served (nothing is claimed). */
  readonly needs: number | null;
  readonly events: readonly NextEvent[];
  readonly finished: World | undefined;
  readonly spend: Spend;
  readonly night: boolean;
  readonly onWorld: (id: string) => void;
  readonly onWorlds: () => void;
  readonly onAgenda: () => void;
  readonly onLedger: () => void;
  /** Under 1180px the side column is a block in the page column, without the agenda. */
  readonly stacked?: boolean;
  readonly children?: ReactNode;
}

export function TodayPanel({
  open,
  needs,
  events,
  finished,
  spend,
  night,
  onWorld,
  onWorlds,
  onAgenda,
  onLedger,
  stacked = false,
  children,
}: TodayProps) {
  const Shell = stacked ? "section" : "aside";
  return (
    <Shell aria-label={stacked ? "Today and spend" : "Today"} className="park-home-today">
      <div className="park-home-card park-home-card--needs">
        <div className="park-home-head">
          <span className="park-home-title">Needs you</span>
          {needs !== null && needs > 0 ? (
            <>
              <span className="park-home-count" aria-hidden="true">
                {needs}
              </span>
              <span className="park-home-sr">{decisionsWaiting(needs)}</span>
            </>
          ) : null}
          <span className="park-home-head__gap" />
          <GoLink href="/worlds" onGo={onWorlds}>
            See all
          </GoLink>
        </div>
        {open.length > 0 ? (
          open.slice(0, 3).map((d) => (
            <button
              key={d.k}
              type="button"
              className="park-home-tray"
              onClick={() => onWorld(d.world)}
            >
              <span className="park-home-tile park-home-tile--needs">{needsAgent(30, night)}</span>
              <span className="park-home-tray__text">
                <span className="park-home-tray__title">{d.title}</span>
                {d.facts?.project ? (
                  <span className="park-home-tray__sub">{d.facts.project}</span>
                ) : null}
              </span>
              <span className="park-home-tray__go" aria-hidden="true">
                ›
              </span>
            </button>
          ))
        ) : (
          <p className="park-home-none">
            {needs === null ? "Nothing to show yet." : "Nothing needs you right now."}
          </p>
        )}
      </div>
      {!stacked && events.length > 0 ? (
        <div className="park-home-card">
          <div className="park-home-head">
            <span className="park-home-title">Up next today</span>
            <span className="park-home-head__gap" />
            <GoLink href="/agenda" onGo={onAgenda}>
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
        </div>
      ) : null}
      {finished ? (
        <div className="park-home-done">
          <span className="park-home-done__face" aria-hidden="true">
            <Buddy kind="connector" mood="done" size={50} />
          </span>
          <span className="park-home-done__text">
            <span className="park-home-done__label">Just finished</span>
            <span className="park-home-done__name">{finished.name}</span>
            <GoLink
              href={`/world/${encodeURIComponent(finished.id)}`}
              onGo={() => onWorld(finished.id)}
            >
              Open result
            </GoLink>
          </span>
        </div>
      ) : null}
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
      {children}
    </Shell>
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
    <section aria-label="Spend at a glance" className="park-home-kpis">
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
