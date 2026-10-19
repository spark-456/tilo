// ADR35_L6c / FR_CON_02: a card that asks for fields has no tap on the Park Decisions page; it is typed on Needs you.
import type { Card } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { decisionsFromCards } from "./decisionsFromCards";

const asks = {
  id: "01".padEnd(26, "0"),
  world_id: "w_a",
  run_id: "r_a",
  kind: "needs_you",
  rung: "needs_you",
  header: { building: "B1", agent: "A_x" },
  what_happened: "Send: needs recipient.",
  why_it_matters: "Nothing is sent.",
  options: [
    { id: "provide", label: "Add it", suggested: true, irreversible: false },
    { id: "hold", label: "Hold", suggested: false, irreversible: false },
  ],
  add_context: false,
  actions: [],
  answer_channels: ["web"],
  created_at: "2026-10-09T09:00:00.000Z",
  timeout: 86400,
  safe_default: "hold",
  gate: null,
  consent: null,
} as unknown as Card;

describe("ADR35_L6c FR_CON_02 Park decisions for a fields card", () => {
  it("has no yes label, carries its card id for the form and says why only", () => {
    const [d] = decisionsFromCards([{ world_id: "w_a", card_id: asks.id, card: asks }]);
    expect(d?.yes).toBe("");
    expect(d?.provide).toEqual({ cardId: asks.id }); // ADR-0035 L6d: the form sits under it
    expect(d?.body).toBe("Nothing is sent.");
  });
});
