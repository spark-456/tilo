// The live Api (WEB-1a, WIRE-1): `getLedger` reads `GET {base}/costs`; every other method is NotBuilt and
// fetches nothing. With no base url nothing is fetched at all. It never imports the fixtures, so sample
// numbers cannot pass as live (HR-1..HR-7). Failures are the shared `TiloApiError` (src/api/http.ts).
import { HttpClient, TiloApiError } from "../../api/http";
import { API_METHODS, type Api, type ApiMethod } from "./index";
import { type CostReport, ledgerFromCosts } from "./live/ledgerFromCosts";

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
  return api;
}
