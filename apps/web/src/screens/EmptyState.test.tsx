// @vitest-environment happy-dom
// #227 Bundle H1: one EmptyState (glyph, title, one line, at most one action) on S-06, S-07, S-12,
// S-13, S-14 and S-21. Each screen says what is true: nothing is recorded, so nothing is listed.
import { act } from "react";
import type { ComponentType, ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { S_06 } from "./S_06";
import { S_07 } from "./S_07";
import { S_12 } from "./S_12";
import { S_13 } from "./S_13";
import { S_14 } from "./S_14";
import { S_21 } from "./S_21";
import { EmptyState } from "./kit";
import type { ScreenProps } from "./routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A client whose run has recorded nothing yet. */
function quietClient(known = true): TiloClient {
  const client = new FixtureClient();
  client.subscribeEvents = () => () => undefined;
  if (!known) client.hasWorld = () => false;
  return client;
}

async function show(node: (client: TiloClient) => ReactNode, client: TiloClient) {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(<ClientProvider client={client}>{node(client)}</ClientProvider>);
  });
  await act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
  return container;
}

const screen = (Component: ComponentType<ScreenProps>, params: string[] = []) =>
  show(() => <Component params={params} />, quietClient());

afterEach(() => document.body.replaceChildren());

describe("#227 H1 EmptyState: the kit component", () => {
  it("has a decorative glyph, a title, one line and at most one action", async () => {
    const c = await show(
      () => (
        <EmptyState
          testid="e"
          title="Nothing yet"
          line="Say what is true."
          action={{ label: "Go", to: "/" }}
        />
      ),
      quietClient(),
    );
    const box = c.querySelector('[data-testid="e"]');
    expect(box?.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
    expect(box?.querySelector(".empty-title")?.textContent).toBe("Nothing yet");
    expect(box?.querySelector(".empty-line")?.textContent).toBe("Say what is true.");
    expect(box?.querySelectorAll("a, button")).toHaveLength(1);
    expect(box?.querySelector("a")?.getAttribute("href")).toBe("/");
  });

  it("without an action it has no control at all", async () => {
    const c = await show(() => <EmptyState testid="e" title="T" line="L" />, quietClient());
    expect(c.querySelectorAll("a, button")).toHaveLength(0);
  });
});

describe("#227 H1 EmptyState: each screen with nothing recorded", () => {
  const cases: Array<[string, ComponentType<ScreenProps>, string[], string, string]> = [
    ["S-06", S_06, [], "needs-empty", "Nothing needs you"],
    ["S-07", S_07, [], "gate-empty", "No gate yet"],
    ["S-12", S_12, ["w_village_basic"], "delivery-pending", "Nothing to deliver yet"],
    ["S-13", S_13, [], "library-empty", "Nothing delivered yet"],
    ["S-21", S_21, [], "history-empty", "No artifact yet"],
  ];
  for (const [id, Component, params, testid, title] of cases) {
    it(`${id} shows its EmptyState "${title}" with one action`, async () => {
      const c = await screen(Component, params);
      const box = c.querySelector(`[data-testid="${testid}"]`);
      expect(box, `${id} ${testid}`).not.toBeNull();
      expect(box?.querySelector(".empty-title")?.textContent).toBe(title);
      expect(box?.querySelectorAll("a, button")).toHaveLength(1);
      expect(c.querySelector(".empty-note")?.textContent ?? "").not.toContain("Nothing");
    });
  }

  it("S-13's memory note is the compact EmptyState, with no action", async () => {
    const c = await screen(S_13);
    const box = c.querySelector('[data-testid="memory-empty"]');
    expect(box?.getAttribute("data-compact")).toBe("true");
    expect(box?.querySelectorAll("a, button")).toHaveLength(0);
  });

  it("S-14 lists no world when the client knows none, and says so", async () => {
    const c = await show(() => <S_14 />, quietClient(false));
    const box = c.querySelector('[data-testid="worlds-empty"]');
    expect(box?.querySelector(".empty-title")?.textContent).toBe("No worlds yet");
    expect(c.querySelector('[data-testid="world-card"]')).toBeNull();
  });

  it("S-14 still shows the world's card when the client knows it", async () => {
    const c = await screen(S_14);
    expect(c.querySelector('[data-testid="worlds-empty"]')).toBeNull();
  });
});
