// PRD 18.3 primary navigation: the desktop left rail and the mobile bottom tabs (World, Story,
// Needs you, Library, More). Every other screen is reached from More. Real links only: each one
// goes to a built screen or to a "Coming soon" screen, never to a dead click.
import { usePathname } from "../router";
import { AppLink } from "./AppLink";
import { screenMeta } from "./meta";

type Section = "home" | "world" | "story" | "needs" | "library" | "more";

const WORLD_ID = /^\/world\/([^/]+)/;
/** Which primary item a path belongs to; anything not claimed by another item is More. */
export function sectionOf(path: string): Section {
  if (path === "/" || path.startsWith("/task/")) return "home";
  if (/^\/world\/[^/]+\/(story|trace)\/?$/.test(path)) return "story";
  if (WORLD_ID.test(path)) return "world";
  if (path.startsWith("/needs-you")) return "needs";
  if (path.startsWith("/library")) return "library";
  return "more";
}

// biome-ignore format: one line per item.
const ITEMS: ReadonlyArray<{ section: Section; label: string; screen: string | null; desktopOnly?: true }> = [
  { section: "home", label: "Home", screen: "S-01", desktopOnly: true },
  { section: "world", label: "World", screen: "S-04" },
  { section: "story", label: "Story", screen: "S-10" },
  { section: "needs", label: "Needs you", screen: "S-06" },
  { section: "library", label: "Library", screen: "S-13" },
  { section: "more", label: "More", screen: null },
];

/** The screens the tabs themselves open; /more lists the rest. */
export const TAB_SCREEN_IDS: ReadonlySet<string> = new Set(
  ITEMS.flatMap((i) => (i.screen ? [i.screen] : [])),
);

export function PrimaryNav({ id, mobile }: { id: string; mobile: boolean }) {
  const path = usePathname();
  const current = sectionOf(path);
  const inWorld = WORLD_ID.exec(path)?.[1];
  return (
    <nav className={id} data-testid={id} aria-label="Primary">
      {ITEMS.filter((i) => !(mobile && i.desktopOnly)).map((i) => {
        const base = (i.screen && screenMeta(i.screen)?.path) || "/more";
        const to = inWorld ? base.replace(WORLD_ID, `/world/${inWorld}`) : base;
        return (
          <AppLink
            key={i.section}
            to={to}
            className="nav-btn"
            {...(current === i.section ? { "aria-current": "page" as const } : {})}
          >
            {i.label}
          </AppLink>
        );
      })}
    </nav>
  );
}
