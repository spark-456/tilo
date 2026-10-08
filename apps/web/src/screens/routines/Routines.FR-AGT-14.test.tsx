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
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../../api/ClientProvider";
import { HttpClient } from "../../api/http";
import { PRESS_MS } from "../remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "https://api.test";

let container: HTMLElement;
let root: Root;
let Routines: () => React.JSX.Element;
const q = <T extends Element = HTMLElement>(s: string, from: ParentNode = container) =>
  from.querySelector<T>(s);
const settle = (ms = PRESS_MS + 60) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const view = (over: Record<string, unknown> = {}) => ({
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
const A = view();
const B = view({
  schedule_id: "sched_b2",
  title: "Friday digest",
  cadence: { weekday: 4, hour: 17, minute: 30, tz: "Europe/London" },
  enabled: false,
  next_due: "2026-10-16T16:30:00Z",
});

type Call = { method: string; path: string; body: unknown };
type Reply = Response | ((call: Call) => Response);

async function open(routes: Record<string, Reply>) {
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

const row = (id: string) => q(`[data-testid="routine-row-${id}"]`);
const rows = () => [...container.querySelectorAll('[data-testid^="routine-row-"]')];
const buttonIn = (from: ParentNode | null, text: string) =>
  [...(from?.querySelectorAll("button") ?? [])].find((b) => b.textContent?.trim() === text);
const click = async (b: Element | undefined) => {
  await act(async () => (b as HTMLButtonElement | undefined)?.click());
  await settle();
};

beforeAll(async () => {
  ({ Routines } = (await import("./Routines")) as { Routines: () => React.JSX.Element });
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

describe("FR-AGT-14 Routines list", () => {
  it("FR-AGT-14 Routines: GETs /schedules once on mount and shows title, cadence in words and next run", async () => {
    const { calls } = await open({ "GET /schedules": json({ schedules: [A, B] }) });
    expect(calls.filter((c) => c.method === "GET" && c.path === "/schedules")).toHaveLength(1);
    expect(calls.filter((c) => c.method !== "GET")).toHaveLength(0); // reading writes nothing
    expect(rows()).toHaveLength(2);

    const a = row("sched_a1")?.textContent ?? "";
    expect(a).toContain("Weekly competitor scan");
    expect(a).toContain("Every Monday at 09:00");
    expect(a).toContain("Asia/Kolkata");
    expect(a).toMatch(/Next run/);
    expect(a).toMatch(/\b12\b/); // 12 Oct 2026 in the schedule's own zone
    expect(a).toMatch(/Oct/);
    expect(a).not.toMatch(/Paused/);
    expect(buttonIn(row("sched_a1"), "Pause")).toBeDefined();

    const b = row("sched_b2")?.textContent ?? "";
    expect(b).toContain("Friday digest");
    expect(b).toContain("Every Friday at 17:30");
    expect(b).toContain("Europe/London");
  });

  it("FR-AGT-14 Routines: a paused routine says Paused and offers Resume, not Pause", async () => {
    await open({ "GET /schedules": json({ schedules: [B] }) });
    const b = row("sched_b2");
    expect(b?.textContent).toMatch(/Paused/);
    expect(buttonIn(b ?? null, "Resume")).toBeDefined();
    expect(buttonIn(b ?? null, "Pause")).toBeUndefined();
  });

  it("FR-AGT-14 Routines: an empty list shows a plain empty state and no rows", async () => {
    await open({ "GET /schedules": json({ schedules: [] }) });
    expect(rows()).toHaveLength(0);
    expect(container.textContent).toContain("No routines yet.");
  });

  it("FR-AGT-14 Routines: Pause sends PATCH {enabled:false} and the row then says Paused with Resume", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [A] }),
      "PATCH /schedules/sched_a1": json(view({ enabled: false })),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Pause"));
    const patches = calls.filter((c) => c.method === "PATCH");
    expect(patches).toHaveLength(1);
    expect(patches[0]?.path).toBe("/schedules/sched_a1");
    expect(patches[0]?.body).toEqual({ enabled: false });
    const a = row("sched_a1");
    expect(a?.textContent).toMatch(/Paused/);
    expect(buttonIn(a ?? null, "Resume")).toBeDefined();
  });

  it("FR-AGT-14 Routines: Resume sends PATCH {enabled:true} and the row is live again", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [B] }),
      "PATCH /schedules/sched_b2": json({ ...B, enabled: true }),
    });
    await click(buttonIn(row("sched_b2") ?? null, "Resume"));
    const patches = calls.filter((c) => c.method === "PATCH");
    expect(patches).toHaveLength(1);
    expect(patches[0]?.body).toEqual({ enabled: true });
    expect(row("sched_b2")?.textContent).not.toMatch(/Paused/);
    expect(buttonIn(row("sched_b2") ?? null, "Pause")).toBeDefined();
  });

  it("FR-AGT-14 Routines: Delete asks first and sends nothing until confirmed; Keep leaves the row", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [A] }),
      "DELETE /schedules/sched_a1": new Response(null, { status: 204 }),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Delete"));
    expect(container.textContent).toMatch(/delete/i);
    expect(buttonIn(container, "Delete routine")).toBeDefined();
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);

    await click(buttonIn(container, "Keep routine"));
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
    expect(row("sched_a1")).not.toBeNull();
    expect(buttonIn(container, "Delete routine")).toBeUndefined();
  });

  it("FR-AGT-14 Routines: confirming Delete sends DELETE once and removes the row; the last one leaves the empty state", async () => {
    const { calls } = await open({
      "GET /schedules": json({ schedules: [A, B] }),
      "DELETE /schedules/sched_a1": new Response(null, { status: 204 }),
      "DELETE /schedules/sched_b2": new Response(null, { status: 204 }),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Delete"));
    await click(buttonIn(container, "Delete routine"));
    const deletes = calls.filter((c) => c.method === "DELETE");
    expect(deletes).toHaveLength(1);
    expect(deletes[0]?.path).toBe("/schedules/sched_a1");
    expect(row("sched_a1")).toBeNull();
    expect(row("sched_b2")).not.toBeNull();

    await click(buttonIn(row("sched_b2") ?? null, "Delete"));
    await click(buttonIn(container, "Delete routine"));
    expect(rows()).toHaveLength(0);
    expect(container.textContent).toContain("No routines yet.");
  });

  it("FR-AGT-14 Routines: a replay-only refusal on Pause shows the replay message, keeps the row, and does not crash", async () => {
    await open({
      "GET /schedules": json({ schedules: [A] }),
      "PATCH /schedules/sched_a1": json(
        { replay_only: true, detail: "This link is replay-only right now." },
        503,
      ),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Pause"));
    expect(q('[role="alert"]')?.textContent).toContain("Finished runs can still be replayed.");
    expect(row("sched_a1")).not.toBeNull();
    expect(row("sched_a1")?.textContent).not.toMatch(/Paused/); // nothing changed
  });

  it("FR-AGT-14 Routines: a replay-only refusal on Delete shows the replay message and keeps the row", async () => {
    await open({
      "GET /schedules": json({ schedules: [A] }),
      "DELETE /schedules/sched_a1": json({ replay_only: true, detail: "replay-only" }, 503),
    });
    await click(buttonIn(row("sched_a1") ?? null, "Delete"));
    await click(buttonIn(container, "Delete routine"));
    expect(q('[role="alert"]')?.textContent).toContain("Finished runs can still be replayed.");
    expect(row("sched_a1")).not.toBeNull();
  });

  it("FR-AGT-14 Routines: a failed list load says so in words with a retry, never an unhandled rejection", async () => {
    const { calls } = await open({ "GET /schedules": json({ detail: "Forbidden" }, 403) });
    expect(q('[role="alert"]')).not.toBeNull();
    expect(rows()).toHaveLength(0);
    const retry = buttonIn(container, "Try again");
    expect(retry).toBeDefined();
    await click(retry);
    expect(calls.filter((c) => c.method === "GET" && c.path === "/schedules")).toHaveLength(2);
  });
});
