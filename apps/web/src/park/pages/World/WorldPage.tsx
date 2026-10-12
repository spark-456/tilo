// The Park "World" page (WEB-6; design "Tilo App World.dc.html"): one world's overview. The title block and
// its buttons, the map with its progress, the decisions it waits on, spend, facts, skills and tools, and then
// Districts (a City), Run history (a Town) or Result (a Village) beside Activity. The worlds, plans,
// decisions, skills and connectors come through useParkApi(); pausing is page state and writes nothing
// (docs/park-designed-not-in-prd/World.md). A decision is taken with app.decide (the store toasts it with
// Undo), navigation inside the Park app is app.go, and the links to the live stage and its lenses are real
// addresses the browser follows, but only for a world whose data came from the live API: a sample world has no
// recorded run, so the same elements are disabled with the reason (docs/park-designed-not-in-prd/World.md).
import { type ChangeEvent, type ReactNode, useEffect, useRef, useState } from "react";
import { createRoomClient } from "../../api/live/meetingHall";
import type {
  ApiResult,
  BuildHandoff,
  Connector,
  Decision,
  Plan,
  Skill,
  World,
} from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { NotFound } from "../../app/NotFound";
import { useDemoSession, useParkApi, useWorldClient } from "../../app/context";
import { stagePath } from "../../app/router";
import {
  SLACK_NOTE_MAX,
  type SlackShareRequest,
  capSlackNote,
  focusablesIn,
  handleSlackDialogKeyDown,
  slackConnectorState,
} from "../../app/slackShare";
import { useStaged } from "../../app/useStaged";
import { Button, PageSheet } from "../../components";
import { SampleBadge, SampleNote } from "../../sample/SampleBadge";
import { icon } from "../../shell/kit";
import { Activity, Districts, Result, RunHistory } from "./Lower";
import { MeetingHall } from "./MeetingHall";
import { FactsCard, GoLink, LovableCard, SpendCard, WaitingCard } from "./Side";
import { SkillProposals } from "./SkillProposals";
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
  /** The side reads that failed or are not built: each card says so itself, the page still opens from the worlds. */
  gaps: { plans: boolean; decisions: boolean; skills: boolean; connectors: boolean };
  handoffs: BuildHandoff[];
}

const NOT_YET = "Not available yet";

/** Runs one side read: its failure is a gap in that card, never the whole page. */
const optional = <T,>(read: Promise<ApiResult<T>>): Promise<ApiResult<T> | null> =>
  read.then(
    (r) => r,
    () => null,
  );

/** S-05's first building (screens/meta.ts): a Park plan's own building ids are not stage ids. */
const INSPECT_BUILDING = "B1";

const NO_STAGE = "Sample world: there is no recorded run to open";
const NO_STAGE_ID = "park-world-nostage";
const NO_SLACK_ID = "park-world-noslack";

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

/** A side card whose read is not built or failed: its own plain line, nothing sample in its place. */
function NotYetCard({ title }: { title: string }) {
  return (
    <section className="park-world-spend" aria-label={title}>
      <div className="park-world-spendhead">
        <span className="park-world-spendtitle">{title}</span>
      </div>
      <div className="park-world-spendnote">{NOT_YET}</div>
    </section>
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
  const worldClient = useWorldClient();
  const demo = useDemoSession(); // QA-DEMO-1: the sample company: labelled, and approving records nothing
  const [roomClient] = useState(createRoomClient);
  const [loaded, setLoaded] = useState<Loaded | "failed" | null>(null);
  const [paused, setPaused] = useState<Record<string, boolean>>({});
  const [slackOpen, setSlackOpen] = useState(false);
  const [slackChannel, setSlackChannel] = useState("");
  const [slackNote, setSlackNote] = useState("");
  const [slackPendingByWorld, setSlackPendingByWorld] = useState<Record<string, SlackShareRequest>>(
    {},
  );
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  // The map and head first, then the side cards, then the lower part: one task each (WEB-MOTION-2).
  const part = useStaged(3);
  const { dec, added } = app;

  useEffect(() => {
    let live = true;
    const handoffRead =
      typeof api.getBuildHandoff === "function"
        ? api.getBuildHandoff().then(
            (r) => r.data,
            (err: unknown) => {
              if (
                err &&
                typeof err === "object" &&
                (err as { code?: unknown }).code === "not_built"
              ) {
                return [];
              }
              throw err;
            },
          )
        : Promise.resolve([]);
    Promise.all([
      api.getWorlds(dec, added),
      optional(api.getPlans(dec)),
      optional(api.getDecisions()),
      optional(api.getSkills()),
      optional(api.getConnectors()),
      handoffRead,
    ]).then(
      ([worlds, plans, decisions, skills, connectors, handoffs]) => {
        if (!live) return;
        setLoaded({
          worlds: worlds.data,
          live: worlds.source === "live",
          plans: plans?.data ?? {},
          decisions: decisions?.data ?? [],
          skills: skills?.data ?? [],
          connectors: connectors?.data ?? [],
          gaps: {
            plans: plans === null,
            decisions: decisions === null,
            skills: skills === null,
            connectors: connectors === null,
          },
          handoffs,
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

  useEffect(() => {
    if (!slackOpen) return;
    const first = focusablesIn(dialogRef.current)[0];
    first?.focus();
  }, [slackOpen]);

  if (loaded === null) return <Frame />;
  const wanted = app.params.id;
  // QA-DEMO-1 M2: an id the list does not hold is "Page not found", never another job (with its Approve buttons).
  // Only an address with no id (the bare /world) falls back to the first world.
  const world =
    loaded === "failed"
      ? undefined
      : (loaded.worlds.find((x) => x.id === wanted) ??
        (wanted
          ? undefined
          : (loaded.worlds.find((x) => !added.some((a) => a.id === x.id)) ?? loaded.worlds[0])));
  if (loaded !== "failed" && wanted && !world) return <NotFound go={app.go} />;
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
  const slackPending = slackPendingByWorld[w.id] ?? null;
  const handoff = loaded.handoffs.find((h) => h.world === w.id) ?? null;
  const open = mine.filter((d) => !dec[d.k]).length + (slackPending ? 1 : 0);
  const look = stateLook(w, isPaused);
  const chip =
    w.st === "needs" && !isPaused && app.needsLeft > 0 ? decisionsWord(app.needsLeft) : look[0];
  const { skills, tools } = skillsAndTools(w, loaded.skills, loaded.connectors);
  const slackState = slackConnectorState(loaded.connectors);
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

  const openSlackDialog = (trigger: HTMLButtonElement) => {
    if (!slackState.connected) return;
    triggerRef.current = trigger;
    setSlackChannel((cur) =>
      cur && slackState.channels.includes(cur) ? cur : (slackState.channels[0] ?? ""),
    );
    setSlackNote("");
    setSlackOpen(true);
  };

  const closeSlackDialog = () => {
    setSlackOpen(false);
    triggerRef.current?.focus();
  };

  const submitSlackApproval = () => {
    const channel = slackChannel || slackState.channels[0];
    if (!channel) return;
    const req: SlackShareRequest = {
      worldId: w.id,
      worldName: w.name,
      channel,
      note: capSlackNote(slackNote),
      sample: !loaded.live,
    };
    setSlackPendingByWorld((prev) => ({ ...prev, [w.id]: req }));
    setSlackOpen(false);
    triggerRef.current?.focus();
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
            {w.sample || demo ? <SampleBadge /> : null}
          </h1>
          <p className="park-world-meta">
            {w.sample
              ? `Recorded ${w.started}`
              : `Owned by ${w.owner} · started ${w.started} · ${agentsWord(w.agents)}`}
          </p>
          {w.sample ? <SampleNote /> : null}
          {demo && !w.sample ? (
            <span className="park-sample-note">
              Sample data from a demo session. Approving here records nothing.
            </span>
          ) : null}
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
          <Button
            variant="secondary"
            size="sm"
            disabled={!slackState.connected}
            aria-disabled={!slackState.connected ? "true" : undefined}
            aria-describedby={!slackState.connected ? NO_SLACK_ID : undefined}
            title={
              !slackState.connected ? slackState.disabledReason : "Share this world link to Slack"
            }
            onClick={(e) => openSlackDialog(e.currentTarget)}
          >
            Share to Slack
          </Button>
          {!slackState.connected ? (
            <span id={NO_SLACK_ID} className="park-world-sr">
              {slackState.disabledReason}
            </span>
          ) : null}
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
        </div>
      </div>

      {loaded.live && worldClient ? <SkillProposals client={worldClient} worldId={w.id} /> : null}
      {slackOpen ? (
        <div className="park-world-slackbackdrop">
          <div
            ref={dialogRef}
            // biome-ignore lint/a11y/useSemanticElements: custom modal dialog with focus trap and role="dialog"
            role="dialog"
            aria-modal="true"
            aria-label="Share to Slack"
            className="park-world-slackdialog"
            onKeyDown={(e) => handleSlackDialogKeyDown(e, dialogRef.current, closeSlackDialog)}
          >
            <div className="park-world-slackhead">
              <div className="park-world-slacktitle">Share to Slack</div>
              <div className="park-world-slacksub">{`${w.name} · ${slackState.account}`}</div>
            </div>
            <label className="park-world-slackfield">
              <span className="park-world-slacklabel">Channel</span>
              <select
                aria-label="Slack channel"
                className="park-world-slackselect"
                value={slackChannel}
                onChange={(e: ChangeEvent<HTMLSelectElement>) => setSlackChannel(e.target.value)}
              >
                {slackState.channels.map((ch) => (
                  <option key={ch} value={ch}>
                    {ch}
                  </option>
                ))}
              </select>
            </label>
            <label className="park-world-slackfield">
              <span className="park-world-slacklabel">
                {`Note (optional, up to ${SLACK_NOTE_MAX} characters)`}
              </span>
              <textarea
                aria-label="Optional note"
                className="park-world-slacknote"
                rows={3}
                maxLength={SLACK_NOTE_MAX}
                value={slackNote}
                onChange={(e: ChangeEvent<HTMLTextAreaElement>) =>
                  setSlackNote(capSlackNote(e.target.value))
                }
              />
            </label>
            <div className="park-world-slackactions">
              <Button variant="needs" size="sm" onClick={submitSlackApproval}>
                Ask for approval
              </Button>
              <Button variant="secondary" size="sm" onClick={closeSlackDialog}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      <div
        className="park-world-top"
        style={{
          gridTemplateColumns: wide ? "minmax(0,1.7fr) minmax(300px,1fr)" : "minmax(0,1fr)",
        }}
      >
        <div className="park-world-mapcard">
          <div className={isCity ? "park-world-map" : "park-world-map park-world-map--art"}>
            <MapArt w={w} plans={loaded.plans} app={app} />
            {isCity && loaded.gaps.plans ? (
              <p className="park-world-meta">City map: {NOT_YET}</p>
            ) : null}
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
          {isCity && !hasStage ? (
            // QA-DEMO-1 m3: the reason the lens links and "Open live view" are off is words on the page, not a tooltip
            <p id={NO_STAGE_ID} className="park-world-nostage">
              {NO_STAGE}
            </p>
          ) : null}
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
            {loaded.gaps.decisions ? (
              <NotYetCard title="Waiting on you" />
            ) : open > 0 ? (
              <WaitingCard
                mine={mine}
                dec={dec}
                night={app.night}
                onDecide={(key) => app.decide(key)}
                onLater={() => app.toast("Tilo will remind you at 16:00")}
                slackPending={slackPending}
              />
            ) : null}
            {handoff ? (
              <LovableCard
                handoff={handoff}
                dec={dec}
                sample={Boolean(w.sample)}
                onDecide={(key) => app.decide(key)}
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
            {loaded.gaps.skills || loaded.gaps.connectors ? (
              <NotYetCard title={loaded.gaps.skills ? "Skills" : "Tools"} />
            ) : null}
          </div>
        ) : null}
      </div>

      {hasStage && roomClient && !w.sample ? (
        <MeetingHall key={w.id} worldId={w.id} client={roomClient} />
      ) : null}
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
              onSlack={openSlackDialog}
              slackConnected={slackState.connected}
              slackReason={slackState.disabledReason}
              noSlackId={NO_SLACK_ID}
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
