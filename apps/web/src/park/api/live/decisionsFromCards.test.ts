// WIRE-3 (Park wiring, third slice; S-06, FR-HIL-01, FR-HIL-02; PRD 9.4 HR-1..HR-7;
// services/api/tests/API_S_06_CARDS_FEED.md): the pure mapper from the tilo-api `GET /cards` items to the Park
// `Decision` type. Interface pinned here, for the builder:
// - file `apps/web/src/park/api/live/decisionsFromCards.ts`, named export `decisionsFromCards(items): Decision[]`
//   and the exported type `CardFeedItem = { world_id: string; card_id: string; card: Card }` (`Card` from
//   `@tilo/contracts`). Pure, never mutates its input, never imports fixtures. Order is kept (the API sends the
//   oldest first, the one waiting longest). It is only handed cards the live Api has already read as valid (the
//   Api refuses a feed it cannot read, see liveApi.wire3.test.ts), so its behaviour on a card with no affirmative
//   option is not pinned.
// - `world` = the item's world_id (the Park `Decision.world` is "the world this decision belongs to").
// - `k` (the Park `DecisionKey`, which the shared park types still declare as "depot" | "mail"): an opaque,
//   non-empty string, one per (world_id, card_id) pair and the same for the same pair every time. Two worlds that
//   hold a card with the same id get different keys (BQ-WIRE3-1). The Api, not the page, holds the way back from
//   `k` to world_id and card_id. No shared park type is changed.
// - `title` = card.what_happened and `body` = card.why_it_matters, both as served: not trimmed, truncated or
//   translated. A gate card's body also carries gate.action.exact and every gate.recipients entry, and a consent
//   card's body also carries every consent.scopes entry, so the person sees exactly what a tap on the button does
//   (BQ-WIRE3-4). A needs_you or meeting card's body is exactly why_it_matters.
// - `yes` = the label of the option a tap on the button answers with (BQ-WIRE3-2): a gate card's `approve`, a consent
//   card's `connect`, and for needs_you and meeting cards the one option marked `suggested`. For a gate this is NOT
//   the suggested option (that is `hold`, the safe default): approving is the person's explicit act.
// - NOT served, so empty, never a sample value (BQ-WIRE3-5): `icon`, `done`, `toast` and `approvedTitle` are "";
//   `facts` is absent.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Card } from "@tilo/contracts";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { decisions as fixtureDecisions } from "../fixtures";
import { type CardFeedItem, decisionsFromCards } from "./decisionsFromCards";

const ulid = (n: number) => `01${"0".repeat(21)}${String(n).padStart(3, "0")}`;

type Over = Record<string, unknown>;

/** A valid card of one kind, shaped like contracts/card.schema.json (the API already validated it). */
function card(n: number, kind: Card["kind"] = "needs_you", over: Over = {}): Card {
  const base = {
    id: ulid(n),
    world_id: `w_a${n}`,
    run_id: `r_a${n}`,
    kind,
    rung: kind === "needs_you" ? "needs_you" : kind,
    header: { building: "B1", agent: "A_x" },
    what_happened: `Something happened ${n}`,
    why_it_matters: `It matters because ${n}`,
    add_context: false,
    actions: ["show_me"],
    answer_channels: ["web", "mobile_web"],
    created_at: "2026-10-07T09:30:00.000Z",
    timeout: 3600,
    gate: null,
    consent: null,
  };
  const kinds: Record<string, Over> = {
    needs_you: {
      options: [
        { id: "skip_it", label: "Skip it", suggested: false, irreversible: false },
        { id: "go_on", label: "Go on", suggested: true, reason: "Cheapest.", irreversible: false },
      ],
      safe_default: "go_on",
    },
    meeting: {
      options: [
        { id: "join", label: "Join", suggested: true, reason: "On time.", irreversible: false },
        { id: "skip", label: "Skip", suggested: false, irreversible: false },
      ],
      safe_default: "join",
    },
    gate: {
      options: [
        { id: "approve", label: "Approve", suggested: false, irreversible: true },
        { id: "hold", label: "Hold", suggested: true, reason: "Safe.", irreversible: false },
      ],
      safe_default: "hold",
      answer_channels: ["web", "mobile_web"],
      actions: ["show_me"],
      gate: {
        id: "G1",
        action: {
          type: "send_email",
          connector: "gmail",
          exact: `Send the brief to the supplier ${n}`,
          item: null,
          destination: null,
        },
        recipients: [`a${n}@example.test`, `b${n}@example.test`],
        irreversible: true,
        risk_tier: "T3",
      },
    },
    consent: {
      options: [
        { id: "connect", label: "Connect", suggested: false, irreversible: false },
        { id: "hold", label: "Hold", suggested: true, reason: "Nothing yet.", irreversible: false },
      ],
      safe_default: "hold",
      consent: { connector: "gmail", scopes: [`Read mail ${n}`, `Send mail ${n}`] },
    },
  };
  return { ...base, ...kinds[kind], ...over } as unknown as Card;
}

const item = (n: number, kind: Card["kind"] = "needs_you", over: Over = {}): CardFeedItem => {
  const c = card(n, kind, over);
  return { world_id: c.world_id, card_id: c.id, card: c };
};

const deepFreeze = <T>(v: T): T => {
  if (typeof v === "object" && v !== null && !Object.isFrozen(v)) {
    Object.freeze(v);
    for (const x of Object.values(v)) deepFreeze(x);
  }
  return v;
};

describe("WIRE_3_decisionsFromCards: served fields map directly", () => {
  it("WIRE_3_decisionsFromCards_world_title_and_body_come_from_the_card_unedited", () => {
    const long = `  ${"é".repeat(138)}  `; // 142 chars with the spaces: neither trimmed nor cut
    const it1 = item(1, "needs_you", { what_happened: long, why_it_matters: " Why <b>so</b>\n  " });
    const [d] = decisionsFromCards([it1]);
    expect(d?.world).toBe(it1.world_id);
    expect(d?.title).toBe(long);
    expect(d?.body).toBe(" Why <b>so</b>\n  ");
  });

  it("WIRE_3_decisionsFromCards_a_needs_you_body_is_exactly_why_it_matters", () => {
    const [d] = decisionsFromCards([item(1, "needs_you")]);
    expect(d?.body).toBe("It matters because 1");
    const [m] = decisionsFromCards([item(2, "meeting")]);
    expect(m?.body).toBe("It matters because 2");
  });

  it("WIRE_3_decisionsFromCards_yes_is_the_label_of_the_suggested_option_on_a_question", () => {
    const [q] = decisionsFromCards([item(1, "needs_you")]);
    expect(q?.yes).toBe("Go on"); // the suggested option is the second one listed
    const [m] = decisionsFromCards([item(2, "meeting")]);
    expect(m?.yes).toBe("Join");
  });

  it("WIRE_3_decisionsFromCards_a_gate_says_approve_not_the_suggested_hold", () => {
    const [g] = decisionsFromCards([item(1, "gate")]);
    expect(g?.yes).toBe("Approve");
  });

  it("WIRE_3_decisionsFromCards_a_consent_card_says_connect_not_the_suggested_hold", () => {
    const [c] = decisionsFromCards([item(1, "consent")]);
    expect(c?.yes).toBe("Connect");
  });

  it("WIRE_3_decisionsFromCards_a_gate_body_shows_the_exact_action_and_every_recipient", () => {
    const [g] = decisionsFromCards([item(3, "gate")]);
    expect(g?.body).toContain("It matters because 3");
    expect(g?.body).toContain("Send the brief to the supplier 3");
    expect(g?.body).toContain("a3@example.test");
    expect(g?.body).toContain("b3@example.test");
  });

  it("WIRE_3_decisionsFromCards_a_consent_body_shows_every_scope", () => {
    const [c] = decisionsFromCards([item(4, "consent")]);
    expect(c?.body).toContain("It matters because 4");
    expect(c?.body).toContain("Read mail 4");
    expect(c?.body).toContain("Send mail 4");
  });
});

describe("WIRE_3_decisionsFromCards: unserved fields are empty, never sample copy (HR-1..HR-7)", () => {
  it("WIRE_3_decisionsFromCards_icon_done_toast_and_approvedTitle_are_empty_and_facts_is_absent", () => {
    for (const kind of ["needs_you", "meeting", "gate", "consent"] as const) {
      const [d] = decisionsFromCards([item(1, kind)]);
      expect(d?.icon, kind).toBe("");
      expect(d?.done, kind).toBe("");
      expect(d?.toast, kind).toBe("");
      expect(d?.approvedTitle, kind).toBe("");
      expect(d?.facts, kind).toBeUndefined();
    }
  });

  it("WIRE_3_decisionsFromCards_no_fixture_decision_text_reaches_the_output", () => {
    const out = JSON.stringify(
      decisionsFromCards([item(1), item(2, "gate"), item(3, "consent"), item(4, "meeting")]),
    );
    for (const f of fixtureDecisions) {
      for (const text of [f.title, f.body, f.yes, f.done, f.toast, f.approvedTitle]) {
        expect(out).not.toContain(text);
      }
    }
    expect(out).not.toContain('"depot"');
    expect(out).not.toContain('"mail"');
  });

  it("WIRE_3_decisionsFromCards_imports_no_fixture_screen_world_or_stage_code", () => {
    const src = readFileSync(join(__dirname, "decisionsFromCards.ts"), "utf8");
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+(?:live\/)?fixtures/);
    expect(src).not.toMatch(/from\s+["'](?:\.\.?\/)+fixtureApi/);
    expect(src).not.toMatch(/from\s+["'][^"']*\/(?:screens|world|stage)\//);
  });
});

describe("WIRE_3_decisionsFromCards: keys, order and purity", () => {
  it("WIRE_3_decisionsFromCards_an_empty_feed_is_an_empty_list", () => {
    expect(decisionsFromCards([])).toEqual([]);
  });

  it("WIRE_3_decisionsFromCards_keeps_the_order_and_gives_each_card_its_own_key", () => {
    const items = [item(3), item(1, "gate"), item(2, "consent"), item(4, "meeting")];
    const out = decisionsFromCards(items);
    expect(out.map((d) => d.world)).toEqual(items.map((i) => i.world_id));
    expect(out.map((d) => d.title)).toEqual(items.map((i) => i.card.what_happened));
    const keys = out.map((d) => d.k as string);
    expect(keys.every((k) => typeof k === "string" && k.length > 0)).toBe(true);
    expect(new Set(keys).size).toBe(4);
  });

  it("WIRE_3_decisionsFromCards_the_same_card_id_in_two_worlds_gets_two_keys", () => {
    const a = item(1, "needs_you", { world_id: "w_one" });
    const b = item(1, "needs_you", { world_id: "w_two" });
    const [da, db] = decisionsFromCards([
      { ...a, world_id: "w_one" },
      { ...b, world_id: "w_two" },
    ]);
    expect(da?.k).not.toBe(db?.k);
  });

  it("WIRE_3_decisionsFromCards_the_key_is_stable_across_calls", () => {
    const items = [item(1), item(2, "gate")];
    expect(decisionsFromCards(items).map((d) => d.k)).toEqual(
      decisionsFromCards(items).map((d) => d.k),
    );
  });

  it("WIRE_3_decisionsFromCards_never_mutates_its_input", () => {
    const items = deepFreeze([item(1), item(2, "gate"), item(3, "consent")]);
    const before = JSON.stringify(items);
    expect(() => decisionsFromCards(items)).not.toThrow();
    expect(JSON.stringify(items)).toBe(before);
  });

  it("WIRE_3_decisionsFromCards_property_one_decision_per_card_in_order_with_distinct_keys", () => {
    const kind = fc.constantFrom("needs_you", "meeting", "gate", "consent") as fc.Arbitrary<
      Card["kind"]
    >;
    const text = fc.string({ minLength: 1, maxLength: 60 });
    fc.assert(
      fc.property(
        fc.uniqueArray(fc.tuple(fc.integer({ min: 1, max: 40 }), fc.integer({ min: 1, max: 3 })), {
          selector: ([n, w]) => `${w}:${n}`,
          maxLength: 20,
        }),
        fc.array(fc.tuple(kind, text, text), { minLength: 20, maxLength: 20 }),
        (ids, texts) => {
          const items = ids.map(([n, w], i) => {
            const [k, what, why] = texts[i] as [Card["kind"], string, string];
            const base = item(n, k, { what_happened: what, why_it_matters: why });
            return { ...base, world_id: `w_${w}`, card: { ...base.card, world_id: `w_${w}` } };
          });
          const out = decisionsFromCards(deepFreeze(items));
          expect(out).toHaveLength(items.length);
          expect(out.map((d) => d.world)).toEqual(items.map((i) => i.world_id));
          expect(out.map((d) => d.title)).toEqual(items.map((i) => i.card.what_happened));
          expect(new Set(out.map((d) => d.k)).size).toBe(items.length);
          for (const d of out) {
            expect([d.icon, d.done, d.toast, d.approvedTitle]).toEqual(["", "", "", ""]);
          }
        },
      ),
      { numRuns: 60 },
    );
  });
});
