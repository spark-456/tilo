// Profile page icons (WEB-12): 20px stroke glyphs drawn for this page, `currentColor`, hidden from
// assistive technology (every control carries its own name). Page-local until AG-WEB promotes a shared set.
import type { ReactNode } from "react";

const glyph = (children: ReactNode) => (
  <svg
    width="20"
    height="20"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {children}
  </svg>
);

export const ICONS = {
  profile: glyph(<path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 20c0-3.5 3.6-6 8-6s8 2.5 8 6" />),
  notifications: glyph(<path d="M6 17v-6a6 6 0 0 1 12 0v6l1.5 2h-15z M10 21h4" />),
  appearance: glyph(
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v2 M12 19v2 M3 12h2 M19 12h2 M5.6 5.6 7 7 M17 17l1.4 1.4 M18.4 5.6 17 7 M7 17l-1.4 1.4" />
    </>,
  ),
  security: glyph(<path d="M12 3l7 3v5c0 5-3 8.5-7 10-4-1.5-7-5-7-10V6z M9 12l2 2 4-4" />),
  billing: glyph(
    <>
      <rect x="3" y="6" width="18" height="13" rx="2.5" />
      <path d="M3 10h18" />
    </>,
  ),
  plug: glyph(<path d="M9 3v5 M15 3v5 M7 8h10v3a5 5 0 0 1-10 0z M12 16v5" />),
  moon: glyph(<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />),
  phone: glyph(
    <>
      <rect x="7" y="2.5" width="10" height="19" rx="2.5" />
      <path d="M11 18.5h2" />
    </>,
  ),
  laptop: glyph(
    <>
      <rect x="4.5" y="5" width="15" height="10" rx="1.5" />
      <path d="M2.5 19h19" />
    </>,
  ),
  tablet: glyph(
    <>
      <rect x="5" y="3" width="14" height="18" rx="2.5" />
      <path d="M11 18h2" />
    </>,
  ),
  download: glyph(<path d="M12 4v11 M7.5 11l4.5 4.5 4.5-4.5 M5 20h14" />),
  // UI-STUDIO-5: a gauge (limits) and a raised hand (ask before).
  limits: glyph(<path d="M4 16a8 8 0 1 1 16 0 M12 16l4-5 M4 20h16" />),
  ask: glyph(<path d="M12 18h.01 M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.7.3-1 1-1 1.7v1" />),
} as const;
