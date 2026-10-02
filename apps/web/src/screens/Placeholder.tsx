// A control whose feature is not built yet: visible, labelled "Coming soon", aria-disabled, and
// a click does nothing (AGW-08). Never a dead click that looks live. `compact` sits in a row of
// placeholders under one shared "Coming soon" chip; the word stays in the accessible name.
export function Placeholder({ label, compact = false }: { label: string; compact?: boolean }) {
  return (
    <button
      type="button"
      className={compact ? "secondary placeholder compact" : "secondary placeholder"}
      aria-disabled="true"
      title="Coming soon"
      onClick={(e) => e.preventDefault()}
    >
      {label} <span className="soon">Coming soon</span>
    </button>
  );
}
