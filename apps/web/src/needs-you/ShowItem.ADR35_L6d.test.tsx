// @vitest-environment happy-dom
// ADR35_L6d / FR_CON_02: "Show me" on the gate sheet reads the owner-only item route and draws the document as text.
import type { Card, Event } from "@tilo/contracts";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GATE_REPLY, requested, resolved } from "../../test-support/needsYou";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { HttpClient, TiloApiError } from "../api/http";
import { type ItemApi, pinnedItemOf } from "../api/item";
import { GateSheet } from "./GateSheet";
import { gatesOf } from "./gates";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});
async function draw(node: React.ReactElement): Promise<HTMLElement> {
  const c = document.createElement("div");
  document.body.append(c);
  root = createRoot(c);
  await act(async () => root?.render(node));
  return c;
}

const card: Card = { ...GATE_REPLY, actions: ["show_me"] } as Card;
const sheet = (item: ItemApi | null, c: Card = card, events: Event[] = [requested(1)]) => {
  const record = gatesOf(events)[0];
  if (!record) throw new Error("no gate");
  return (
    <GateSheet record={record} card={c} layout={LAYOUT_VILLAGE_BASIC} answer={null} item={item} />
  );
};
const showMe = (c: HTMLElement) =>
  c.querySelector<HTMLButtonElement>("button[aria-controls]") ?? undefined;
const click = (c: HTMLElement) =>
  act(async () => {
    showMe(c)?.click();
  });
const email = (over: object = {}) => ({
  document: JSON.stringify({ kind: "email", subject: "Q3 note", body_text: "Hello team", ...over }),
  recipients: ["a@example.org"],
});

describe("ADR35_L6d FR_CON_02 the gate sheet's Show me", () => {
  it("fetches nothing until pressed, then shows the email as text with its recipients", async () => {
    const getCardItem = vi.fn(async () => email());
    const c = await draw(sheet({ getCardItem }));
    expect(getCardItem).not.toHaveBeenCalled();
    await click(c);
    expect(getCardItem).toHaveBeenCalledExactlyOnceWith(card.id);
    expect(c.querySelector('[aria-label="Email"]')?.textContent).toContain("Q3 note");
    expect(c.querySelector('[aria-label="Email"]')?.textContent).toContain("a@example.org");
    expect(c.querySelector("pre")?.textContent).toBe("Hello team");
    expect(showMe(c)?.textContent).toBe("Hide it");
    await click(c);
    expect(c.querySelector("pre")).toBeNull();
  });

  it("renders injected markup, links and bidi controls as plain text, never as elements", async () => {
    const body =
      '<img src=x onerror="alert(1)"><a href="javascript:alert(1)">go</a>\u202eevil\u2066';
    const c = await draw(
      sheet({ getCardItem: async () => email({ subject: "<b>bold</b>", body_text: body }) }),
    );
    await click(c);
    expect(c.querySelector("pre img, pre a, dl b, img, script")).toBeNull();
    expect(c.querySelector("pre")?.textContent).toBe(
      '<img src=x onerror="alert(1)"><a href="javascript:alert(1)">go</a>evil',
    );
    expect(c.querySelector("dd")?.textContent).toBeTruthy();
  });

  it("says a fixed sentence when the route refuses, and lets the person try again", async () => {
    let fail = true;
    const getCardItem = vi.fn(async () => {
      if (fail) throw new TiloApiError("SECRET reason text", 409, false);
      return email();
    });
    const c = await draw(sheet({ getCardItem }));
    await click(c);
    const alert = c.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("cannot be shown right now");
    expect(c.textContent).not.toContain("SECRET");
    expect(showMe(c)?.textContent).toBe("Show me");
    fail = false;
    await click(c);
    expect(c.querySelector('[role="alert"]')).toBeNull();
    expect(c.querySelector("pre")?.textContent).toBe("Hello team");
  });

  it("is a labelled, keyboard-reachable disclosure controlling a live region", async () => {
    const c = await draw(sheet({ getCardItem: async () => email() }));
    const button = showMe(c);
    expect(button?.getAttribute("aria-expanded")).toBe("false");
    expect(
      document
        .getElementById(button?.getAttribute("aria-controls") ?? "")
        ?.getAttribute("aria-live"),
    ).toBe("polite");
    await click(c);
    expect(showMe(c)?.getAttribute("aria-expanded")).toBe("true");
  });

  it("shows nothing new offline (no item api), once decided, or on a card that pins no item", async () => {
    const offline = await draw(sheet(null));
    expect(showMe(offline)).toBeUndefined();
    expect(offline.textContent).toContain("Show me"); // the old disabled placeholder is unchanged
    const api = { getCardItem: async () => email() };
    const decided = await draw(sheet(api, card, [requested(1), resolved(2, "approve")]));
    expect(showMe(decided)).toBeUndefined();
    const noItem = {
      ...card,
      gate: { ...card.gate, action: { ...card.gate?.action, item: undefined } },
    } as unknown as Card;
    expect(showMe(await draw(sheet(api, noItem)))).toBeUndefined();
  });
});

describe("ADR35_L6d FR_CON_02 the item reply", () => {
  it("takes the three kinds, keeps the recipients apart and refuses anything else", () => {
    expect(pinnedItemOf({ kind: "email", subject: "s", recipients: ["a@x.org"] })).toEqual({
      document: '{"kind":"email","subject":"s"}',
      recipients: ["a@x.org"],
    });
    expect(pinnedItemOf({ kind: "calendar_event", title: "t" })?.recipients).toEqual([]);
    for (const bad of [
      null,
      [],
      "x",
      { kind: "other" },
      { subject: "s" },
      { kind: "email", recipients: [1] },
    ])
      expect(pinnedItemOf(bad)).toBeNull();
    expect(pinnedItemOf({ kind: "email", body_text: "x".repeat(70_000) })).toBeNull();
  });

  it("HttpClient reads GET /worlds/{id}/cards/{cid}/item for the world the card came from", async () => {
    const seen: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      seen.push(url);
      return new Response(
        JSON.stringify({ kind: "email", subject: "s", body_text: "b", recipients: [] }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    });
    const http = new HttpClient({
      baseUrl: "https://api.example.test",
      fetch: fetchMock as unknown as typeof fetch,
    });
    await expect(http.getCardItem("c9")).rejects.toThrow(/card list/); // unknown card: no request
    expect(seen).toEqual([]);
    const item = await http.cardsOf("w/1").getCardItem("c 9");
    expect(seen).toEqual(["https://api.example.test/worlds/w%2F1/cards/c%209/item"]);
    expect(JSON.parse(item.document)).toEqual({ kind: "email", subject: "s", body_text: "b" });
  });
});
