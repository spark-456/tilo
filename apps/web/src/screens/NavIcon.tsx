// Primary navigation icons (Bundle C1): Tilo's own 24 px stroke glyphs in `currentColor`, so they
// take the label's colour. Decorative: the label beside each one names the destination.
const PATHS: Readonly<Record<string, string>> = {
  home: "M4 11.5 12 5l8 6.5V19a1 1 0 0 1-1 1h-4v-5H9v5H5a1 1 0 0 1-1-1z",
  world: "M12 3 20 7.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9",
  story: "M5 6h14M5 11h14M5 16h9",
  needs: "M6 17V11a6 6 0 0 1 12 0v6l1.5 2h-15zM10 21h4",
  library: "M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10",
  more: "M6 12h.01M12 12h.01M18 12h.01",
};

export function NavIcon({ name }: { name: string }) {
  return (
    <svg
      className="nav-icon"
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[name] ?? PATHS.more} />
    </svg>
  );
}
