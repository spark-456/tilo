// ADR35_L6c / FR_CON_02: the HttpClient half of the fields route.
import type { Card } from "@tilo/contracts";
import { describe, expect, it, vi } from "vitest";
import { isFieldsApi } from "./fields";
import { FixtureClient } from "./fixtureClient";
import { CARDS_VALID } from "./fixtures/cards";
import { HttpClient, TiloApiError } from "./http";

const BASE = "https://api.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
function script(...replies: Response[]) {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = [];
  const fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const next = replies.shift();
    if (!next) throw new Error("unscripted call");
    return next;
  }) as unknown as typeof globalThis.fetch;
  return { calls, fetch };
}
const card: Card = { ...(CARDS_VALID[0] as Card), world_id: "w1" };

describe("ADR35_L6c FR_CON_02 HttpClient fields calls", () => {
  it("lists what is asked and posts the typed values to the card's world; the fixture client has no form", async () => {
    const { calls, fetch } = script(
      json([card]),
      json({ fields: [{ name: "subject", label: "Subject", hint: "h", max_length: 150 }] }),
      json({ outcome: "answered" }),
    );
    const c = new HttpClient({ baseUrl: BASE, fetch });
    expect(isFieldsApi(c)).toBe(true);
    expect(isFieldsApi(new FixtureClient())).toBe(false);
    await c.listCards("w1");
    expect(await c.getCardFields(card.id)).toEqual([
      { name: "subject", label: "Subject", hint: "h", maxLength: 150 },
    ]);
    expect(calls[1]?.url).toBe(`${BASE}/worlds/w1/cards/${card.id}/fields`);
    await c.supplyCardFields(card.id, { subject: "Q3" });
    expect(calls[2]?.url).toBe(`${BASE}/worlds/w1/cards/${card.id}/fields`);
    expect(calls[2]?.init?.method).toBe("POST");
    expect(JSON.parse(String(calls[2]?.init?.body))).toEqual({ fields: { subject: "Q3" } });
  });

  it("shows the API's plain 422 reason, and a card it never listed says so without a call", async () => {
    const reason = "the subject has line breaks or hidden characters";
    const { calls, fetch } = script(json([card]), json({ outcome: "rejected", reason }, 422));
    const c = new HttpClient({ baseUrl: BASE, fetch });
    await expect(c.supplyCardFields(card.id, { subject: "x" })).rejects.toBeInstanceOf(
      TiloApiError,
    );
    expect(calls).toHaveLength(0);
    await c.listCards("w1");
    await expect(c.supplyCardFields(card.id, { subject: "x" })).rejects.toMatchObject({
      message: reason,
      status: 422,
    });
  });

  it("a reply that is not the documented shape is unreadable, and an echoed address with markup is not shown", async () => {
    const { fetch } = script(
      json([card]),
      json({ fields: [{ name: "Bad Name" }] }),
      json({ outcome: "rejected", reason: "<b>x</b>" }, 422),
    );
    const c = new HttpClient({ baseUrl: BASE, fetch });
    await c.listCards("w1");
    await expect(c.getCardFields(card.id)).rejects.toMatchObject({ retryable: true });
    await expect(c.supplyCardFields(card.id, { subject: "x" })).rejects.toMatchObject({
      message: "Tilo could not accept that.",
    });
  });
});
