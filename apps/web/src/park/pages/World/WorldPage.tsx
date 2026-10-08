// The Park "World" page (WEB-6; design "Tilo App World.dc.html"): one world's overview. The title block and
// its buttons, the map with its progress, the decisions it waits on, spend, facts, skills and tools, and then
// Districts (a City), Run history (a Town) or Result (a Village) beside Activity. The worlds, plans,
// decisions, skills and connectors come through useParkApi(); pausing is page state and writes nothing
// (docs/park-designed-not-in-prd/World.md). A decision is taken with app.decide (the store toasts it with
// Undo), navigation inside the Park app is app.go, and the links to the live stage and its lenses are real
// addresses the browser follows, but only for a world whose data came from the live API: a sample world has no
// recorded run, so the same elements are disabled with the reason (docs/park-designed-not-in-prd/World.md).
import { type ReactNode, useEffect, useState } from "react";
import type { Connector, Decision, Plan, Skill, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { useParkApi } from "../../app/context";
import { stagePath } from "../../app/router";
import { useStaged } from "../../app/useStaged";
import { Button, PageSheet } from "../../components";
import { SampleBadge, SampleNote } from "../../sample/SampleBadge";
import { icon } from "../../shell/kit";
import { Activity, Districts, Result, RunHistory } from "./Lower";
import { FactsCard, GoLink, SpendCard, WaitingCard } from "./Side";
import "./World.css";
import { cityArt, rowArt, singleArt } from "./worldArt";
import {
  LEGEND,
  agentsWord,
  decisionsWord,
  heroTagOf,
  skillsAndTools,
  stateLook,
} from "./worldModel";

interface Loaded {
  worlds: World[];
  /** True when the world list came from the live API (`source: "live"`): only then does a world have a stage. */
  live: boolean;
  plans: Record<string, Plan>;
  decisions: Decision[];
  skills: Skill[];
  connectors: Connector[];
}

/** S-05's first building (screens/meta.ts): a Park plan's own building ids are not stage ids. */
const INSPECT_BUILDING = "B1";

const NO_STAGE = "Sample world: there is no recorded run to open";
const NO_STAGE_ID = "park-world-nostage";

/**
 * A link to the stage or one of its lenses. With a stage it is a plain link the browser follows. Without one
 * (a sample world) it is the same element and class, disabled: no href, aria-disabled, and the reason as its
 * title and, once per page, as visually hidden text it is described by.
 */
function StageLink({
  href,
  className,
  children,
}: { href: string | null; className?: string; children: ReactNode }) {
  if (href !== null) {
    return (
      <a className={className} href={href}>
        {children}
      </a>
    );
  }
  return (
    // biome-ignore lint/a11y/useValidAnchor: a disabled link has no destination, so no href
    <a
      className={className}
      // biome-ignore lint/a11y/useSemanticElements: the disabled-link pattern: role="link" + aria-disabled
      role="link"
      aria-disabled="true"
      aria-describedby={NO_STAGE_ID}
      title={NO_STAGE}
    >
      {children}
    </a>
  );
}

/** The world art in the map: a City's plan, a Town's row, or a Village's single building. */
function MapArt({
  w,
  plans,
  app,
}: { w: World; plans: Record<string, Plan>; app: AppCtx }): ReactNode {
  if (w.tier === "City") {
    const plan = w.plan ? plans[w.plan] : undefined;
    return w.plan && plan ? cityArt(plan, w.plan, app.dec, app.night) : null;
  }
  return (
    <div className="park-world-bigart">
      {w.tier === "Town" && w.row ? rowArt(w.row, app.night) : singleArt(w, app.night)}
    </div>
  );
}

function Frame({ children, worldId }: { children?: ReactNode; worldId?: string }) {
  return (
    <div className="park-world-root" data-testid="park-page-world" data-world-id={worldId}>
      <PageSheet>{children}</PageSheet>
    </div>
  );
}

export function WorldPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const [loaded, setLoaded] = useState<Loaded | "failed" | null>(null);
  const [paused, setPaused] = useState<Record<string, boolean>>({});
  // The map and head first, then the side cards, then the lower part: one task each (WEB-MOTION-2).
  const part = useStaged(3);
  const { dec, added } = app;

  useEffect(() => {
    let live = true;
    Promise.all([
      api.getWorlds(dec, added),
      api.getPlans(dec),
      api.getDecisions(),
      api.getSkills(),
      api.getConnectors(),
    ]).then(
      ([worlds, plans, decisions, skills, connectors]) => {
        if (!live) return;
        setLoaded({
          worlds: worlds.data,
          live: worlds.source === "live",
          plans: plans.data,
          decisions: decisions.data,
          skills: skills.data,
          connectors: connectors.data,
        });
      },
      () => {
        if (live) setLoaded("failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api, dec, added]);

  if (loaded === null) return <Frame />;
  const world =
    loaded === "failed"
      ? undefined
      : (loaded.worlds.find((x) => x.id === app.params.id) ??
        loaded.worlds.find((x) => !added.some((a) => a.id === x.id)) ??
        loaded.worlds[0]);
  if (loaded === "failed" || !world) {
    return (
      <Frame>
        <h1 className="park-world-h1" tabIndex={-1}>
          World
        </h1>
        <p className="park-world-meta">Not connected yet</p>
      </Frame>
    );
  }

  const w = world;
  const isCity = w.tier === "City";
  const isTown = w.tier === "Town";
  const isPaused = Boolean(paused[w.id]);
  const mine = loaded.decisions.filter((d) => d.world === w.id);
  const open = mine.filter((d) => !dec[d.k]).length;
  const look = stateLook(w, isPaused);
  const chip = w.st === "needs" && !isPaused ? decisionsWord(app.needsLeft) : look[0];
  const { skills, tools } = skillsAndTools(w, loaded.skills, loaded.connectors);
  const wide = (app.vw || 1440) >= 1060;
  const id = encodeURIComponent(w.id);
  // A world has a stage only when its data came from the live API; a world started on this page is local state.
  const hasStage = loaded.live && !added.some((a) => a.id === w.id);
  const stage = (to: string): string | null => (hasStage ? to : null);

  const togglePause = () => {
    setPaused((p) => ({ ...p, [w.id]: !isPaused }));
    app.toast(isPaused ? "Resumed. Agents are back at work" : "Paused. No spend while paused");
  };
  const share = () => {
    try {
      // document.URL is the address as location.href gives it; the park static checks keep `location` to router.ts
      Promise.resolve(navigator.clipboard.writeText(document.URL)).catch(() => undefined);
    } catch {
      // no clipboard here: the toast still says what the button is for
    }
    app.toast("Link copied. Only your team can open it");
  };

  return (
    <Frame worldId={w.id}>
      <nav aria-label="Breadcrumb" className="park-world-crumb">
        <GoLink className="park-world-back" href="#worlds" onGo={() => app.go("worlds")}>
          {icon("arrowL", 15)}Worlds
        </GoLink>
        <span>/</span>
        <span className="park-world-crumbname">{w.name}</span>
      </nav>

      <div className="park-world-head">
        <div className="park-world-titles">
          <div className="park-world-eyebrowrow">
            <span className="park-world-eyebrow">{`${w.tier} · ${w.tool}`.toUpperCase()}</span>
            <span className="park-world-chip" style={{ background: look[1], color: look[2] }}>
              <span className="park-world-dot" style={{ background: look[3] }} />
              {chip}
            </span>
          </div>
          <h1 className="park-world-h1" tabIndex={-1}>
            {w.name}
            {w.sample ? <SampleBadge /> : null}
          </h1>
          <p className="park-world-meta">
            {w.sample
              ? `Recorded ${w.started}`
              : `Owned by ${w.owner} · started ${w.started} · ${agentsWord(w.agents)}`}
          </p>
          {w.sample ? <SampleNote /> : null}
        </div>
        <div className="park-world-actions">
          <Button
            variant="secondary"
            icon={icon(isPaused ? "play" : "pause", 14)}
            onClick={togglePause}
            {...(w.sample ? { disabled: true, title: "A recorded replay cannot be paused" } : {})}
          >
            {isPaused ? "Resume" : "Pause"}
          </Button>
          <Button variant="secondary" icon={icon("share", 16)} onClick={share}>
            Share
          </Button>
          {isCity ? (
            <StageLink className="park-world-live" href={stage(stagePath(w.id))}>
              {icon("play", 14)}Open live view
            </StageLink>
          ) : null}
          {w.sample ? (
            <a className="park-world-live" href={stagePath(w.id)}>
              {icon("play", 14)}Watch the replay
            </a>
          ) : null}
          {isCity && !hasStage ? (
            <span id={NO_STAGE_ID} className="park-world-sr">
              {NO_STAGE}
            </span>
          ) : null}
        </div>
      </div>

      <div
        className="park-world-top"
        style={{
          gridTemplateColumns: wide ? "minmax(0,1.7fr) minmax(300px,1fr)" : "minmax(0,1fr)",
        }}
      >
        <div className="park-world-mapcard">
          <div className={isCity ? "park-world-map" : "park-world-map park-world-map--art"}>
            <MapArt w={w} plans={loaded.plans} app={app} />
            <div className="park-world-tag">{heroTagOf(w)}</div>
            {isPaused ? (
              <div className="park-world-overlay">
                <div className="park-world-pill">
                  {icon("pause", 15)}Paused · agents are waiting
                </div>
              </div>
            ) : null}
            {isCity ? (
              <nav aria-label="Run views" className="park-world-lenses">
                <StageLink href={stage(`/world/${id}/story`)}>Story</StageLink>
                <StageLink href={stage(`/world/${id}/trace`)}>Trace</StageLink>
                <StageLink href={stage(`/world/${id}/delivery`)}>Delivery</StageLink>
                <StageLink href={stage(`/world/${id}/inspect/${INSPECT_BUILDING}`)}>
                  Inspect
                </StageLink>
              </nav>
            ) : null}
          </div>
          <div className="park-world-progrow">
            <div className="park-world-progwrap">
              <div className="park-world-track">
                <div
                  className="park-world-fill"
                  style={{ width: `${w.prog ?? 0}%`, background: look[4] }}
                />
              </div>
              <span className="park-world-proglabel">
                {w.prog != null ? `${w.prog}%` : w.nextV}
              </span>
            </div>
            {isCity ? (
              <div className="park-world-legend">
                {LEGEND.map(([colour, label]) => (
                  <span key={label} className="park-world-legenditem">
                    <span className="park-world-swatch" style={{ background: colour }} />
                    {label}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        {part(2) ? (
          <div className="park-world-side">
            {open > 0 ? (
              <WaitingCard
                mine={mine}
                dec={dec}
                night={app.night}
                onDecide={(key) => app.decide(key)}
                onLater={() => app.toast("Tilo will remind you at 16:00")}
              />
            ) : null}
            <SpendCard w={w} mine={mine} dec={dec} onLedger={() => app.go("ledger")} />
            <FactsCard
              w={w}
              skills={skills}
              tools={tools}
              onSkill={(skill) => app.go("skills", { id: skill })}
              onTools={() => app.go("connectors")}
            />
          </div>
        ) : null}
      </div>

      {part(3) ? (
        <div className="park-world-lower">
          {isCity ? <Districts districts={w.districts ?? []} /> : null}
          {isTown ? (
            <RunHistory
              runs={w.runs ?? []}
              onRunNow={() => app.toast("Run started. You’ll get a notification when it finishes")}
              onAgenda={() => app.go("agenda")}
            />
          ) : null}
          {!isCity && !isTown ? (
            <Result
              w={w}
              onOpen={() => app.toast("Opening the result in Google Drive")}
              onSlack={() => app.toast("Shared to #ops in Slack")}
            />
          ) : null}
          <Activity
            items={
              w.activity ?? [
                {
                  t: w.started,
                  rank: "director",
                  who: "Director",
                  text: `Started ${w.name.toLowerCase()}.`,
                  kind: "info",
                },
              ]
            }
            night={app.night}
          />
        </div>
      ) : null}
    </Frame>
  );
}
