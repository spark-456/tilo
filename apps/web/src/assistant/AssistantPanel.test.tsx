// @vitest-environment happy-dom
// FR-PA-12 / FR-PA-18 (docs/prd-addendum-people-agents.md): the assistant panel shell. A launcher on
// every screen opens a panel (side panel on desktop, bottom sheet on a phone) that shows the
// context of the screen as a chip, traps focus, closes on Esc and gives focus back, and keeps its
// open state for the session. Answers come from an adapter; the fixture adapter says it is a
// preview and invents nothing.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantLauncher } from "./AssistantLauncher";
import { AssistantPanel } from "./AssistantPanel";
import type { AssistantAdapter } from "./adapter";
import { fixtureAdapter } from "./adapter";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;

async function mount(adapter?: AssistantAdapter) {
  await act(async () => {
    root.render(
      <>
        <AssistantLauncher />
        <AssistantPanel {...(adapter ? { adapter } : {})} />
      </>,
    );
  });
}
const launcher = () => document.querySelector<HTMLButtonElement>('[data-testid="assistant-open"]');
const dialog = () => document.querySelector<HTMLElement>("dialog[open]");
const go = async (path: string) =>
  act(async () => {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
const press = async (key: string, opts: KeyboardEventInit = {}) =>
  act(async () => {
    (document.activeElement ?? document.body).dispatchEvent(
      new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...opts }),
    );
  });

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.pushState({}, "", "/");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("FR-PA-12 assistant panel shell", () => {
  it("is closed until asked, and the launcher says what it opens", async () => {
    await mount();
    expect(dialog()).toBeNull();
    expect(launcher()?.textContent).toBe("Ask Tilo");
    expect(launcher()?.getAttribute("aria-expanded")).toBe("false");
  });

  it("opens as a named dialog with the screen's context as a chip, focus inside", async () => {
    await mount();
    await act(async () => launcher()?.click());
    expect(dialog()?.getAttribute("aria-label")).toBe("Assistant");
    expect(dialog()?.getAttribute("aria-modal")).toBe("true");
    expect(launcher()?.getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector('[data-testid="assistant-context"]')?.textContent).toBe(
      "You are on: Start",
    );
    expect(dialog()?.contains(document.activeElement)).toBe(true);
  });

  it("follows the screen: the chip names the screen the person is on", async () => {
    await mount();
    await act(async () => launcher()?.click());
    await go("/library");
    expect(document.querySelector('[data-testid="assistant-context"]')?.textContent).toBe(
      "You are on: Library",
    );
    await go("/world/w_village_basic/delivery");
    expect(document.querySelector('[data-testid="assistant-context"]')?.textContent).toContain(
      "Delivery",
    );
  });

  it("Esc closes it and focus goes back to the launcher", async () => {
    await mount();
    await act(async () => launcher()?.click());
    await press("Escape");
    expect(dialog()).toBeNull();
    expect(document.activeElement).toBe(launcher());
  });

  it("traps focus: Tab from the last control wraps to the first, Shift+Tab the other way", async () => {
    await mount();
    await act(async () => launcher()?.click());
    const items = [
      ...(dialog()?.querySelectorAll<HTMLElement>("button, input, textarea, a[href]") ?? []),
    ].filter((el) => !el.hasAttribute("disabled"));
    const [first, last] = [items[0], items[items.length - 1]];
    expect(items.length).toBeGreaterThan(1);
    await act(async () => last?.focus());
    await press("Tab");
    expect(document.activeElement).toBe(first);
    await press("Tab", { shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("keeps its open state for the session", async () => {
    await mount();
    await act(async () => launcher()?.click());
    act(() => root.unmount());
    root = createRoot(container);
    await mount();
    expect(dialog()).not.toBeNull();
    await press("Escape");
    act(() => root.unmount());
    root = createRoot(container);
    await mount();
    expect(dialog()).toBeNull();
  });

  it("sends a question to the adapter with the context and shows the question and the answer", async () => {
    const ask = vi.fn(async () => ({ text: "Two things are waiting for you.", sources: [] }));
    await mount({ ask });
    await act(async () => launcher()?.click());
    const input = dialog()?.querySelector<HTMLInputElement>("input") as HTMLInputElement;
    await act(async () => {
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      set?.call(input, "What is waiting for me?");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      dialog()
        ?.querySelector("form")
        ?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(ask).toHaveBeenCalledWith(
      "What is waiting for me?",
      expect.objectContaining({ label: "Start" }),
    );
    const log = dialog()?.querySelector('[role="log"]');
    expect(log?.textContent).toContain("What is waiting for me?");
    expect(log?.textContent).toContain("Two things are waiting for you.");
    expect(input.value).toBe("");
  });

  it("the fixture adapter says it is a preview and answers nothing it does not know", async () => {
    const reply = await fixtureAdapter.ask("What is on my plate?", {
      label: "My plate",
      route: "/plate",
      record: null,
    });
    expect(reply.text).toMatch(/preview/i);
    expect(reply.text).toMatch(/not connected/i);
    expect(reply.sources).toEqual([]);
  });
});
