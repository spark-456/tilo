// The status tabs (with counts) and the scale legend of the Worlds page.
import { cx } from "../../components/cx";
import { SCALES, STATUS_TABS, type StatusFilter, type TierFilter } from "./model";

interface FiltersProps {
  status: StatusFilter;
  tier: TierFilter;
  count: (f: StatusFilter) => number;
  onStatus: (f: StatusFilter) => void;
  onTier: (t: TierFilter) => void;
}

export function Filters({ status, tier, count, onStatus, onTier }: FiltersProps) {
  return (
    <div className="park-worlds-filters">
      <div role="tablist" aria-label="Status" className="park-worlds-tabs">
        {STATUS_TABS.map(([f, label]) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={status === f}
            className={cx("park-worlds-tab", status === f && "park-worlds-tab--on")}
            onClick={() => onStatus(f)}
          >
            {label}
            <span className="park-worlds-tab__n">{count(f)}</span>
          </button>
        ))}
      </div>
      <div className="park-worlds-scale">
        <span className="park-worlds-scale__label">SCALE</span>
        {SCALES.map(([t, label]) => (
          <button
            key={t}
            type="button"
            aria-pressed={tier === t}
            className={cx("park-worlds-scale__btn", tier === t && "park-worlds-scale__btn--on")}
            onClick={() => onTier(t)}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
