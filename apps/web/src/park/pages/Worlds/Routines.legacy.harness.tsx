// @vitest-environment happy-dom
// FR-AGT-14 (PRD 8, "Scheduled runs (Clock Tower)": a weekly schedule fires on time and reuses
// memory), Routines list side. `./Routines` exports `Routines` (no props): it reads the client from
// ClientProvider (an HttpClient), GETs /schedules on mount and lists each routine with its title,
// cadence in words, next run and paused state. Pause / Resume sends PATCH {enabled}, Delete asks for
// confirmation and then sends DELETE. Fetch is mocked at the http layer; no network.
//
// Resolved ambiguities (PRD gives no UI detail):
//  - The cadence reads "Every Monday at 09:00 (Asia/Kolkata)"; weekday 0 is Monday (Cadence in
//    services/harness schedule.py). The next run is shown beside the words "Next run".
//  - Row buttons are "Pause" / "Resume" / "Delete". Delete opens an in-page confirmation (role
//    alertdialog, or any element whose text asks to delete) with the buttons "Delete routine" and
//    "Keep routine"; nothing is sent until "Delete routine".
//  - Empty list: the plain sentence "No routines yet." and no row.
//  - The replay-only message is NFR-22's: a 503 with replay_only: true reads "Live models are
//    unavailable right now, so nothing new was started. Finished runs can still be replayed." This
//    needs NFR-22's http.ts change (origin/feat/NFR-22-web) in the base.
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, vi } from "vitest";
import { ClientProvider } from "../../../api/ClientProvider";
import { HttpClient } from "../../../api/http";
import { PRESS_MS } from "../../../screens/remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "https://api.test";

export let container: HTMLElement;
let root: Root;
let Routines: () => React.JSX.Element;
export const q = <T extends Element = HTMLElement>(s: string, from: ParentNode = container) =>
  from.querySelector<T>(s);
export const settle = (ms = PRESS_MS + 60) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

export const view = (over: Record<string, unknown> = {}) => ({
  schedule_id: "sched_a1",
  title: "Weekly competitor scan",
  cadence: { weekday: 0, hour: 9, minute: 0, tz: "Asia/Kolkata" },
  enabled: true,
  next_due: "2026-10-12T03:30:00Z", // Monday 12 Oct 2026, 09:00 in Asia/Kolkata
  budget_cap: 130,
  last_world_id: null,
  last_slot: null,
  failures: 0,
  last_error: null,
  approved_brief_ref: "w_approved",
  created_at: "2026-10-07T04:00:00Z",
  ...over,
});
export const A = view();
export const B = view({
  schedule_id: "sched_b2",
  title: "Friday digest",
  cadence: { weekday: 4, hour: 17, minute: 30, tz: "Europe/London" },
  enabled: false,
  next_due: "2026-10-16T16:30:00Z",
});

type Call = { method: string; path: string; body: unknown };
type Reply = Response | ((call: Call) => Response | Promise<Response>);

export async function open(routes: Record<string, Reply>) {
  const calls: Call[] = [];
  const fetchFake = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    const call: Call = {
      method: init?.method ?? "GET",
      path,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    const hit = routes[`${call.method} ${path}`];
    if (!hit) return json({ detail: "Not Found" }, 404);
    return typeof hit === "function" ? hit(call) : hit.clone();
  });
  const client = new HttpClient({ baseUrl: BASE, fetch: fetchFake as unknown as typeof fetch });
  await act(async () => {
    root.render(
      <ClientProvider client={client}>
        <Routines />
      </ClientProvider>,
    );
  });
  await settle();
  return { calls };
}

export const row = (id: string) => q(`[data-testid="routine-row-${id}"]`);
export const rows = () => [...container.querySelectorAll('[data-testid^="routine-row-"]')];
export const buttonIn = (from: ParentNode | null, text: string) =>
  [...(from?.querySelectorAll("button") ?? [])].find((b) => b.textContent?.trim() === text);
export const click = async (b: Element | undefined) => {
  await act(async () => (b as HTMLButtonElement | undefined)?.click());
  await settle();
};

beforeAll(async () => {
  ({ Routines } = (await import("./Routines")) as {
    Routines: () => React.JSX.Element;
  });
});
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});
