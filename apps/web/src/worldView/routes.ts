// OLD-UI-OUT-2: the addresses of a world's lenses and of the Needs-you page. They are pages of the Park app (the
// Park shell frames them); this module is the pure address table, dependency-free so Root.tsx can read it without
// loading either app (NFR-01).
//   /world/:id/stage|story|trace|delivery   the live stage and its lenses, and the delivery
//   /world/:id/inspect/:item                one object of the world
//   /needs-you, /needs-you/gate, /needs-you/consent   the queue, one gate, one connection request
// A bare `/world/:id` stays the Park World overview (park/app/router.ts).

export type Lens = "stage" | "story" | "trace" | "delivery";
export type NeedsSheet = "queue" | "gate" | "consent";

export type ViewRoute =
  | { readonly kind: "lens"; readonly worldId: string; readonly lens: Lens }
  | { readonly kind: "inspect"; readonly worldId: string; readonly itemId: string }
  | { readonly kind: "needs"; readonly sheet: NeedsSheet };

const LENS = /^\/world\/([^/]+)\/(stage|story|trace|delivery)\/?$/;
const INSPECT = /^\/world\/([^/]+)\/inspect\/([^/]+)\/?$/;
const NEEDS = /^\/needs-you(?:\/(gate|consent))?\/?$/;

function decode(raw: string | undefined): string | null {
  if (raw === undefined) return null;
  try {
    const value = decodeURIComponent(raw);
    return value === "" ? null : value;
  } catch {
    return null; // a malformed escape such as %E0 names nothing
  }
}

/** The view an address belongs to, or null when it is none of these. */
export function parseViewPath(pathname: string): ViewRoute | null {
  const lens = LENS.exec(pathname);
  if (lens) {
    const worldId = decode(lens[1]);
    return worldId === null ? null : { kind: "lens", worldId, lens: lens[2] as Lens };
  }
  const inspect = INSPECT.exec(pathname);
  if (inspect) {
    const worldId = decode(inspect[1]);
    const itemId = decode(inspect[2]);
    return worldId === null || itemId === null ? null : { kind: "inspect", worldId, itemId };
  }
  const needs = NEEDS.exec(pathname);
  if (needs) return { kind: "needs", sheet: (needs[1] as NeedsSheet | undefined) ?? "queue" };
  return null;
}

const enc = encodeURIComponent;
export const lensPath = (worldId: string, lens: Lens): string => `/world/${enc(worldId)}/${lens}`;
export const inspectPath = (worldId: string, itemId: string): string =>
  `/world/${enc(worldId)}/inspect/${enc(itemId)}`;
export const overviewPath = (worldId: string): string => `/world/${enc(worldId)}`;

/** The page title of a view, as the shell writes it ("Story · Tilo"). */
export function viewTitle(route: ViewRoute): string {
  if (route.kind === "needs") {
    return route.sheet === "gate"
      ? "Approval gate"
      : route.sheet === "consent"
        ? "Connection consent"
        : "Needs you";
  }
  if (route.kind === "inspect") return "Inspect";
  return { stage: "World", story: "Story", trace: "Trace", delivery: "Delivery" }[route.lens];
}
