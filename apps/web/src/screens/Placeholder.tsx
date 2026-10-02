// A control whose feature is not built yet: visible, labelled "Coming soon", aria-disabled, and
// a click does nothing (AGW-08). Never a dead click that looks live.
export function Placeholder({ label }: { label: string }) {
  return (
    <button
      type="button"
      className="secondary placeholder"
      aria-disabled="true"
      title="Coming soon"
      onClick={(e) => e.preventDefault()}
    >
      {label} <span className="soon">Coming soon</span>
    </button>
  );
}
