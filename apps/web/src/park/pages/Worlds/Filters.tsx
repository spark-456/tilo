// The filter row of the Worlds page (STUDIO-3): status tabs with counts, the search box and the size buttons.
import type { ChangeEvent } from "react";
import { cx } from "../../components/cx";
import type { Art } from "./art";
import { SCALES, STATUS_TABS, type StatusFilter, type TierFilter } from "./model";

interface FiltersProps {
  art: Art;
  status: StatusFilter;
  tier: TierFilter;
  query: string;
  count: (f: StatusFilter) => number;
  onStatus: (f: StatusFilter) => void;
  onTier: (t: TierFilter) => void;
  onQuery: (value: string) => void;
}

export function Filters({
  art,
  status,
  tier,
  query,
  count,
  onStatus,
  onTier,
  onQuery,
}: FiltersProps) {
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
      <div className="park-worlds-search">
        {art.icon("search", 17)}
        <input
          className="park-worlds-search__input"
          aria-label="Search worlds"
          placeholder="Find a world"
          value={query}
          onChange={(e: ChangeEvent<HTMLInputElement>) => onQuery(e.target.value)}
        />
      </div>
      {/* biome-ignore lint/a11y/useSemanticElements: a group of toggle buttons, not a form fieldset */}
      <div role="group" aria-label="Size" className="park-worlds-scale">
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
