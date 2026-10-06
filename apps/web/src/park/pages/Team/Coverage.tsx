// WEB-10 Team page: "Who signs off, and how fast". `flash` is the amber border when the Ledger sent you
// here (`params.focus`); the design clears it after 1.8 s with a timer, which arrives with WEB-3b.
import { useEffect, useRef } from "react";
import { icon } from "./teamKit";
import { type CoverRow, initialsOf } from "./teamModel";

interface CoverageProps {
  rows: readonly CoverRow[];
  flash: boolean;
  onBackup: (row: CoverRow, personId: string) => void;
  onLedger: () => void;
}

export function Coverage({ rows, flash, onBackup, onLedger }: CoverageProps) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    if (flash) ref.current?.scrollIntoView?.({ block: "start" });
  }, [flash]);
  return (
    <section
      ref={ref}
      className="park-team-card park-team-cover-card"
      aria-label="Approval coverage"
      data-flash={flash ? "true" : undefined}
    >
      <div className="park-team-cardhead park-team-cardhead--split">
        <div className="park-team-heading">
          <h2 className="park-team-h2">Who signs off, and how fast</h2>
          <div className="park-team-hint">
            Average wait this month, from the Ledger. Alex can approve anything as owner.
          </div>
        </div>
        <a
          href="/park/ledger"
          className="park-team-link"
          onClick={(e) => {
            e.preventDefault();
            onLedger();
          }}
        >
          See wait times
        </a>
      </div>
      <table className="park-team-blk">
        <tbody className="park-team-blk">
          {rows.map((r) => (
            <tr key={r.id} className="park-team-cover">
              <td className="park-team-what">{r.what}</td>
              <td className="park-team-covwho">
                <span className="park-team-avs">
                  {r.who.map((w) => (
                    <span
                      key={w.id}
                      title={w.name}
                      className="park-team-av"
                      style={{ background: w.c }}
                    >
                      {initialsOf(w.name)}
                    </span>
                  ))}
                </span>
                <span className="park-team-names">{r.names}</span>
              </td>
              <td className={r.slow ? "park-team-wait park-team-wait--slow" : "park-team-wait"}>
                {r.wait}
              </td>
              <td className="park-team-act">
                {r.single ? (
                  <select
                    className="park-team-select park-team-select--backup"
                    aria-label={`Add a backup for ${r.what}`}
                    value=""
                    onChange={(e) => e.target.value && onBackup(r, e.target.value)}
                  >
                    <option value="">Add a backup…</option>
                    {r.opts.map((o) => (
                      <option key={o.id} value={o.id}>
                        {o.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="park-team-covered">
                    {icon("check", 12)}
                    Covered
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
