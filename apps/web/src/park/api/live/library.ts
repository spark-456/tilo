// OLD-UI-OUT wave 3: what Tilo has delivered, read from the API's own records (nothing is "finished" before its
// event, HR-1). One page of the person's worlds (`GET /worlds`), then `GET /worlds/{id}/delivery` of each completed
// one (the API answers 409 until `world.completed`, so only completed worlds are asked). A world whose delivery
// cannot be read is counted, never invented; a reply of the wrong shape is an unreadable reply, never rows.
import { type HttpClient, TiloApiError } from "../../../api/http";

export interface LibraryItem {
  worldId: string;
  worldTitle: string;
  artifactId: string;
  title: string;
  kind: string;
  version: number;
}

export interface Library {
  items: LibraryItem[];
  /** Completed worlds whose delivery could not be read just now. */
  unreadable: number;
  /** More completed worlds exist than this view reads. */
  truncated: boolean;
  credits: number;
}

/** How many completed worlds one visit reads: one request each, so the page stays quick and bounded. */
export const MAX_WORLDS = 12;

const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const bad = () =>
  new TiloApiError("Tilo sent a Library reply this page could not read.", 200, true);

interface WorldRow {
  id: string;
  title: string;
}

function completedWorlds(v: unknown): { rows: WorldRow[]; more: boolean } {
  if (!object(v) || !Array.isArray(v.worlds)) throw bad();
  const all: WorldRow[] = [];
  for (const w of v.worlds) {
    if (!object(w) || typeof w.world_id !== "string" || typeof w.status !== "string") throw bad();
    if (w.status !== "completed" || w.sample === true) continue;
    all.push({
      id: w.world_id,
      title: typeof w.title === "string" && w.title ? w.title : "Untitled world",
    });
  }
  return {
    rows: all.slice(0, MAX_WORLDS),
    more: all.length > MAX_WORLDS || typeof v.next_cursor === "string",
  };
}

function deliveredOf(v: unknown, world: WorldRow): { items: LibraryItem[]; credits: number } {
  if (!object(v) || !Array.isArray(v.artifacts)) throw bad();
  const items = v.artifacts.map((a): LibraryItem => {
    if (
      !object(a) ||
      typeof a.id !== "string" ||
      typeof a.title !== "string" ||
      typeof a.kind !== "string" ||
      typeof a.version !== "number"
    )
      throw bad();
    return {
      worldId: world.id,
      worldTitle: world.title,
      artifactId: a.id,
      title: a.title,
      kind: a.kind,
      version: a.version,
    };
  });
  return { items, credits: typeof v.credits_used === "number" ? v.credits_used : 0 };
}

export function libraryApi(http: Pick<HttpClient, "getJson">) {
  return {
    async getLibrary(): Promise<Library> {
      const { rows, more } = completedWorlds(await http.getJson("/worlds?limit=100"));
      const read = await Promise.allSettled(
        rows.map(async (w) =>
          deliveredOf(await http.getJson(`/worlds/${encodeURIComponent(w.id)}/delivery`), w),
        ),
      );
      const out: Library = { items: [], unreadable: 0, truncated: more, credits: 0 };
      for (const r of read) {
        if (r.status === "fulfilled") {
          out.items.push(...r.value.items);
          out.credits += r.value.credits;
        } else out.unreadable += 1;
      }
      return out;
    },
  };
}
