// A control whose feature is not built yet: visible, labelled "Coming soon", aria-disabled, and
// a click does nothing (AGW-08). Never a dead click that looks live. `compact` drops the inline
// caption for rows that carry one shared "Coming soon" line; the title and the accessible name
// still say it.
export function Placeholder({
  label,
  compact = false,
  danger = false,
}: { label: string; compact?: boolean; danger?: boolean }) {
  return (
    <button
      type="button"
      className={`secondary placeholder${compact ? " compact" : ""}${danger ? " danger" : ""}`}
      aria-disabled="true"
      aria-label={compact ? `${label}, coming soon` : undefined}
      title="Coming soon"
      onClick={(e) => e.preventDefault()}
    >
      {label}
      {!compact && (
        <>
          {" "}
          <span className="soon">Coming soon</span>
        </>
      )}
    </button>
  );
}
