// The live Api (WEB-1a, WIRE-1, WIRE-2): `getLedger` reads `GET {base}/costs`, `getWorlds` walks `GET {base}/worlds`
// pages; every other method is NotBuilt and
// fetches nothing. With no base url nothing is fetched at all. It never imports the fixtures, so sample
// numbers cannot pass as live (HR-1..HR-7). Failures are the shared `TiloApiError` (src/api/http.ts).
import { HttpClient, TiloApiError } from "../../api/http";
import { API_METHODS, type Api, type ApiMethod } from "./index";
import { type CostReport, ledgerFromCosts } from "./live/ledgerFromCosts";
import { STATE_OF, type WorldListItem, worldsFromList } from "./live/worldsFromList";

export class NotBuilt extends Error {
  readonly code = "not_built";
  constructor(method: ApiMethod) {
    super(`${method} is not connected yet`);
    this.name = "NotBuilt";
  }
}

export interface LiveApiOptions {
  /** The API origin; trailing slashes are trimmed. Without it, every method is NotBuilt. */
  baseUrl?: string;
  fetch?: typeof fetch;
}

const BAD_REPLY = "Tilo sent a reply this page could not read.";

const isRows = (v: unknown): boolean =>
  Array.isArray(v) && v.every((r) => typeof r?.usd === "number");

/** A body that is not a cost report is an unreadable reply, never a Ledger. */
function isCostReport(v: unknown): v is CostReport {
  const r = v as Partial<Record<keyof CostReport, unknown>> | null;
  const totals = r?.totals as { usd?: unknown } | null | undefined;
  return (
    typeof totals === "object" &&
    totals !== null &&
    typeof totals.usd === "number" &&
    isRows(r?.by_profile) &&
    isRows(r?.by_task_type)
  );
}

/** At most 1,000 worlds, the newest (BQ-WIRE2-5): a server that never ends the walk cannot hang the page. */
const MAX_PAGES = 10;

const isItem = (v: unknown): v is WorldListItem => {
  const i = v as Partial<Record<keyof WorldListItem, unknown>> | null;
  return (
    typeof i === "object" &&
    i !== null &&
    typeof i.world_id === "string" &&
    typeof i.status === "string" &&
    Object.hasOwn(STATE_OF, i.status) &&
    (i.title === null || typeof i.title === "string") &&
    (i.created_at === null || typeof i.created_at === "string")
  );
};

/** A body that is not a world list page is an unreadable reply, never worlds (an unknown status too, HR-5). */
function isWorldPage(v: unknown): v is { worlds: WorldListItem[]; next_cursor: string | null } {
  const p = v as { worlds?: unknown; next_cursor?: unknown } | null;
  return (
    typeof p === "object" &&
    p !== null &&
    Array.isArray(p.worlds) &&
    p.worlds.every(isItem) &&
    (p.next_cursor === null || typeof p.next_cursor === "string")
  );
}

export function createLiveApi(options: LiveApiOptions = {}): Api {
  const stubs = API_METHODS.map((m) => [m, () => Promise.reject(new NotBuilt(m))]);
  const api = Object.fromEntries(stubs) as unknown as Api;
  const baseUrl = options.baseUrl?.trim();
  if (!baseUrl) return api;
  const http = new HttpClient({
    baseUrl,
    ...(options.fetch ? { fetch: options.fetch } : {}),
  });
  api.getLedger = async () => {
    const report = await http.getJson("/costs");
    if (!isCostReport(report)) throw new TiloApiError(BAD_REPLY, 200, true);
    return { data: ledgerFromCosts(report), source: "live" };
  };
  api.getWorlds = async (_dec, added) => {
    const items: WorldListItem[] = [];
    let cursor: string | null = null;
    for (let n = 0; n < MAX_PAGES && (n === 0 || cursor !== null); n++) {
      const query = cursor === null ? "" : `&cursor=${encodeURIComponent(cursor)}`;
      const body = await http.getJson(`/worlds?limit=100${query}`);
      if (!isWorldPage(body)) throw new TiloApiError(BAD_REPLY, 200, true);
      items.push(...body.worlds);
      cursor = body.next_cursor;
    }
    const live = worldsFromList(items);
    const liveIds = new Set(live.map((w) => w.id));
    return { data: [...added.filter((w) => !liveIds.has(w.id)), ...live], source: "live" };
  };
  return api;
}
