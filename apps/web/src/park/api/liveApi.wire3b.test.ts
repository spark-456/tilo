// WIRE-3 addendum (supervisor decision): the answer route only accepts a card whose world is the session's world
// (services/api/src/tilo_api/cards.py), so `decide` on a feed card of another owned world gets a 404. The Api makes
// that case actionable: a TiloApiError with `code` "open_in_world" and `write` true; the world to open is the
// Decision's `world`. Also pins that a tap sends exactly the option `Decision.yes` names, and that a gate's body
// carries its exact action and every recipient (BQ-WIRE3-4).
import { describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { decisionsFromCards } from "./live/decisionsFromCards";
import { createLiveApi } from "./liveApi";
import type { Decision, DecisionKey } from "./types";

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
const key = (d: Decision | undefined): DecisionKey => {
  if (!d) throw new Error("the feed served no decision");
  return d.k;
};
const feed = {
  cards: [{ world_id: "w_other", card_id: gateCard.id, card: gateCard }],
  next_cursor: null,
};

function setup(answer: () => Response) {
  const spy = vi.fn(async (_url: string | URL | Request, init?: RequestInit) =>
    init?.method === "POST" ? answer() : json(feed),
  );
  return { spy, api: createLiveApi({ baseUrl: BASE, fetch: spy as unknown as typeof fetch }) };
}

describe("WIRE_3_open_in_world: a card of another world cannot be answered here", () => {
  it.each([
    ["a bare 404", () => json({ detail: "Not Found" }, 404)],
    [
      "a rejected card_not_found",
      () => json({ outcome: "rejected", reason: "card_not_found" }, 404),
    ],
  ])("WIRE_3_decide_404_from_%s_is_open_in_world_with_write_true", async (_n, answer) => {
    const { spy, api } = setup(answer);
    const [d] = (await api.getDecisions()).data;
    const err = await api.decide(key(d)).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(TiloApiError);
    const e = err as TiloApiError;
    expect(e.code).toBe("open_in_world");
    expect(e.status).toBe(404);
    expect(e.write).toBe(true);
    expect(e.retryable).toBe(false);
    expect(d?.world).toBe("w_other"); // the world the page opens
    expect(spy.mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(1);
  });

  it("WIRE_3_decide_other_refusals_keep_no_open_in_world_code", async () => {
    const { api } = setup(() => json({ outcome: "rejected", reason: "forbidden" }, 403));
    const [d] = (await api.getDecisions()).data;
    const err = (await api.decide(key(d)).catch((e: unknown) => e)) as TiloApiError;
    expect(err.code).not.toBe("open_in_world");
    expect(err.write).toBe(true);
  });
});

describe("WIRE_3_tap_matches_the_words: what the person reads is what a tap sends", () => {
  it("WIRE_3_decide_a_gate_sends_the_option_whose_label_is_yes_and_its_body_names_the_action", async () => {
    const { spy, api } = setup(() => json({ outcome: "answered" }));
    const [d] = (await api.getDecisions()).data;
    expect(d?.yes).toBe("Approve");
    expect(d?.body).toContain("Email the brief to two suppliers");
    expect(d?.body).toContain("one@example.test");
    expect(d?.body).toContain("two@example.test");
    await api.decide(key(d));
    const sent = JSON.parse(
      String(spy.mock.calls.find(([, i]) => i?.method === "POST")?.[1]?.body),
    );
    const label = gateCard.options.find((o) => o.id === sent.option)?.label;
    expect(label).toBe(d?.yes);
  });

  it("WIRE_3_decisionsFromCards_yes_is_the_label_of_the_option_a_tap_answers_for_every_kind", () => {
    const question = {
      ...gateCard,
      kind: "needs_you",
      gate: null,
      options: [
        { id: "a", label: "Not this", suggested: false, irreversible: false },
        { id: "b", label: "This one", suggested: true, irreversible: false },
      ],
    };
    const [d] = decisionsFromCards([
      { world_id: "w_other", card_id: gateCard.id, card: question as never },
    ]);
    expect(d?.yes).toBe("This one");
  });
});
