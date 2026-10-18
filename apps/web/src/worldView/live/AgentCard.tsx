// TILO-T-WORLD / TW-2: the stats card over an agent the pointer is on:
// name, role, 32x40 AgentSprite, color swatch, status chip, task, units, credits, tools, and last said lines.
import { useLayoutEffect, useRef, useState } from "react";
import { Icon } from "../../design/tilo-t";
import { AgentSprite, agentColorByOrder, agentColorNameByOrder } from "../../design/tilo-w";
import type { AgentStats } from "../../world/agentStats";
import { spriteKindOfRank, spriteMoodOfStatus } from "./agentLook";
import "./live.css";

const WIDTH = 280;

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
  const col = agentColorByOrder(stats.order);
  const colName = agentColorNameByOrder(stats.order);

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
        <AgentSprite
          scale={1.2}
          col={col}
          kind={spriteKindOfRank(stats.rank)}
          mood={spriteMoodOfStatus[stats.status]}
          lit
        />
        <div>
          <p className="tw-card__name">{stats.name}</p>
          <p className="tw-card__role">
            {stats.role}
            {stats.district ? ` · ${stats.district}` : ""}
          </p>
          <div
            className="tw-card__swatch"
            style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}
          >
            <span
              style={{
                display: "inline-block",
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: col,
              }}
            />
            <span style={{ fontSize: 12, opacity: 0.85 }}>{colName} · on map &amp; chat</span>
          </div>
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
