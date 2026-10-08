// @vitest-environment happy-dom
// FR-UX-11 live wiring (docs/prd-supplement-design-2026-10-06.md row FR-UX-11): on the live Api the popover is honest
// (HR-1..HR-7, PRD 9.4). The live Api has no notifications route yet, so the popover says "Not connected yet" and never
// shows sample notifications; a notification from a live source opens its world, Connectors or Settings; "You approved"
// appears only after the server recorded the answer; the bell's dot counts the decisions the Api served, not the sample.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { liveApi, mountApp, seen, settle } from "../../../test-support/park/shellHarness";
import { TiloApiError } from "../../api/http";
import { NotBuilt } from "../api/liveApi";
import type { ApiResult, DecideAck, Decision, Notification } from "../api/types";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const bell = () => q<HTMLButtonElement>(document.body, 'button[aria-label="Notifications"]');
const unreadDots = () => [...bell().children].filter((c) => c.tagName.toLowerCase() !== "svg");
const dialog = () => q<HTMLElement>(document.body, '[role="dialog"][aria-label="Notifications"]');
const rows = () => qa<HTMLButtonElement>(dialog(), "button[data-kind]");
const rowWith = (text: string) =>
  rows().find((r) => (r.textContent ?? "").includes(text)) as HTMLButtonElement;

const decision = (k: Decision["k"], approvedTitle = ""): Decision => ({
  k,
  world: "w-live",
  title: `Card ${k}`,
  body: "Why it matters",
  yes: "Approve",
  icon: "",
  done: "",
  toast: "",
  approvedTitle,
});

const note = (id: string, over: Partial<Notification>): Notification => ({
  id,
  t: "09:00",
  title: `Live item ${id}`,
  sub: "From the service",
  kind: "needs",
  go: ["world", "w-live"],
  ...over,
});

/** The live Api (every result marked live) with the notifications read replaced. */
function withNotifications(
  list: Promise<Notification[]> | (() => Promise<Notification[]>),
  decisions: Decision[] = [decision("depot"), decision("mail")],
) {
  const api = liveApi(fakeApi());
  api.getDecisions = () => Promise.resolve({ data: decisions, source: "live" });
  api.getNotifications = async () => ({
    data: await (typeof list === "function" ? list() : list),
    source: "live",
  });
  return api;
}

describe("FR_UX_11 live: the popover is honest", () => {
  it("test_FR_UX_11_live_without_a_notifications_route_says_Not_connected_yet_and_shows_no_sample", async () => {
    const api = liveApi(fakeApi());
    api.getNotifications = () => Promise.reject(new NotBuilt("getNotifications"));
    await mountApp({ api });
    click(bell());
    expect(dialog().textContent).toContain("Not connected yet");
    expect(rows()).toHaveLength(0);
    for (const sample of ["Laptop Depot", "Supplier brief", "Competitor pricing", "HubSpot"]) {
      expect(document.body.textContent).not.toContain(sample);
    }
    // Settings stays reachable
    const settings = qa<HTMLButtonElement>(dialog(), "button").find(
      (b) => b.textContent === "Settings",
    ) as HTMLButtonElement;
    click(settings);
    expect(seen.store.getState().menu).toBeNull();
  });

  it("test_FR_UX_11_live_a_failed_read_says_it_could_not_load_not_Not_connected", async () => {
    const api = liveApi(fakeApi());
    api.getNotifications = () => Promise.reject(new TiloApiError("down", 503, true));
    await mountApp({ api });
    click(bell());
    expect(dialog().textContent).toContain("Notifications could not load");
    expect(dialog().textContent).not.toContain("Not connected yet");
    expect(rows()).toHaveLength(0);
  });

  it("test_FR_UX_11_fixture_notifications_never_get_the_not_connected_line", async () => {
    await mountApp();
    click(bell());
    expect(dialog().textContent).not.toContain("Not connected yet");
    expect(rows()).toHaveLength(5);
  });
});

describe("FR_UX_11 live: each notification opens its world, Connectors or Settings", () => {
  it("test_FR_UX_11_live_sourced_items_open_their_world_through_the_loader_Connectors_and_Settings", async () => {
    const list = [
      note("a", { go: ["world", "w-live"] }),
      note("b", { kind: "warn", title: "Sign-in expires", go: ["connectors"] }),
    ];
    const { navigate, sch } = await mountApp({ api: withNotifications(Promise.resolve(list)) });
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: true });

    click(bell());
    click(rowWith("Live item a"));
    expect(dialog).toThrow(); // closed
    // A world the Api does not know as a sample goes straight to its page (the loader only wraps known worlds)
    expect(navigate).toHaveBeenCalledWith("/world/w-live");

    click(bell());
    click(rowWith("Sign-in expires"));
    expect(navigate).toHaveBeenCalledWith("/connectors");
    expect(sch.live()).toHaveLength(0);

    click(bell());
    click(
      qa<HTMLButtonElement>(dialog(), "button").find(
        (b) => b.textContent === "Settings",
      ) as HTMLButtonElement,
    );
    expect(navigate).toHaveBeenCalledWith("/profile?tab=notifications");
  });
});

describe("FR_UX_11 live: You approved only after the server recorded it", () => {
  const items = [note("a", { dec: "depot" })];

  it("test_FR_UX_11_live_row_stays_open_while_the_answer_is_in_flight_then_reads_You_approved", async () => {
    let answer: (v: ApiResult<DecideAck>) => void = () => undefined;
    const api = withNotifications(Promise.resolve(items), [decision("depot"), decision("mail")]);
    api.decide = () =>
      new Promise((resolve) => {
        answer = resolve;
      });
    await mountApp({ api });
    click(bell());
    expect(rows()[0]?.getAttribute("data-kind")).toBe("needs");

    act(() => seen.app.decide("depot"));
    await settle();
    // Nothing has been recorded yet: no local guess
    expect(rows()[0]?.getAttribute("data-kind")).toBe("needs");
    expect(rows()[0]?.textContent).toContain("Live item a");
    expect(rows()[0]?.textContent).not.toContain("You approved");

    await act(async () => answer({ data: { ok: true, dec: { depot: true } }, source: "live" }));
    await settle();
    expect(rows()[0]?.getAttribute("data-kind")).toBe("done");
    expect(rows()[0]?.textContent).toContain("You approved");
  });

  it("test_FR_UX_11_live_a_rejected_answer_leaves_the_row_open", async () => {
    const api = withNotifications(Promise.resolve(items), [decision("depot"), decision("mail")]);
    api.decide = () => Promise.reject(new TiloApiError("Tilo could not record that.", 500, true));
    await mountApp({ api });
    click(bell());
    act(() => seen.app.decide("depot"));
    await settle();
    expect(rows()[0]?.getAttribute("data-kind")).toBe("needs");
    expect(rows()[0]?.textContent).not.toContain("You approved");
    expect(seen.app.dec.depot).toBeUndefined();
  });
});

describe("FR_UX_11 live: the bell's dot counts what the service served", () => {
  it("test_FR_UX_11_live_no_waiting_decision_means_no_dot_not_the_sample_count", async () => {
    await mountApp({ api: withNotifications(Promise.resolve([]), []) });
    expect(unreadDots()).toHaveLength(0);
  });

  it("test_FR_UX_11_live_dot_shows_for_a_waiting_decision_and_clears_once_it_is_recorded_or_read", async () => {
    const api = withNotifications(Promise.resolve([note("a", { dec: "depot" })]), [
      decision("depot"),
    ]);
    api.decide = () =>
      Promise.resolve({
        data: { ok: true as const, dec: { depot: true as const } },
        source: "live",
      });
    await mountApp({ api });
    expect(unreadDots()).toHaveLength(1);
    act(() => seen.app.decide("depot"));
    await settle();
    expect(seen.store.getState().read).toBe(false);
    expect(unreadDots()).toHaveLength(0);
  });

  it("test_FR_UX_11_live_opening_the_bell_clears_the_dot_for_good", async () => {
    await mountApp({ api: withNotifications(Promise.resolve([]), [decision("depot")]) });
    expect(unreadDots()).toHaveLength(1);
    click(bell());
    expect(unreadDots()).toHaveLength(0);
    click(bell());
    expect(unreadDots()).toHaveLength(0);
  });
});
