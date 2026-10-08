// @vitest-environment happy-dom
// FR-AGT-14 (PRD 8, "Scheduled runs (Clock Tower)": a weekly schedule fires on time and reuses
// memory), S-03 side. An optional "Repeat weekly" control, off by default. When on, after the budget
// grant and start succeed, the web POSTs /schedules with the task, the chosen approach, a title and
// the cadence (weekday 0-6 with Monday = 0, hour, minute, IANA zone prefilled from the browser).
//
// Everything runs through a real HttpClient over a routed fake fetch (the http layer); no network.
// Resolved ambiguities (PRD gives no UI detail):
//  - Defaults when the control is switched on: Monday (0) 09:00, the browser's time zone.
//  - Controls: checkbox [data-testid=repeat-weekly]; weekday <select> [data-testid=repeat-weekday]
//    (option values "0".."6", Monday first); time <input type=time> [data-testid=repeat-time]
//    ("HH:MM"); time zone [data-testid=repeat-tz] (its value or text is the IANA name).
//  - A /schedules refusal after a successful start: the run stays started (approve is not undone), the
//    server's plain sentence is shown, and a link to the started world's stage stays available.
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../../api/ClientProvider";
import { FIXTURE_APPROACHES } from "../../api/fixtures/derived";
import { HttpClient } from "../../api/http";
import { FlowShell } from "../FlowShell";
import { PRESS_MS } from "../remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BASE = "https://api.test";
const ZONE = "Asia/Kolkata";

let container: HTMLElement;
let root: Root;
const q = <T extends Element = HTMLElement>(s: string) => container.querySelector<T>(s);
const settle = (ms = PRESS_MS + 60) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));

function setValue(el: HTMLInputElement | HTMLSelectElement, value: string): void {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement : HTMLInputElement;
  Object.getOwnPropertyDescriptor(proto.prototype, "value")?.set?.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

type Call = { method: string; path: string; body: unknown };
type Reply = Response | ((call: Call) => Response);

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const VIEW = {
  schedule_id: "sched_a1",
  title: "Weekly",
  cadence: { weekday: 0, hour: 9, minute: 0, tz: ZONE },
  enabled: true,
  next_due: "2026-10-12T03:30:00Z",
  budget_cap: 130,
  last_world_id: null,
  last_slot: null,
  failures: 0,
  last_error: null,
  approved_brief_ref: "w_approved",
  created_at: "2026-10-07T04:00:00Z",
};

async function open(schedulesReply: Reply = json(VIEW, 201), approveReply?: Reply) {
  const calls: Call[] = [];
  const fetchFake = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    const call: Call = {
      method: init?.method ?? "GET",
      path,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    if (call.method === "GET" && path === "/tasks/t1/approaches")
      return json({ task_id: "t1", ...FIXTURE_APPROACHES });
    if (call.method === "POST" && path === "/tasks/t1/approve") {
      const r = approveReply ?? json({ world_id: "w_approved" });
      return typeof r === "function" ? r(call) : r.clone();
    }
    if (path.startsWith("/schedules"))
      return typeof schedulesReply === "function" ? schedulesReply(call) : schedulesReply.clone();
    return json({ detail: "Not Found" }, 404);
  });
  const client = new HttpClient({ baseUrl: BASE, fetch: fetchFake as unknown as typeof fetch });
  window.history.pushState({}, "", "/task/t1/approaches");
  await act(async () => {
    root.render(
      <ClientProvider client={client}>
        <FlowShell />
      </ClientProvider>,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await settle(0);
  await settle(0);
  const schedules = () => calls.filter((c) => c.path.startsWith("/schedules"));
  const approves = () => calls.filter((c) => c.path === "/tasks/t1/approve");
  return { calls, schedules, approves };
}

const choose = async (id: string) =>
  act(async () => q<HTMLButtonElement>(`[data-testid="select-approach-${id}"]`)?.click());
const start = async () => {
  await act(async () => q<HTMLButtonElement>("button.primary")?.click());
  await settle();
  await settle();
};
const repeat = () => q<HTMLInputElement>('[data-testid="repeat-weekly"]');
const turnOn = async () => act(async () => repeat()?.click());
const valueIn = (testid: string) => {
  const el = q<HTMLInputElement | HTMLSelectElement>(`[data-testid="${testid}"]`);
  return el ? (el.value !== "" ? el.value : (el.textContent ?? "")) : null;
};

beforeAll(async () => {
  await import("./Approaches");
});
beforeEach(() => {
  const real = Intl.DateTimeFormat.prototype.resolvedOptions;
  vi.spyOn(Intl.DateTimeFormat.prototype, "resolvedOptions").mockImplementation(function (
    this: Intl.DateTimeFormat,
  ) {
    return { ...real.call(this), timeZone: ZONE };
  });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("FR-AGT-14 S-03 Repeat weekly", () => {
  it("FR-AGT-14 S-03: a 'Repeat weekly' checkbox is present and off by default", async () => {
    await open();
    expect(repeat()).not.toBeNull();
    expect(repeat()?.type).toBe("checkbox");
    expect(repeat()?.checked).toBe(false);
    expect(container.textContent).toContain("Repeat weekly");
  });

  it("FR-AGT-14 S-03: switching it on shows weekday, time and the browser time zone prefilled (Monday 09:00)", async () => {
    await open();
    await choose("thorough");
    await turnOn();
    expect(repeat()?.checked).toBe(true);
    expect(valueIn("repeat-weekday")).toBe("0");
    expect(valueIn("repeat-time")).toBe("09:00");
    expect(valueIn("repeat-tz")).toContain(ZONE);
    const days = [...(q("[data-testid=repeat-weekday]")?.querySelectorAll("option") ?? [])];
    expect(days.map((o) => o.getAttribute("value"))).toEqual(["0", "1", "2", "3", "4", "5", "6"]);
    expect(days[0]?.textContent).toBe("Monday");
    expect(days[6]?.textContent).toBe("Sunday");
  });

  it("FR-AGT-14 S-03: repeat weekly posts one schedule after the grant, with the chosen approach, title and cadence", async () => {
    const { calls, schedules, approves } = await open();
    await choose("thorough");
    await turnOn();
    await act(async () => {
      const day = q<HTMLSelectElement>("[data-testid=repeat-weekday]");
      const time = q<HTMLInputElement>("[data-testid=repeat-time]");
      if (day) setValue(day, "4"); // Friday
      if (time) setValue(time, "17:30");
    });
    await start();

    expect(approves()).toHaveLength(1);
    expect(schedules()).toHaveLength(1);
    const post = schedules()[0];
    expect(post?.method).toBe("POST");
    expect(post?.path).toBe("/schedules");
    const body = post?.body as {
      task_id: string;
      approach_id: string;
      title: string;
      cadence: unknown;
    };
    expect(body.task_id).toBe("t1");
    expect(body.approach_id).toBe("thorough");
    expect(body.cadence).toEqual({ weekday: 4, hour: 17, minute: 30, tz: ZONE });
    // The API accepts a title of 1..140 characters with no control characters.
    expect(typeof body.title).toBe("string");
    expect(body.title.length).toBeGreaterThanOrEqual(1);
    expect(body.title.length).toBeLessThanOrEqual(140);
    // biome-ignore lint/suspicious/noControlCharactersInRegex: the test checks for exactly these
    expect(/[\u0000-\u001f\u007f-\u009f]/.test(body.title)).toBe(false);
    expect(Object.keys(body).sort()).toEqual(["approach_id", "cadence", "task_id", "title"]);
    // The grant comes first: the schedule is created only once the budget is approved.
    expect(calls.findIndex((c) => c.path === "/tasks/t1/approve")).toBeLessThan(
      calls.findIndex((c) => c.path === "/schedules"),
    );
    expect(window.location.pathname).toBe("/world/w_approved/stage");
  });

  it("FR-AGT-14 S-03: the defaults post Monday 09:00 in the browser zone when the person changes nothing", async () => {
    const { schedules } = await open();
    await choose("quick");
    await turnOn();
    await start();
    expect(schedules()).toHaveLength(1);
    expect((schedules()[0]?.body as { cadence: unknown }).cadence).toEqual({
      weekday: 0,
      hour: 9,
      minute: 0,
      tz: ZONE,
    });
    expect((schedules()[0]?.body as { approach_id: string }).approach_id).toBe("quick");
  });

  it("FR-AGT-14 S-03: off by default posts no /schedules call", async () => {
    const { schedules, approves } = await open();
    await choose("thorough");
    await start();
    expect(approves()).toHaveLength(1);
    expect(schedules()).toHaveLength(0);
  });

  it("FR-AGT-14 S-03: switched on then off again posts no /schedules call", async () => {
    const { schedules, approves } = await open();
    await choose("thorough");
    await turnOn();
    await turnOn();
    expect(repeat()?.checked).toBe(false);
    await start();
    expect(approves()).toHaveLength(1);
    expect(schedules()).toHaveLength(0);
  });

  it("FR-AGT-14 S-03: a 409 from /schedules shows its plain sentence and does not undo the started run", async () => {
    const said = "Approve this task's budget first.";
    const { calls, schedules, approves } = await open(json({ detail: said }, 409));
    await choose("thorough");
    await turnOn();
    await start();

    expect(schedules()).toHaveLength(1);
    expect(approves()).toHaveLength(1); // not repeated, not rolled back
    expect(calls.filter((c) => c.method === "DELETE")).toHaveLength(0);
    expect(container.textContent).toContain(said);
    // The run did start: nothing claims otherwise, and the person can still open it.
    expect(container.textContent).not.toContain("Nothing was changed");
    expect(q('a[href="/world/w_approved/stage"]')).not.toBeNull();
  });

  it("FR-AGT-14 S-03: a 422 from /schedules (bad zone) shows its plain sentence and leaves the run started", async () => {
    const said = "Pick a weekday, a time and a time zone that exists.";
    const { schedules, approves } = await open(json({ detail: said }, 422));
    await choose("thorough");
    await turnOn();
    await start();
    expect(schedules()).toHaveLength(1);
    expect(approves()).toHaveLength(1);
    expect(container.textContent).toContain(said);
    expect(container.textContent).not.toContain("Nothing was changed");
    expect(q('a[href="/world/w_approved/stage"]')).not.toBeNull();
  });

  it("FR-AGT-14 S-03: if the start itself fails, no schedule is posted", async () => {
    const { schedules, approves } = await open(
      json(VIEW, 201),
      json({ detail: "Pick one of the approaches this task was offered." }, 422),
    );
    await choose("thorough");
    await turnOn();
    await start();
    expect(approves()).toHaveLength(1);
    expect(schedules()).toHaveLength(0);
    expect(window.location.pathname).toBe("/task/t1/approaches");
  });
});
