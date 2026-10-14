import { useClient, useIsFixtureClient, useWorldKnown } from "../api/ClientProvider";
import { FIXTURE_WORLD_ID } from "../api/fixtures/derived";
// PRD 18.3 primary navigation: the desktop left rail and the mobile bottom tabs (World, Story,
// Needs you, Library, More). Every other screen is reached from More. Real links only: each one
// goes to a built screen or to a "Coming soon" screen, never to a dead click. The last item is the
// Ask Tilo button, which opens the assistant panel.
import { AssistantLauncher } from "../assistant/AssistantLauncher";
import { deriveQueue } from "../needs-you/queue";
import { stagePath, usePathname } from "../router";
import { useRunLog } from "../world/runLog";
import { useAddressedWorld, withWorld } from "../world/worldContext";
import { AppLink } from "./AppLink";
import { NavIcon } from "./NavIcon";
import { screenMeta } from "./meta";

type Section = "home" | "world" | "story" | "needs" | "library" | "more";

const WORLD_ID = /^\/world\/([^/]+)/;
/** Which primary item a path belongs to; anything not claimed by another item is More. */
export function sectionOf(path: string): Section {
  if (path === "/" || path.startsWith("/task/")) return "home";
  if (/^\/world\/[^/]+\/(story|trace)\/?$/.test(path)) return "story";
  // /world/:id/stage (S-04); /worlds and anything under it is the Park Worlds page
  if (WORLD_ID.test(path) || path === "/worlds" || path.startsWith("/worlds/")) return "world";
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

/** The Needs-you count: the queue S-06 lists, from this world's recorded events (HR-1). Nothing
 * shows at zero; the hidden words give the count to assistive technology. */
function NeedsBadge({ worldId }: { worldId: string }) {
  const waiting = deriveQueue(useRunLog(useClient(), worldId)).length;
  return waiting > 0 ? (
    <span className="nav-badge" data-testid="nav-needs-badge">
      {waiting}
      <span className="visually-hidden"> waiting</span>
    </span>
  ) : null;
}

/** The world whose Needs-you queue is counted: the addressed one, else the fixture world (fixture
 * client only: a real client is never asked about a world nobody named); null when it is unknown. */
export function useCountedWorld(): string | null {
  const fixtureClient = useIsFixtureClient();
  const countWorld = useAddressedWorld() ?? (fixtureClient ? FIXTURE_WORLD_ID : null);
  return useWorldKnown(countWorld) ? countWorld : null;
}

export function PrimaryNav({ id, mobile }: { id: string; mobile: boolean }) {
  const path = usePathname();
  const current = sectionOf(path);
  // The world of the path, else of `?world=` (the Needs-you screens): its links keep that world.
  const inWorld = useAddressedWorld();
  const counted = useCountedWorld();
  return (
    <nav className={id} data-testid={id} aria-label="Primary">
      {ITEMS.filter((i) => !(mobile && i.desktopOnly)).map((i) => {
        const base = (i.screen && screenMeta(i.screen)?.path) || "/more";
        const to = !inWorld
          ? base
          : i.section === "needs"
            ? withWorld(base, inWorld)
            : i.section === "world"
              ? stagePath(inWorld)
              : base.replace(WORLD_ID, stagePath(inWorld).replace(/\/stage$/, ""));
        return (
          <AppLink
            key={i.section}
            to={to}
            className="nav-btn"
            {...(current === i.section ? { "aria-current": "page" as const } : {})}
          >
            {/* The label comes first in the source, so the link's name starts with it; the column is
                reversed, so the icon shows above it. */}
            <span className="nav-label">{i.label}</span>
            <span className="nav-icon-box">
              <NavIcon name={i.section} />
              {i.section === "needs" && counted && <NeedsBadge worldId={counted} />}
            </span>
          </AppLink>
        );
      })}
      {/* Ask Tilo (FR-PA-12) is the last item: a button that opens the panel, in the flow, so it
          never covers a control. */}
      <AssistantLauncher />
    </nav>
  );
}
