// A control whose feature is not built yet: visible, labelled "Coming soon", aria-disabled, and
// a click does nothing (AGW-08). Never a dead click that looks live. `compact` drops the inline
// caption for rows that carry one shared "Coming soon" line; the title and the accessible name
// still say it.
export function Placeholder({ label, compact = false }: { label: string; compact?: boolean }) {
  return (
    <button
      type="button"
      className={compact ? "secondary placeholder compact" : "secondary placeholder"}
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
