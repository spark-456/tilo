// TILO-T-WORLD: the stats card over an agent the pointer is on (and the same facts in the agent panel's header): name
// and role, what it is doing and where, units done, tools called, credits spent and its last three lines. Every number
// is read from the recorded events (agentStats); the card is display state, never an event (HR-1).
import { useLayoutEffect, useRef, useState } from "react";
import { Buddy, Icon } from "../../design/tilo-t";
import type { AgentStats } from "../../world/agentStats";
import { MOOD_OF_STATUS, roleOf } from "./agentLook";
import "./live.css";

const WIDTH = 264;

export function AgentFacts({ stats }: { stats: AgentStats }) {
  return (
    <>
      <div className="tw-facts__row">
        <span className="tw-chip" data-status={stats.status}>
          {stats.status}
        </span>
        {stats.at ? (
          <span className="tw-facts__at">
            <Icon name="pin" size={14} /> {stats.at.name}
          </span>
        ) : null}
      </div>
      {stats.task ? <p className="tw-facts__task">{stats.task}</p> : null}
      <dl className="tw-facts__grid">
        <div>
          <dt>Units done</dt>
          <dd>{stats.unitsDone}</dd>
        </div>
        <div>
          <dt>Work steps</dt>
          <dd>{stats.workCalls}</dd>
        </div>
        <div>
          <dt>Credits</dt>
          <dd>{stats.credits}</dd>
        </div>
      </dl>
      <p className="tw-facts__tools">
        <span>Tools used</span>
        {stats.tools.length > 0 ? stats.tools.join(", ") : "none recorded"}
      </p>
    </>
  );
}

export function AgentCard({
  stats,
  at,
}: {
  stats: AgentStats;
  /** The pointer, in px from the stage's corner. */
  at: { x: number; y: number };
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const parent = ref.current?.parentElement;
    if (parent) setBox({ w: parent.clientWidth, h: parent.clientHeight });
  }, []);
  const left = box.w ? Math.max(8, Math.min(at.x + 16, box.w - WIDTH - 8)) : at.x + 16;
  const top = box.h ? Math.max(8, Math.min(at.y + 12, box.h - 220)) : at.y + 12;
  return (
    <div
      ref={ref}
      className="tw-card tw-fade"
      data-testid="agent-card"
      style={{ left, top, width: WIDTH }}
      role="tooltip"
      aria-label={`${stats.name}, ${stats.role}`}
    >
      <div className="tw-card__head">
        <Buddy mood={MOOD_OF_STATUS[stats.status]} role={roleOf(stats.rank)} size={44} />
        <div>
          <p className="tw-card__name">{stats.name}</p>
          <p className="tw-card__role">
            {stats.role}
            {stats.district ? ` · ${stats.district}` : ""}
          </p>
        </div>
      </div>
      <AgentFacts stats={stats} />
      {stats.said.length > 0 ? (
        <ul className="tw-card__said" aria-label="Last things said">
          {stats.said.map((m) => (
            <li key={m.seq}>{m.text}</li>
          ))}
        </ul>
      ) : (
        <p className="tw-card__quiet">Nothing said yet.</p>
      )}
      <p className="tw-card__hint">Click to talk to {stats.name}</p>
    </div>
  );
}
