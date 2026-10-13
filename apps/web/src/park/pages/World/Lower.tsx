// The lower grid of the World page: Districts (a City), Run history (a Town) or Result (a Village), and Activity.
import type { ActivityItem, World, WorldDistrict, WorldRun } from "../../api/types";
import { Button } from "../../components";
import { icon } from "../../shell/kit";
import { agentArt } from "./worldArt";
import { ACTIVITY_DOT, DISTRICT_LOOK, keyed, recordedLine } from "./worldModel";

const RUN_OFF_ID = "park-world-runoff";
const OPEN_OFF_ID = "park-world-openoff";

function SectionHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="park-world-sechead">
      <h2 className="park-world-h2">{title}</h2>
      <span className="park-world-sub">{sub}</span>
    </div>
  );
}

function DistrictRow({ d }: { d: WorldDistrict }) {
  const look = DISTRICT_LOOK[d.st];
  return (
    <div className="park-world-district">
      <span className="park-world-dtile" style={{ background: look[3], color: look[4] }}>
        {icon(d.icon, 18)}
      </span>
      <span className="park-world-dinfo park-world-dinfo--stack">
        <span className="park-world-dname">{d.name}</span>
        <span className="park-world-dnote">{d.note}</span>
      </span>
      <span className="park-world-dprog park-world-dprog--stack">
        <span className="park-world-dcount">{`${d.done} of ${d.total} buildings · ${d.agents} agents`}</span>
        <span className="park-world-dbar">
          <span
            className="park-world-dfill"
            style={{ width: `${d.total ? (d.done / d.total) * 100 : 0}%`, background: look[5] }}
          />
        </span>
      </span>
      <span
        className="park-world-dchip park-world-dchip--stack"
        style={{ background: look[1], color: look[2] }}
      >
        {look[0]}
      </span>
    </div>
  );
}

export function Districts({ districts }: { districts: readonly WorldDistrict[] }) {
  return (
    <section aria-label="Districts" className="park-world-section">
      <SectionHead title="Districts" sub={`${districts.length} districts`} />
      {keyed(districts, (d) => d.name).map(([key, d]) => (
        <DistrictRow key={key} d={d} />
      ))}
    </section>
  );
}

function RunRow({ r }: { r: WorldRun }) {
  const tile = r.ok
    ? { background: "var(--okSoft)", color: "var(--ok)" }
    : { background: "var(--amberTile)", color: "var(--amberInk)" };
  return (
    <div className="park-world-run">
      <span className="park-world-rtile" style={tile}>
        {icon(r.ok ? "check" : "flag", 15)}
      </span>
      <span className="park-world-rinfo">
        <span className="park-world-rwhat">{r.what}</span>
        <span className="park-world-rwhen">{r.when}</span>
      </span>
      <span className="park-world-rcost">{r.cost}</span>
    </div>
  );
}

export function RunHistory({
  runs,
  onRunNow,
  onAgenda,
  runNowOff,
}: {
  runs: readonly WorldRun[];
  onRunNow: () => void;
  onAgenda: () => void;
  /** UI-10 B1: why "Run now" is off (no run route is connected): focusable and described, never a false toast. */
  runNowOff?: string;
}) {
  return (
    <section aria-label="Run history" className="park-world-section">
      <SectionHead title="Run history" sub={`${runs.length} recent runs`} />
      {keyed(runs, (r) => `${r.when}|${r.what}`).map(([key, r]) => (
        <RunRow key={key} r={r} />
      ))}
      {runs.length === 0 ? (
        <div className="park-world-noruns">No runs yet. The first run waits for your approval.</div>
      ) : null}
      <div className="park-world-runactions">
        <Button
          variant="primary"
          size="sm"
          icon={icon("play", 14)}
          onClick={runNowOff ? undefined : onRunNow}
          {...(runNowOff ? { "aria-disabled": "true", "aria-describedby": RUN_OFF_ID } : {})}
        >
          Run now
        </Button>
        {runNowOff ? (
          <span id={RUN_OFF_ID} className="park-world-sub">
            {runNowOff}
          </span>
        ) : null}
        <Button variant="secondary" size="sm" onClick={onAgenda}>
          See in Agenda
        </Button>
      </div>
    </section>
  );
}

export function Result({
  w,
  onOpen,
  onSlack,
  slackConnected = true,
  slackReason = "",
  noSlackId,
  recorded = false,
  openOff,
}: {
  w: World;
  /** UI-10 B2: a running line of a sample world is a recording, not a live countdown. */
  recorded?: boolean;
  onOpen: () => void;
  /** UI-10 B1: why "Open result" is off (no file is linked): focusable and described, never a false toast. */
  openOff?: string;
  onSlack: (trigger: HTMLButtonElement) => void;
  slackConnected?: boolean;
  slackReason?: string;
  noSlackId?: string;
}) {
  return (
    <section aria-label="Result" className="park-world-section">
      <SectionHead title="Result" sub={recorded ? "Sample" : (w.when ?? "")} />
      <div className="park-world-result">
        <div className="park-world-out">{w.out ?? ""}</div>
        {w.st === "finished" ? (
          <div className="park-world-resultactions">
            <Button
              variant="primary"
              size="sm"
              onClick={openOff ? undefined : onOpen}
              {...(openOff ? { "aria-disabled": "true", "aria-describedby": OPEN_OFF_ID } : {})}
            >
              Open result
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!slackConnected}
              aria-disabled={!slackConnected ? "true" : undefined}
              aria-describedby={!slackConnected ? noSlackId : undefined}
              title={!slackConnected ? slackReason : "Share this world link to Slack"}
              onClick={(e) => onSlack(e.currentTarget)}
            >
              Share to Slack
            </Button>
            {openOff ? (
              <span id={OPEN_OFF_ID} className="park-world-sub">
                {openOff}
              </span>
            ) : null}
          </div>
        ) : (
          <div className="park-world-running">
            <span className="park-world-spinner" />
            <span>{recorded && w.when ? recordedLine(w.when) : (w.when ?? "")}</span>
          </div>
        )}
      </div>
    </section>
  );
}

function ActivityRow({ a, night }: { a: ActivityItem; night: boolean }) {
  return (
    <div className="park-world-activity">
      <span className="park-world-avatar">
        {a.you
          ? "AM"
          : agentArt(
              a.rank
                ? { rank: a.rank, expr: "neutral" }
                : { role: a.role, expr: a.kind === "needs" ? "needs" : "focused" },
              32,
              night,
            )}
      </span>
      <span className="park-world-ainfo">
        <span className="park-world-who">
          <span className="park-world-adot" style={{ background: ACTIVITY_DOT[a.kind] }} />
          {a.who}
        </span>
        <span className="park-world-atext">{a.text}</span>
      </span>
      <span className="park-world-atime">{a.t}</span>
    </div>
  );
}

// UI-10 B3: "Today" only when every row is from today; a row dated "6 Oct" under "Today" contradicts itself.
const TODAY_ROW = /^(today( |$)|\d{1,2}:\d{2}$|just now$)/i;
const activitySub = (items: readonly ActivityItem[]): string =>
  items.every((a) => TODAY_ROW.test(a.t)) ? "Today" : "Recent";

export function Activity({ items, night }: { items: readonly ActivityItem[]; night: boolean }) {
  return (
    <section aria-label="Activity" className="park-world-section">
      <SectionHead title="Activity" sub={activitySub(items)} />
      {keyed(items, (a) => `${a.t}|${a.who}|${a.text}`).map(([key, a]) => (
        <ActivityRow key={key} a={a} night={night} />
      ))}
    </section>
  );
}
