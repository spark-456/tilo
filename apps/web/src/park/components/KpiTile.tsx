// KPI tile (README: r18, padding 16 18, label 13/800, value 28/800, sub 13/700). It is one real button
// only when it has an onClick (the Ledger "Waiting on you" tile); otherwise it is plain text.
import { cx } from "./cx";
import "./park.components.css";

export type KpiTone = "amber" | "ok" | "sch" | "hero";

export interface KpiTileProps {
  label: string;
  value: string;
  sub?: string;
  /** The design's tints: amber (waiting), ok (done), sch (memory), hero (hours). Plain when omitted.
   * The sch label is --sch on --schSoft, 3.86:1 by day: the reference's own pair, kept as is. */
  tone?: KpiTone;
  onClick?: () => void;
}

export function KpiTile({ label, value, sub, tone, onClick }: KpiTileProps) {
  const className = cx("park-kpi", tone && `park-kpi--${tone}`, onClick && "park-kpi--action");
  const parts = (
    <>
      <span className="park-kpi__label">{label}</span>
      <span className="park-kpi__value">{value}</span>
      {sub !== undefined ? <span className="park-kpi__sub">{sub}</span> : null}
    </>
  );
  return onClick ? (
    <button type="button" className={className} onClick={onClick}>
      {parts}
    </button>
  ) : (
    <div className={className}>{parts}</div>
  );
}
