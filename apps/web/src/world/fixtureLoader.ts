// P1: fixture mode loads a layout + event stream by name. `village-basic` is imported straight
// from contracts/ (not copied); every other name is served from apps/web/fixtures/<name>.*.
// `new URL(<literal>, import.meta.url)` is Vite's static-asset-URL form; both paths are real
// network fetches (world-honesty.spec.ts delays them with page.route).
import type { Event, Layout } from "@tilo/contracts";

export interface LoadedFixture {
  readonly layout: Layout;
  readonly events: readonly Event[];
}

const VILLAGE_BASIC_LAYOUT_URL = new URL(
  "../../../../contracts/fixtures/layout/valid/village_basic.json",
  import.meta.url,
);
const VILLAGE_BASIC_EVENTS_URL = new URL(
  "../../../../contracts/fixtures/streams/village-basic.jsonl",
  import.meta.url,
);

function urlsFor(name: string): { layoutUrl: string | URL; eventsUrl: string | URL } {
  if (name === "village-basic") {
    return { layoutUrl: VILLAGE_BASIC_LAYOUT_URL, eventsUrl: VILLAGE_BASIC_EVENTS_URL };
  }
  return {
    layoutUrl: `/fixtures/${name}.layout.json`,
    eventsUrl: `/fixtures/${name}.events.jsonl`,
  };
}

function parseJsonl(text: string): Event[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as Event);
}

// Vite's SPA fallback answers a missing file with index.html and status 200, so an HTML body is
// treated as "not found" too; the caller shows an in-app alert instead of logging (P0-08b).
function isFound(res: Response): boolean {
  return res.ok && !(res.headers.get("content-type") ?? "").includes("text/html");
}

export async function loadFixture(name: string): Promise<LoadedFixture> {
  const { layoutUrl, eventsUrl } = urlsFor(name);
  const [layoutRes, eventsRes] = await Promise.all([fetch(layoutUrl), fetch(eventsUrl)]);
  if (!isFound(layoutRes) || !isFound(eventsRes)) {
    throw new Error(
      `fixture "${name}": failed to load (layout ${layoutRes.status}, events ${eventsRes.status})`,
    );
  }
  const [layout, eventsText] = await Promise.all([layoutRes.json(), eventsRes.text()]);
  return { layout: layout as Layout, events: parseJsonl(eventsText) };
}
