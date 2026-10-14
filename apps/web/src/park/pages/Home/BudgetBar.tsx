// The confirm card's budget meter, ported from the retired S-03 (artboard Tilo 2 Balanced Refined 2-1/2-4). It draws
// only what the card holds: the approach's estimated credit range and the cap Start approves. Nothing has been spent,
// so there is no "used" fill (HR-1). The words are in the label; the bar is a second way to read them.
export interface MeterGeometry {
  /** Percent of the track where the estimate starts, and how wide it is. */
  readonly bandLeft: number;
  readonly bandWidth: number;
  /** Percent where the cap sits, or null while there is no cap. */
  readonly capAt: number | null;
}

export function meterGeometry(min: number, max: number, cap: number | null): MeterGeometry {
  const scale = Math.max(max, cap ?? 0, 1) * 1.15; // room past the larger end, so it never touches the edge
  const pct = (n: number) => Math.round((n / scale) * 1000) / 10;
  return { bandLeft: pct(min), bandWidth: pct(max - min), capAt: cap === null ? null : pct(cap) };
}

export function BudgetBar({ min, max, cap }: { min: number; max: number; cap: number | null }) {
  const g = meterGeometry(min, max, cap);
  const label = `Estimated ${min} to ${max} credits${cap === null ? "" : `; your cap is ${cap}`}`;
  return (
    <div className="park-home-meter" role="img" aria-label={label} data-testid="budget-meter">
      <span
        className="park-home-meter__band"
        style={{ left: `${g.bandLeft}%`, width: `${g.bandWidth}%` }}
      />
      {g.capAt !== null ? (
        <span className="park-home-meter__cap" style={{ left: `${g.capAt}%` }} />
      ) : null}
    </div>
  );
}
