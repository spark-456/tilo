// @vitest-environment happy-dom
// FR-SPD-01 and FR-SPD-07 on the Ledger page (docs/prd-supplement-design-2026-10-06.md section 1.3).
//
// FR-SPD-01 "Five KPI tiles. Done when: every figure equals the credit ledger; 'waiting on you' opens the world."
//   Each tile's figure is stated here as a function of the SAME ledger object the page was given (never a typed
//   number), for the fixture, for a changed ledger, and for generated ledgers; the waiting tile opens the world
//   of the decision the page was given.
// FR-SPD-07 "Activity log. Done when: approving from the log is the same single decide() call as everywhere else."
//   Approving a row calls Api.decide once with the card's key, exactly as the store's own decide does, and no
//   other code path posts an answer (static scan plus a live Api with a counting fetch).
//
// Each test says whether it pins existing behaviour (GREEN today) or a gap (RED today) in its comment.
// Ambiguities resolved here (PRD supplement defaults):
//  - BQ-DSN-02: a ledger served in USD (live shape) shows its own unit on every tile, never the design's "£".
//  - Labels are the five names of FR-SPD-01 verbatim, case-sensitive.
//  - "Saved by memory" and "Hours handed back" carry no invented figure in their sub line (HR-1, "every figure
//    equals the credit ledger"); "Up £120 on August" is a typed number the ledger does not hold.
import fc from "fast-check";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, click, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  KPI_LABELS,
  type KpiLabel,
  controlOf,
  dollars,
  figuresOf,
  pounds,
  tileCandidates,
  tileLabelsPresent,
  tileShowing,
  variedLedger,
} from "../../../../test-support/park/spdKpis";
import { decisions as fixtureDecisions, ledger as fixtureLedger } from "../../api/fixtures";
import type { Api } from "../../api/index";
import { type CardFeedItem, decisionKey } from "../../api/live/decisionsFromCards";
import { createLiveApi } from "../../api/liveApi";
import type { Decision, DecisionKey, Ledger } from "../../api/types";
import { ParkProvider, useApp, useParkStore } from "../../app/context";
import type { ParkStore } from "../../app/store";
import { LedgerPage } from "./LedgerPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

function Shell({ onStore }: { onStore: (s: ParkStore) => void }) {
  const app = useApp();
  onStore(useParkStore());
  return (
    <div data-park="" data-time={app.time}>
      <LedgerPage app={app} />
    </div>
  );
}

interface Rig {
  ledger?: Ledger;
  decisions?: Decision[];
  api?: Api;
}

/** The Ledger route mounted the way the shell does, over an Api that serves exactly `ledger` and `decisions`. */
async function mountLedger(rig: Rig = {}) {
  window.history.pushState({}, "", "/park/ledger");
  const api = (rig.api ?? fakeApi()) as ReturnType<typeof fakeApi>;
  const ledger = rig.ledger;
  const given = rig.decisions;
  if (ledger)
    api.getLedger = (() =>
      Promise.resolve({ data: ledger, source: "fixture" })) as typeof api.getLedger;
  if (given)
    api.getDecisions = (() =>
      Promise.resolve({ data: given, source: "fixture" })) as typeof api.getDecisions;
  const navigate = vi.fn();
  let held: ParkStore | undefined;
  const m = mount(
    <ParkProvider
      api={api}
      navigate={navigate}
      schedule={fakeScheduler().schedule}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <Shell
        onStore={(s) => {
          held = s;
        }}
      />
    </ParkProvider>,
  );
  const store = held;
  if (!store) throw new Error("the shell did not mount");
  await settle();
  return { ...m, api, navigate, store };
}

/** Fails with the label and the figure it wanted, listing what each candidate tile said. */
function expectTile(root: HTMLElement, label: KpiLabel, figure: string) {
  const tile = tileShowing(root, label, figure);
  const saw = tileCandidates(root, label).map((t) => t.textContent);
  expect(
    tile,
    `"${label}" should show ${figure}; tiles named so say ${JSON.stringify(saw)}`,
  ).toBeDefined();
  return tile as HTMLElement;
}

describe("FR_SPD_01_ledger_five_kpi_tiles: every figure equals the credit ledger", () => {
  // GREEN: pins existing behaviour (kpis() in model.ts).
  it("FR_SPD_01_ledger_shows_the_five_tiles_each_equal_to_the_fixture_ledger", async () => {
    const { container } = await mountLedger({ ledger: fixtureLedger });
    expect(tileLabelsPresent(container)).toEqual([...KPI_LABELS]);
    const want = figuresOf(fixtureLedger);
    for (const label of KPI_LABELS) expectTile(container, label, want[label]);
  });

  // GREEN: pins that the tiles read the ledger the page was given, not the fixture.
  it("FR_SPD_01_ledger_tiles_follow_a_changed_ledger_and_keep_none_of_the_old_figures", async () => {
    const changed = variedLedger(fixtureLedger);
    const { container } = await mountLedger({ ledger: changed });
    const want = figuresOf(changed);
    expect(want, "the changed ledger shares no figure with the fixture").not.toEqual(
      figuresOf(fixtureLedger),
    );
    const tiles = new Set<HTMLElement>();
    for (const label of KPI_LABELS) tiles.add(expectTile(container, label, want[label]));
    const old = figuresOf(fixtureLedger);
    for (const t of tiles)
      for (const stale of Object.values(old))
        expect(
          t.textContent,
          `tile "${t.textContent}" keeps the fixture figure ${stale}`,
        ).not.toContain(stale);
  });

  // GREEN: property over generated ledgers (the same object feeds the page and the expectation).
  it("FR_SPD_01_ledger_property_every_tile_equals_the_figure_derived_from_the_ledger_given", async () => {
    const whole = (max: number) => fc.integer({ min: 100, max });
    await fc.assert(
      fc.asyncProperty(
        whole(99999),
        whole(99999),
        whole(99999),
        fc.array(whole(9999), { minLength: 1, maxLength: 5 }),
        fc.array(fc.integer({ min: 1, max: 60 }), { minLength: 1, maxLength: 3 }),
        async (spent, forecast, waiting, memory, hours) => {
          const L = variedLedger(fixtureLedger);
          L.budget = 200000;
          L.spent = spent;
          L.forecast = forecast;
          const tx = L.tx.find((t) => t.st === "waiting");
          if (tx) tx.amt = waiting;
          L.memory = memory;
          L.hours = hours.map((h, i) => [`Team ${i}`, h, "var(--ok)", "Work"]);
          const { container } = await mountLedger({ ledger: L });
          const want = figuresOf(L);
          for (const label of KPI_LABELS) expectTile(container, label, want[label]);
          cleanup();
        },
      ),
      { numRuns: 12 },
    );
  }, 120_000);

  // RED today (BQ-DSN-02): "Month-end forecast", "Waiting on you" and "Saved by memory" format with a fixed
  // "£" (gbp) even when the ledger says USD; only "Spent so far" uses the ledger's own currency.
  it("FR_SPD_01_ledger_tiles_use_the_ledgers_own_unit_never_a_fixed_pound_sign", async () => {
    const live: Ledger = { ...variedLedger(fixtureLedger), currency: "USD" };
    const { container } = await mountLedger({ ledger: live });
    const want = figuresOf(live, dollars);
    const poundTiles = KPI_LABELS.filter((label) =>
      expectTile(container, label, want[label]).textContent?.includes("£"),
    );
    expect(poundTiles, "tiles that print a pound sign for a USD ledger").toEqual([]);
  });

  // RED today: the "Saved by memory" sub line is the typed text "Up £120 on August". A figure the ledger does
  // not hold must not appear (HR-1); the ledger given here has no August data, so "£120" cannot be derived.
  it("FR_SPD_01_ledger_saved_by_memory_sub_line_states_no_figure_the_ledger_does_not_hold", async () => {
    const changed = variedLedger(fixtureLedger); // memory is [10, 20, 30, 40]
    const { container } = await mountLedger({ ledger: changed });
    const tile = expectTile(container, "Saved by memory", figuresOf(changed)["Saved by memory"]);
    expect(tile.textContent).not.toContain("£120");
    expect(tile.textContent).not.toContain("August");
  });

  // GREEN: pins the existing amber tile: it is one real control and opens the world of the pending decision.
  it("FR_SPD_01_ledger_waiting_on_you_tile_opens_the_world_of_the_decision_it_was_given", async () => {
    const first = await mountLedger({ ledger: fixtureLedger, decisions: fixtureDecisions });
    const wait = tileShowing(first.container, "Waiting on you", pounds(3420));
    const control = wait && controlOf(wait);
    expect(control, "the waiting tile is a control").toBeDefined();
    click(control as HTMLElement);
    expect(first.navigate).toHaveBeenCalledWith("/world/k1");
    cleanup();
    // The world comes from the decisions the page was given: change it and the tile follows.
    const moved = fixtureDecisions.map((d) =>
      d.k === "depot" ? { ...d, world: "depot-world-b" } : d,
    );
    const next = await mountLedger({ ledger: fixtureLedger, decisions: moved });
    const tile = tileShowing(next.container, "Waiting on you", pounds(3420));
    click(controlOf(tile as HTMLElement) as HTMLElement);
    expect(next.navigate).toHaveBeenCalledWith("/world/depot-world-b");
    expect(next.navigate).toHaveBeenCalledTimes(1);
  });

  // GREEN: the other four tiles do not navigate (only the waiting tile opens the world).
  it("FR_SPD_01_ledger_only_the_waiting_tile_is_a_control", async () => {
    const { container } = await mountLedger({ ledger: fixtureLedger, decisions: fixtureDecisions });
    for (const label of KPI_LABELS.filter((l) => l !== "Waiting on you")) {
      const tile = expectTile(container, label, figuresOf(fixtureLedger)[label]);
      expect(controlOf(tile), `"${label}" is plain text`).toBeUndefined();
    }
  });
});

// ---------------------------------------------------------------------------------------------------------
// FR-SPD-07

/** The Approve button of the open waiting row of the Activity log. */
const approveButtons = (root: HTMLElement) =>
  qa<HTMLButtonElement>(q(root, 'section[aria-label="Activity"]'), "button").filter((b) =>
    /^Approve\b/.test((b.textContent ?? "").trim()),
  );

describe("FR_SPD_07_ledger_activity_log_approve_is_the_one_decide_call", () => {
  // GREEN: pins that an approval from the log is one Api.decide call carrying the card key and nothing else.
  it("FR_SPD_07_approving_from_the_log_calls_api_decide_once_with_the_key_alone", async () => {
    const { container, api } = await mountLedger();
    const buttons = approveButtons(container);
    expect(buttons, "the first waiting row is open with its Approve button").toHaveLength(1);
    click(buttons[0] as HTMLButtonElement);
    expect(api.decide).toHaveBeenCalledTimes(1);
    expect(api.decide.mock.calls[0]).toEqual(["depot"]);
    expect(api.undo).not.toHaveBeenCalled();
    expect(api.startWorld).not.toHaveBeenCalled();
  });

  // GREEN: same function, same arguments as the store's own decide (what Worlds, World and the shell call).
  it("FR_SPD_07_the_log_and_the_shared_decide_make_the_identical_api_call", async () => {
    const viaLog = await mountLedger();
    click(approveButtons(viaLog.container)[0] as HTMLButtonElement);
    const logCalls = [...viaLog.api.decide.mock.calls];
    cleanup();
    const viaStore = await mountLedger();
    act(() => viaStore.store.decide("depot"));
    expect(logCalls).toEqual(viaStore.api.decide.mock.calls);
    expect(logCalls).toHaveLength(1);
    // The resulting shared state is the same too: the decision is taken and the toast says so.
    expect(viaLog.store.getState().dec).toEqual(viaStore.store.getState().dec);
    expect(viaLog.store.getState().toast?.message).toBe(viaStore.store.getState().toast?.message);
  });

  // GREEN: a second press on the stale button (double click, slow render) answers nothing twice.
  it("FR_SPD_07_a_second_press_does_not_send_a_second_answer", async () => {
    const { container, api } = await mountLedger();
    const button = approveButtons(container)[0] as HTMLButtonElement;
    click(button);
    click(button);
    expect(api.decide).toHaveBeenCalledTimes(1);
  });

  // GREEN: the mail row of the log is the same call with its own key, in the order the person pressed.
  it("FR_SPD_07_each_log_approval_is_one_call_with_its_own_key", async () => {
    const { container, api } = await mountLedger();
    const activity = q(container, 'section[aria-label="Activity"]');
    click(approveButtons(container)[0] as HTMLButtonElement);
    const mail = qa<HTMLElement>(activity, "button[aria-expanded]").find((b) =>
      (b.textContent ?? "").includes("Supplier brief waiting"),
    );
    click(mail as HTMLElement);
    const send = qa<HTMLButtonElement>(activity, "button").find(
      (b) => b.textContent === "Send brief",
    );
    click(send as HTMLButtonElement);
    expect(api.decide.mock.calls).toEqual([["depot"], ["mail"]]);
  });

  // GREEN: with the live Api (counting fetch) the log's Approve posts exactly one answer, to the card's route.
  it("FR_SPD_07_live_api_approve_from_the_log_posts_exactly_one_answer", async () => {
    const card = {
      id: "01000000000000000000000001",
      world_id: "w_live1",
      run_id: "r_live1",
      kind: "gate",
      rung: "gate",
      header: { building: "B1", agent: "A_x" },
      what_happened: "Send the supplier brief",
      why_it_matters: "It goes outside the company",
      add_context: false,
      actions: ["show_me"],
      answer_channels: ["web", "mobile_web"],
      created_at: "2026-10-07T09:30:00.000Z",
      timeout: 3600,
      options: [
        { id: "approve", label: "Approve", suggested: false, irreversible: true },
        { id: "hold", label: "Hold", suggested: true, reason: "Safe.", irreversible: false },
      ],
      safe_default: "hold",
      gate: {
        id: "G1",
        action: {
          type: "send_email",
          connector: "gmail",
          exact: "Send the brief to the supplier",
          item: null,
          destination: null,
        },
        recipients: ["supplier@example.test"],
        irreversible: true,
        risk_tier: "T3",
      },
      consent: null,
    } as unknown as CardFeedItem["card"];
    const json = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    const fetchSpy = vi.fn(async (_url: string | URL | Request, init?: RequestInit) =>
      (init?.method ?? "GET") === "POST"
        ? json({ outcome: "answered" })
        : json({
            cards: [{ world_id: card.world_id, card_id: card.id, card }],
            count: 1,
            next_cursor: null,
          }),
    );
    const live = createLiveApi({ baseUrl: "https://api.example.test", fetch: fetchSpy as never });
    const key = decisionKey(card.world_id, card.id) as DecisionKey;
    const waitingLedger: Ledger = {
      ...fixtureLedger,
      tx: [],
      activity: [
        {
          day: "Today · Thu 24 Sep",
          t: "11:52",
          k: "waiting",
          dec: key,
          world: card.world_id,
          what: "Supplier brief waiting",
          sub: "Needs your sign-off",
          amt: "—",
          detail: [["Why", "It goes outside the company"]],
        },
      ],
    };
    live.getLedger = (() =>
      Promise.resolve({ data: waitingLedger, source: "live" })) as typeof live.getLedger;
    const { container } = await mountLedger({ api: live });
    const buttons = approveButtons(container);
    expect(buttons).toHaveLength(1);
    const reads = fetchSpy.mock.calls.length;
    click(buttons[0] as HTMLButtonElement);
    await settle();
    const posts = fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST");
    expect(posts, "exactly one POST for one press").toHaveLength(1);
    expect(String(posts[0]?.[0])).toBe(
      "https://api.example.test/worlds/w_live1/cards/01000000000000000000000001/answer",
    );
    expect(JSON.parse(String(posts[0]?.[1]?.body))).toEqual({ option: "approve" });
    expect(fetchSpy.mock.calls.length - reads, "no other request follows the press").toBe(1);
  });
});
