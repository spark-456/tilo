// ADR35_L6d / FR_CON_02: a live `provide` card can never be answered by a tap, on any Park surface.
import type { Card } from "@tilo/contracts";
import { describe, expect, it, vi } from "vitest";
import { activityGroups } from "../pages/Ledger/model";
import { decisionKey, decisionsFromCards } from "./live/decisionsFromCards";
import { ledgerFromCosts } from "./live/ledgerFromCosts";
import { createLiveApi } from "./liveApi";

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
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

describe("ADR35_L6d FR_CON_02 a provide card is never answered by a tap", () => {
  it("decide() on its key sends nothing: it is not an answerable key", async () => {
    const fetchMock = vi.fn(async (_url: string) =>
      json({ cards: [{ world_id: "w_a", card_id: asks.id, card: asks }], next_cursor: null }),
    );
    const api = createLiveApi({ baseUrl: BASE, fetch: fetchMock as unknown as typeof fetch });
    const { data } = await api.getDecisions();
    expect(data).toHaveLength(1);
    const key = decisionKey("w_a", asks.id);
    expect(data[0]?.k).toBe(key);
    await expect(api.decide(key)).rejects.toThrow();
    expect(fetchMock.mock.calls.every(([url]) => String(url).includes("/cards?limit"))).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1); // only the read; no POST
  });

  it("the Ledger Activity approve button needs a ledger entry's own key, which a live ledger never has", () => {
    const L = ledgerFromCosts({
      totals: { usd: 1.5 },
      by_profile: [{ usd: 1.5, profile: "fast" }],
      by_task_type: [],
    });
    expect(JSON.stringify(L)).not.toContain('"dec"'); // no entry names a decision
    const [provide] = decisionsFromCards([{ world_id: "w_a", card_id: asks.id, card: asks }]);
    const { groups } = activityGroups(L, {}, "all", provide ? [provide] : []);
    const rows = groups.flatMap((g) => g.rows);
    expect(rows.filter((r) => r.waiting || r.decKey)).toEqual([]);
  });
});
