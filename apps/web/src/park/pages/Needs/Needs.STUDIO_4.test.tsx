// @vitest-environment happy-dom
// STUDIO-4 Needs you ("made clearer", design/studio-v2 "Tilo S Needs"): one decision at a time, each a plain question
// with what happens if yes, if no, the cost and exactly what will be sent; buttons say what they do. Live data is the
// cross-world `GET /cards` feed answered by `POST .../answer` through the real live Api over a stubbed fetch; a
// question keeps its typed answer (OWN-ANSWER); a gate's "Show me" reads `GET .../cards/{cid}/item` only when asked.
import type { Card } from "@tilo/contracts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import {
  type Mounted,
  cleanup,
  click,
  mount,
  press,
  q,
  qa,
} from "../../../../test-support/park/componentsHarness";
import { settle, typeInto } from "../../../../test-support/park/skillsHarness";
import type { FieldsApi } from "../../../api/fields";
import type { ItemApi } from "../../../api/item";
import type { Api } from "../../api";
import { createFixtureApi } from "../../api/fixtureApi";
import { createLiveApi } from "../../api/liveApi";
import type { Dec } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { ParkProvider } from "../../app/context";
import type { FieldsFor } from "../../app/fieldsContext";
import { NeedsPage } from "./NeedsPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const GATE: Card = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W3",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: { building: "B2", agent: "A_s1" },
  add_context: true,
  created_at: "2026-10-15T09:30:00.000Z",
  timeout: 3600,
  gate: {
    id: "G1",
    action: {
      type: "send_email",
      connector: "gmail",
      exact: "Send the drafted reply in the thread 'Quote for 500 packs' to orders@example.com.",
      item: { artifact_id: "art_reply_draft", version: 2, label: "Reply draft" },
      destination: "thread-quote-500-packs",
    },
    recipients: ["orders@example.com"],
    irreversible: true,
    risk_tier: "T3",
  },
  consent: null,
  kind: "gate",
  rung: "gate",
  what_happened: "The reply to the supplier is drafted and ready to send.",
  why_it_matters: "It confirms the order of 500 packs at the quoted price.",
  options: [
    { id: "approve", label: "Approve", suggested: false, irreversible: true },
    {
      id: "edit",
      label: "Edit first",
      suggested: true,
      reason: "A new recipient.",
      irreversible: false,
    },
    { id: "hold", label: "Hold", suggested: false, irreversible: false },
  ],
  actions: ["show_me", "snooze"],
  answer_channels: ["web", "mobile_web"],
  safe_default: "hold",
} as Card;

const QUESTION: Card = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W4",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: { building: "B2", agent: "A_s1" },
  add_context: true,
  created_at: "2026-10-15T09:31:00.000Z",
  timeout: 3600,
  gate: null,
  consent: null,
  kind: "needs_you",
  rung: "needs_you",
  what_happened: "Two quotes use different pack sizes.",
  why_it_matters: "Comparing them per pack would favour the larger pack.",
  options: [
    {
      id: "per_kwh",
      label: "Compare per kWh",
      suggested: true,
      reason: "It is fair.",
      irreversible: false,
    },
    { id: "per_pack", label: "Compare per pack", suggested: false, irreversible: false },
  ],
  actions: ["show_me", "snooze", "delegate"],
  answer_channels: ["web", "mobile_web", "email"],
  safe_default: "per_kwh",
} as Card;

const ANSWER = (card: Card) => `/worlds/w_01/cards/${card.id}/answer`;

function liveRig(fields?: FieldsFor) {
  const fetchSpy = vi.fn(async (url: unknown, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    const method = init?.method ?? "GET";
    if (method === "GET" && path.startsWith("/cards"))
      return json({
        cards: [GATE, QUESTION].map((card) => ({ world_id: "w_01", card_id: card.id, card })),
        count: 2,
        next_cursor: null,
      });
    if (method === "GET" && path.startsWith("/worlds?"))
      return json({ worlds: [], next_cursor: null });
    if (method === "POST" && path.endsWith("/answer")) return json({ outcome: "answered" });
    throw new Error(`unrouted ${method} ${path}`);
  });
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const posts = (path: string) =>
    fetchSpy.mock.calls
      .filter((c) => c[1]?.method === "POST" && String(c[0]) === `${BASE}${path}`)
      .map((c) => JSON.parse(String(c[1]?.body)));
  return { api, fetchSpy, posts, fields };
}

async function mountNeeds(api: Api, over: Partial<AppCtx> = {}, fields?: FieldsFor | null) {
  const app = stubApp("needs" as AppCtx["page"], {
    decide: vi.fn((k, text, option) => {
      void api.decide(k, text, option).catch(() => undefined);
    }),
    ...over,
  });
  const tree = (a: AppCtx) => (
    <ParkProvider
      api={api}
      schedule={() => () => undefined}
      viewport={{ vw: 1440, vh: 900 }}
      fields={fields ?? null}
    >
      <NeedsPage app={a} />
    </ParkProvider>
  );
  const m: Mounted = mount(tree(app));
  await settle();
  return {
    app,
    m,
    rerender: async (a: AppCtx) => {
      m.render(tree(a));
      await settle();
    },
  };
}

const text = (el: ParentNode) =>
  ((el as HTMLElement).textContent ?? "").replace(/\s+/g, " ").trim();
const button = (root: ParentNode, name: string) =>
  qa<HTMLButtonElement>(root, "button").find(
    (b) => text(b) === name || b.getAttribute("aria-label") === name,
  );
const box = (root: ParentNode, label: string) => q(root, `section[aria-label="${label}"]`);

describe("STUDIO_4 Needs you: one decision at a time, made clear", () => {
  it("CX_T_NEEDS_gate_shows_plain_risk_and_posts_each_served_action", async () => {
    const { api, posts } = liveRig();
    const { m } = await mountNeeds(api);
    const card = q(m.container, "article");
    expect(text(q(card, '[aria-label="Risk"]'))).toContain("cannot be undone");
    expect(text(q(card, '[aria-label="Risk"]'))).toContain("orders@example.com");
    expect(q(card, '[aria-label="Risk"]').classList.contains("park-needs__risk--high")).toBe(true);
    expect(button(card, "Edit first")).toBeTruthy();
    expect(button(card, "Hold")).toBeTruthy();
    click(button(card, "Edit first") as HTMLButtonElement);
    await settle();
    expect(posts(ANSWER(GATE))).toEqual([{ option: "edit" }]);
  });

  it("CX_T_NEEDS_hold_uses_the_served_hold_option", async () => {
    const { api, posts } = liveRig();
    const { m } = await mountNeeds(api);
    click(button(m.container, "Hold") as HTMLButtonElement);
    await settle();
    expect(posts(ANSWER(GATE))).toEqual([{ option: "hold" }]);
  });

  it("CX_T_NEEDS_rejects_an_option_the_card_did_not_serve", async () => {
    const { api, posts } = liveRig();
    const first = (await api.getDecisions()).data[0];
    if (!first) throw new Error("missing served decision");
    await expect(api.decide(first.k, undefined, "forged")).rejects.toThrow();
    expect(posts(ANSWER(GATE))).toEqual([]);
  });

  it("STUDIO_4_needs_shows_one_decision_with_its_plain_question_yes_no_cost_and_what_is_sent", async () => {
    const { api } = liveRig();
    const { m } = await mountNeeds(api);
    expect(qa(m.container, "h1").map(text)).toEqual(["Needs you"]);
    expect(qa(m.container, "article")).toHaveLength(1); // one decision at a time
    const card = q(m.container, "article");
    expect(text(q(card, "h2"))).toBe(GATE.what_happened);
    expect(text(card)).toContain("1 of 2");
    expect(text(box(card, "If you say yes"))).toContain(GATE.gate?.action.exact ?? "missing");
    expect(text(box(card, "If you say yes"))).toContain("cannot be undone");
    expect(text(box(card, "If you say no"))).toContain("Nothing is sent or shared.");
    expect(text(box(card, "Cost"))).toContain("Not reported for this decision"); // a card serves no cost: none is made up
    const sent = box(card, "Exactly what will be sent");
    expect(text(sent)).toContain("orders@example.com");
    expect(text(sent)).toContain("Reply draft");
    // the queue lists both, in order, and names the shown one
    const rows = qa(m.container, 'nav[aria-label="Waiting on you"] button');
    expect(rows.map((r) => r.getAttribute("aria-current"))).toEqual(["true", null]);
  });

  it("STUDIO_4_needs_the_one_primary_button_says_its_answer_and_posts_approve_once", async () => {
    const { api, posts } = liveRig();
    const { m, app } = await mountNeeds(api);
    expect(qa(m.container, ".park-btn--primary")).toHaveLength(1);
    const approve = button(m.container, "Approve") as HTMLButtonElement;
    expect(approve.classList.contains("park-btn--primary")).toBe(true);
    // what the tap does is said beside it
    const says = approve.getAttribute("aria-describedby") ?? "";
    expect(text(q(m.container, `[id="${says}"]`))).toContain(
      "releases exactly what is shown above",
    );
    expect(button(m.container, "Decide later: next decision")).toBeTruthy();
    click(approve);
    await settle();
    expect(app.decide).toHaveBeenCalledTimes(1);
    expect(posts(ANSWER(GATE))).toEqual([{ option: "approve" }]);
  });

  it("STUDIO_4_needs_decide_later_moves_on_and_sends_nothing_and_J_K_move_too", async () => {
    const { api, posts } = liveRig();
    const { m } = await mountNeeds(api);
    click(button(m.container, "Decide later: next decision") as HTMLButtonElement);
    await settle();
    expect(text(q(m.container, "article h2"))).toBe(QUESTION.what_happened);
    expect(posts(ANSWER(GATE))).toEqual([]);
    press(document.body, "k");
    await settle();
    expect(text(q(m.container, "article h2"))).toBe(GATE.what_happened);
    press(document.body, "j");
    await settle();
    expect(text(q(m.container, "article h2"))).toBe(QUESTION.what_happened);
  });

  it("STUDIO_4_needs_a_question_lists_its_choices_and_what_happens_unanswered_and_takes_a_typed_answer", async () => {
    const { api, posts } = liveRig();
    const { m } = await mountNeeds(api);
    click(button(m.container, "Next decision") as HTMLButtonElement);
    await settle();
    const card = q(m.container, "article");
    expect(text(box(card, "Your choices"))).toContain("“Compare per kWh” (suggested): It is fair.");
    expect(text(box(card, "If you don’t answer"))).toContain("Tilo picks “Compare per kWh”");
    const field = q<HTMLTextAreaElement>(card, "textarea");
    typeInto(field, "Per kWh, and flag the pack size");
    click(button(card, "Send") as HTMLButtonElement);
    await settle();
    expect(posts(ANSWER(QUESTION))).toEqual([{ text: "Per kWh, and flag the pack size" }]);
  });

  it("STUDIO_4_needs_show_me_reads_the_pinned_item_only_when_asked_and_shows_it_as_text", async () => {
    const getCardItem = vi.fn(async () => ({
      document: JSON.stringify({
        kind: "email",
        subject: "Quote for 500 packs",
        body_text: "<b>Hello</b> team",
      }),
      recipients: ["orders@example.com"],
    }));
    const item: FieldsApi & ItemApi = {
      getCardFields: vi.fn(),
      supplyCardFields: vi.fn(),
      getCardItem,
    } as unknown as FieldsApi & ItemApi;
    const { api } = liveRig();
    const { m } = await mountNeeds(api, {}, () => item);
    expect(getCardItem).not.toHaveBeenCalled();
    click(button(m.container, "Show me the full item") as HTMLButtonElement);
    await settle();
    expect(getCardItem).toHaveBeenCalledWith(GATE.id);
    const shown = text(m.container);
    expect(shown).toContain("Quote for 500 packs");
    expect(shown).toContain("<b>Hello</b> team"); // text, never markup
    expect(qa(m.container, "article b")).toHaveLength(0);
  });

  it("STUDIO_4_needs_answered_decisions_leave_the_queue_and_the_last_one_leaves_an_empty_state", async () => {
    const api = createFixtureApi();
    const { m, app, rerender } = await mountNeeds(api);
    const first = text(q(m.container, "article h2"));
    expect(text(box(q(m.container, "article"), "Cost"))).toMatch(/£\d/); // the fixture's own amount
    const dec: Dec = {};
    for (const d of (await api.getDecisions()).data) dec[d.k] = true;
    await rerender({ ...app, dec });
    expect(qa(m.container, "article")).toHaveLength(0);
    expect(text(m.container)).toContain("Nothing needs you");
    expect(text(q(m.container, 'section[aria-label="Answered here"]'))).toContain(first);
    expect(qa(m.container, ".park-btn--primary")).toHaveLength(1);
  });

  it("STUDIO_4_needs_a_failed_read_says_so_and_answers_nothing", async () => {
    const api = {
      ...createFixtureApi(),
      getDecisions: vi.fn(async () => Promise.reject(new Error("down"))),
    } as Api;
    const { m, app } = await mountNeeds(api);
    expect(text(q(m.container, '[role="alert"]'))).toContain("Needs you could not load");
    expect(app.decide).not.toHaveBeenCalled();
  });
});
