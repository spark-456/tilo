// The Ledger's middle sections: where it goes, cost per run, approval wait times, what Tilo gave back.
import { type ReactNode, useId, useState } from "react";
import type { Ledger } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { Button, SegmentedControl } from "../../components";
import {
  type By,
  METHODS,
  donut,
  groupsWithRows,
  hourBars,
  memoryBars,
  memoryWeeks,
  money,
  runCards,
  runsHeadline,
  waitBuckets,
  waitTypes,
  waitsHeadline,
} from "./model";

export function Head({
  eyebrow,
  title,
  balance,
}: { eyebrow: string; title: string; balance?: boolean }) {
  return (
    <div>
      <div className="park-ledger-eyebrow">{eyebrow}</div>
      {title ? (
        <h2 className={balance ? "park-ledger-h2 park-ledger-h2--balance" : "park-ledger-h2"}>
          {title}
        </h2>
      ) : null}
    </div>
  );
}

const BY_TABS = [
  { value: "world", label: "World" },
  { value: "tool", label: "Tool" },
  { value: "role", label: "Agent" },
] as const;

export function WhereItGoes({ L }: { L: Ledger }) {
  const groups = groupsWithRows(L);
  const [picked, setBy] = useState<By>("world");
  // Only the groupings the Ledger has rows for are offered; the first of them opens.
  const by = groups.includes(picked) ? picked : (groups[0] ?? picked);
  const tabs = BY_TABS.filter((t) => groups.includes(t.value));
  const d = donut(L, by);
  return (
    <section aria-label="Where it goes" className="park-ledger-card">
      <Head eyebrow="WHERE IT GOES" title={d.head} balance />
      {tabs.length > 1 ? (
        <div className="park-ledger-group">
          <SegmentedControl
            label="Group by"
            options={tabs}
            value={by}
            onChange={(v) => setBy(v as By)}
          />
        </div>
      ) : null}
      <div className="park-ledger-donutrow">
        <div className="park-ledger-donut">
          <div className="park-ledger-ring" data-donut="" style={{ background: d.conic }} />
          <div className="park-ledger-hole">
            <span className="park-ledger-hole-label">Total</span>
            <span className="park-ledger-hole-value">{d.total}</span>
          </div>
        </div>
        <div className="park-ledger-legendlist">
          {d.rows.map((r) => (
            <div key={r.name} className="park-ledger-legendrow" data-legend-row="">
              <span className="park-ledger-swatch" style={{ background: r.c }} />
              <span className="park-ledger-ellipsis">{r.name}</span>
              <span className="park-ledger-legendamt">
                {r.amt} · {r.pct}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function CostPerRun({ L, go }: { L: Ledger; go: AppCtx["go"] }) {
  return (
    <section aria-label="Cost per run" className="park-ledger-card park-ledger-card--tight">
      <Head eyebrow="COST PER RUN" title={runsHeadline(L)} balance />
      <div className="park-ledger-runs">
        {runCards(L).map((s) => (
          <button
            key={s.name}
            type="button"
            className="park-ledger-run"
            onClick={() => go("skills", { id: s.skill })}
          >
            <span className="park-ledger-runtop">
              <span className="park-ledger-runname park-ledger-ellipsis">{s.name}</span>
              <span className="park-ledger-drop">{s.drop}</span>
            </span>
            <svg
              className="park-ledger-spark"
              viewBox="0 0 200 60"
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path className="park-ledger-spark-area" d={s.area} />
              <path
                className="park-ledger-spark-line"
                d={s.line}
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            <span className="park-ledger-runends">
              <span>{s.first} run 1</span>
              <span>
                {s.now} run {s.n}
              </span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function RecordedRuns({ L }: { L: Ledger }) {
  return (
    <section aria-label="Recorded run costs" className="park-ledger-card">
      <Head eyebrow="COST PER RUN" title="Recorded run totals" />
      <p className="park-ledger-sub">
        Costs recorded so far. Skill cost trends are not available yet.
      </p>
      <div className="park-ledger-types">
        {L.recordedRuns?.map((run) => (
          <div key={run.id} className="park-ledger-type park-ledger-recorded">
            <span className="park-ledger-ellipsis" title={run.id}>
              {run.id}
            </span>
            <span>
              {money(L, run.usd)} · {run.completed ? "Completed" : "Completion not recorded"}
            </span>
          </div>
        ))}
        {!L.recordedRuns?.length ? (
          <p className="park-ledger-sub">No run costs recorded yet.</p>
        ) : null}
      </div>
    </section>
  );
}

export function ApprovalWaits({ L, app }: { L: Ledger; app: AppCtx }) {
  const backup = app.prefs.backup;
  return (
    <section aria-label="Approval wait times" className="park-ledger-card park-ledger-card--tight">
      <Head eyebrow="APPROVAL WAIT TIMES" title={waitsHeadline(L)} balance />
      <div className="park-ledger-stack8">
        {waitBuckets(L).map((b) => (
          <div key={b.label} className="park-ledger-bucket">
            <span className="park-ledger-bucket-label">{b.label}</span>
            <span className="park-ledger-track">
              <span className="park-ledger-fill" style={{ width: b.w, background: b.c }} />
            </span>
            <span className="park-ledger-count">{b.n}</span>
          </div>
        ))}
      </div>
      <div className="park-ledger-types">
        {waitTypes(L, backup).map((w) => (
          <div key={w.name} className="park-ledger-type">
            <span>{w.name}</span>
            <span style={{ color: w.c }}>{w.v}</span>
          </div>
        ))}
      </div>
      {L.recordedRuns !== undefined ? (
        <p className="park-ledger-sub">
          Measured from recorded requests to answers. Backup impact is not available yet.
        </p>
      ) : backup ? null : (
        <div className="park-ledger-callout">
          <span className="park-ledger-callout-text">
            Jin approves all outside sharing. A backup approver would cut the wait.
          </span>
          <Button variant="needs" size="sm" onClick={() => app.go("team", { focus: "share" })}>
            Add a backup
          </Button>
        </div>
      )}
    </section>
  );
}

/** A figure that is an estimate says so, and its method opens in place (FR-SPD-06; PRD 14.2, 14.3). */
function Estimate({ method }: { method: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="park-ledger-estimate">
      <span className="park-ledger-estimate-row">
        <span className="park-ledger-estimate-tag" data-estimate="">
          Estimate
        </span>
        <button
          type="button"
          className="park-ledger-method"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(!open)}
        >
          How this is counted
        </button>
      </span>
      <p id={id} className="park-ledger-method-text" hidden={!open}>
        {method}
      </p>
    </div>
  );
}

export function GaveBack({ L }: { L: Ledger }): ReactNode {
  const memory = memoryBars(L);
  const weeks = memoryWeeks(L);
  const hours = hourBars(L);
  const saved = money(
    L,
    L.memory.reduce((a, v) => a + v, 0),
  );
  const total = L.hours.reduce((a, h) => a + h[1], 0);
  return (
    <section aria-label="What Tilo gave back" className="park-ledger-card">
      <Head
        eyebrow="WHAT TILO GAVE BACK"
        title={[
          L.memory.length ? `${saved} saved by memory` : null,
          L.hours.length ? `${total} hours handed back to people` : null,
        ]
          .filter(Boolean)
          .join(" and ")}
      />
      <div className="park-ledger-back">
        {L.memory.length > 0 ? (
          <div className="park-ledger-col">
            <div className="park-ledger-colhead">
              <span>Saved by memory, per week</span>
              <span style={{ color: "var(--sch)" }}>{saved}</span>
            </div>
            <Estimate method={METHODS.memory} />
            <div className="park-ledger-bars">
              {memory.map((b, i) => (
                <div key={`${b.v}-${i}`} className="park-ledger-bar">
                  <span className="park-ledger-bar-value">{b.v}</span>
                  <span className="park-ledger-bar-col" style={{ height: b.h, background: b.c }} />
                </div>
              ))}
            </div>
            {weeks.length > 0 ? (
              <div className="park-ledger-weeks">
                {weeks.map((w) => (
                  <span key={w}>{w}</span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
        {L.hours.length > 0 ? (
          <div className="park-ledger-col park-ledger-col--hours">
            <div className="park-ledger-colhead">
              <span>Hours handed back, by team</span>
              <span style={{ color: "var(--heroInk)" }}>{total} h</span>
            </div>
            <Estimate method={METHODS.hours} />
            <div className="park-ledger-stacked">
              {hours.map((t) => (
                <span key={t.name} style={{ width: t.w, background: t.c }} />
              ))}
            </div>
            <div className="park-ledger-tiles">
              {hours.map((t) => (
                <div key={t.name} className="park-ledger-tile">
                  <span className="park-ledger-tilebar" style={{ background: t.c }} />
                  <span className="park-ledger-tiletext">
                    <span className="park-ledger-tilename">
                      {t.name} · {t.h}
                    </span>
                    <span className="park-ledger-tilewhat">{t.what}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
