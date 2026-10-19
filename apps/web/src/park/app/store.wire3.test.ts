// WIRE-3 (security review of #548): with the live Api, the store marks a decision taken only after tilo-api
// recorded the answer (HR-1). A failure leaves the card open and says why, another world's card offers "Open in
// world", a live decision offers no Undo (no route reopens a card), and a second tap while the first is in flight
// sends nothing.
import { describe, expect, it, vi } from "vitest";
import { fakeScheduler } from "../../../test-support/park/appHarness";
import { createLiveApi } from "../api/liveApi";
import { createParkStore } from "./store";

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const gateCard = {
  id: "01HZ00000000000000000GATE1",
  world_id: "w_other",
  run_id: "r_1",
  kind: "gate",
  rung: "gate",
  header: { building: "B1", agent: "A_x" },
  what_happened: "Send the brief",
  why_it_matters: "The supplier waits",
  options: [
    { id: "approve", label: "Approve", suggested: false, irreversible: true },
    { id: "hold", label: "Hold", suggested: true, irreversible: false },
  ],
  gate: {
    id: "G1",
    action: { type: "send_email", connector: "gmail", exact: "Email the brief to two suppliers" },
    recipients: ["one@example.test", "two@example.test"],
    irreversible: true,
    risk_tier: "T3",
  },
  consent: null,
};
const feed = {
  cards: [{ world_id: "w_other", card_id: gateCard.id, card: gateCard }],
  next_cursor: null,
};
const flush = () => new Promise((r) => setTimeout(r, 0));

async function setup(answer: () => Response | Promise<Response>) {
  const fetchSpy = vi.fn(async (_url: string | URL | Request, init?: RequestInit) =>
    init?.method === "POST" ? answer() : json(feed),
  );
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const navigate = vi.fn();
  const store = createParkStore({
    api,
    navigate,
    schedule: fakeScheduler().schedule,
    now: () => 0,
  });
  const got = await api.getDecisions();
  store.noteSource(got.source);
  store.setDecisions(got.data);
  const k = got.data[0]?.k;
  if (!k) throw new Error("the feed served no decision");
  const posts = () => fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST").length;
  return { store, navigate, k, posts };
}

describe("WIRE_3_store_live: a decision is taken only when tilo-api recorded it", () => {
  it.each([
    ["a 404 (another world)", () => json({ detail: "Not Found" }, 404)],
    ["a 400 refusal", () => json({ outcome: "rejected", reason: "invalid_option" }, 400)],
    ["a 403", () => json({ detail: "Forbidden" }, 403)],
    ["a 409", () => json({ detail: "Conflict" }, 409)],
    ["a 503", () => json({ detail: "event_write_failed" }, 503)],
    ["a 200 that says rejected", () => json({ outcome: "rejected", reason: "already_resolved" })],
    [
      "a network failure",
      () => {
        throw new TypeError("connect ECONNREFUSED 10.0.0.7:8080");
      },
    ],
  ])(
    "WIRE_3_store_live_%s_leaves_the_card_open_with_no_success_toast_or_undo",
    async (_n, answer) => {
      const { store, k } = await setup(answer);
      store.decide(k);
      expect(store.getState().dec[k], "nothing is taken before the answer is recorded").toBeFalsy();
      await flush();
      const s = store.getState();
      expect(s.dec[k]).toBeFalsy();
      expect(s.toast?.actionLabel).not.toBe("Undo");
      expect(s.toast?.message ?? "").not.toMatch(/Send the brief/);
      expect(s.toast?.message ?? "").not.toContain("10.0.0.7");
    },
  );

  it("WIRE_3_store_live_another_worlds_card_offers_open_in_world_and_goes_there", async () => {
    const { store, k, navigate } = await setup(() => json({ detail: "Not Found" }, 404));
    store.decide(k);
    await flush();
    const t = store.getState().toast;
    expect(t?.actionLabel).toBe("Open in world");
    t?.action?.();
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(String(navigate.mock.calls[0]?.[0])).toContain("w_other");
  });

  it("WIRE_3_store_live_an_answered_approve_is_taken_and_offers_no_undo", async () => {
    const { store, k } = await setup(() => json({ outcome: "answered" }));
    store.decide(k);
    await flush();
    const s = store.getState();
    expect(s.dec[k]).toBe(true);
    expect(s.toast).not.toBeNull();
    expect(s.toast?.actionLabel).toBeUndefined();
    expect(s.toast?.action).toBeUndefined();
  });

  it("WIRE_3_store_live_a_second_tap_while_the_first_is_in_flight_sends_nothing", async () => {
    let release: (r: Response) => void = () => undefined;
    const { store, k, posts } = await setup(
      () =>
        new Promise<Response>((r) => {
          release = r;
        }),
    );
    store.decide(k);
    store.decide(k);
    await flush();
    expect(posts()).toBe(1);
    release(json({ outcome: "answered" }));
    await flush();
    store.decide(k);
    await flush();
    expect(posts(), "a taken decision is never answered again").toBe(1);
  });
});
