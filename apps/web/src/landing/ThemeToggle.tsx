// STUDIO-6: the light/dark switch of the signed-out pages (a 44px icon button in the header). Display state only.
export function ThemeToggle({ night, onToggle }: { night: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="landing-iconbtn"
      aria-label={night ? "Switch to light mode" : "Switch to dark mode"}
      onClick={onToggle}
    >
      <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        {night ? (
          <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.900 4.900l1.400 1.400M17.700 17.700l1.400 1.400M4.900 19.100l1.400-1.400M17.700 6.300l1.400-1.400" />
          </g>
        ) : (
          <path fill="currentColor" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.800z" />
        )}
      </svg>
    </button>
  );
}
