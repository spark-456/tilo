import { useState } from "react";
import type { Decision, Ledger } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { Button, SegmentedControl } from "../../components";
import { icon } from "./icons";
import { KINDS, type Kind, activityGroups } from "./model";

/** Activity: filter tabs, day-grouped rows, and a row that opens to its detail (Approve, Open in world). */
export function Activity({
  L,
  decisions,
  app,
}: { L: Ledger; decisions: readonly Decision[]; app: AppCtx }) {
  const [kind, setKind] = useState<Kind>("all");
  const [open, setOpen] = useState(0);
  const { groups, waitN } = activityGroups(L, app.dec, kind, decisions);
  const options = KINDS.map(([value, label]) => ({
    value,
    label: value === "waiting" && waitN ? `${label} · ${waitN}` : label,
  }));
  return (
    <section aria-label="Activity" className="park-ledger-card park-ledger-card--activity">
      <div className="park-ledger-acthead">
        <h2 className="park-ledger-h2" style={{ marginTop: 0 }}>
          Activity
        </h2>
        <SegmentedControl
          label="Entry type"
          options={options}
          value={kind}
          onChange={(v) => {
            setKind(v as Kind);
            setOpen(-1);
          }}
        />
      </div>
      {groups.map((g) => (
        <div key={g.day} className="park-ledger-day">
          <div className="park-ledger-dayname">{g.day}</div>
          {g.rows.map((r) => {
            const isOpen = open === r.index;
            const bg = isOpen ? "var(--sunk)" : r.waiting ? "var(--amberSoft)" : "transparent";
            return (
              <div key={r.index} className="park-ledger-arow" style={{ background: bg }}>
                <button
                  type="button"
                  className="park-ledger-arow-btn"
                  aria-expanded={isOpen}
                  onClick={() => setOpen(isOpen ? -1 : r.index)}
                >
                  <span className="park-ledger-time">{r.time}</span>
                  <span
                    className="park-ledger-icontile"
                    style={{ background: r.tile, color: r.ink }}
                  >
                    {icon(r.icon, 17)}
                  </span>
                  <span className="park-ledger-what">
                    <span className="park-ledger-what-title">{r.what}</span>
                    <span className="park-ledger-what-sub">{r.sub}</span>
                  </span>
                  <span className="park-ledger-amt">
                    <span className="park-ledger-amt-value" style={{ color: r.amtColor }}>
                      {r.amt}
                    </span>
                    <span className="park-ledger-amt-tag" style={{ color: r.tagColor }}>
                      {r.tag}
                    </span>
                  </span>
                </button>
                {isOpen ? (
                  <div className="park-ledger-detail">
                    {r.detail.map((d) => (
                      <div key={d.k}>
                        <div className="park-ledger-detail-key">{d.k}</div>
                        <div className="park-ledger-detail-value">{d.v}</div>
                      </div>
                    ))}
                    <div className="park-ledger-detail-actions">
                      {r.waiting && r.decKey ? (
                        <span className="park-ledger-approve">
                          <Button
                            variant="needs"
                            size="sm"
                            onClick={() => r.decKey && app.decide(r.decKey)}
                          >
                            {r.approveLabel}
                          </Button>
                        </span>
                      ) : null}
                      <span className="park-ledger-open">
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => app.go("world", { id: r.world })}
                        >
                          Open in world
                          {icon("chevR", 12)}
                        </Button>
                      </span>
                    </div>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ))}
      {groups.length === 0 ? (
        <div className="park-ledger-empty">Nothing here this month.</div>
      ) : null}
    </section>
  );
}
