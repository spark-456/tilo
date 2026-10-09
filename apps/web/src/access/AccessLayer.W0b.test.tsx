// @vitest-environment happy-dom
// SEC-15 W0b (completion plan, 9 Oct): the access gate is enforced by the server (a Firestore AccessStore now backs it),
// so the web has to ask. `AccessLayer` sits between the sign-in gate and the apps on a deployment with an API: it
// reads `GET /access`, asks the sign-up question (`POST /access/declaration`) when the person has not answered, shows
// "under construction" to a visitor and the app only to a judge. It only shows what the server answered; it decides
// nothing, and it never renders the product behind a refusal. Component tests only.
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../api/http";
import { AccessLayer } from "./AccessLayer";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

const text = () => (container.textContent ?? "").replace(/\s+/g, " ");
const q = <T extends Element>(sel: string) => container.querySelector<T>(sel);
const settle = async () => {
  await act(async () => undefined);
  await act(async () => undefined);
};
const App = () => <div data-testid="app">the app</div>;
const access = (declaration: "visitor" | "judge" | null) => ({
  declaration,
  allowed: declaration === "judge",
  models: declaration === "judge" ? "replay" : null,
});

function http(
  get: () => Promise<unknown>,
  post: (body: unknown) => Promise<unknown> = async (b) => b,
) {
  return {
    getJson: vi.fn(async (_path: string) => get()),
    postJson: vi.fn(async (_p: string, b: unknown) => post(b)),
  };
}
const show = async (h: ReturnType<typeof http>) => {
  await act(async () => {
    root.render(
      <AccessLayer http={h}>
        <App />
      </AccessLayer>,
    );
  });
  await settle();
};

describe("SEC-15 W0b the access layer", () => {
  it("SEC-15 W0b nothing but a wait is shown until the server has answered, and /access is read once", async () => {
    let release: (v: unknown) => void = () => undefined;
    const h = http(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );
    await show(h);
    expect(q('[data-testid="app"]')).toBeNull();
    expect(h.getJson).toHaveBeenCalledTimes(1);
    expect(h.getJson).toHaveBeenCalledWith("/access");
    release(access("judge"));
    await settle();
    expect(q('[data-testid="app"]')).not.toBeNull();
  });

  it("SEC-15 W0b a judge gets the app", async () => {
    await show(http(async () => access("judge")));
    expect(q('[data-testid="app"]')).not.toBeNull();
    expect(q('[data-testid="sign-up-declaration"]')).toBeNull();
  });

  it("SEC-15 W0b a visitor is told Tilo is under construction and never sees the app", async () => {
    await show(http(async () => access("visitor")));
    expect(q('[data-testid="under-construction"]')).not.toBeNull();
    expect(q('[data-testid="app"]')).toBeNull();
  });

  it("SEC-15 W0b a person who has not answered is asked, and the answer is posted once, as the person's own choice", async () => {
    const h = http(
      async () => access(null),
      async () => access("judge"),
    );
    await show(h);
    expect(q('[data-testid="sign-up-declaration"]')).not.toBeNull();
    expect(q('[data-testid="app"]')).toBeNull();
    const judge = [...container.querySelectorAll<HTMLInputElement>('input[type="radio"]')].find(
      (i) => i.value === "judge",
    );
    await act(async () => judge?.click());
    await act(async () => q<HTMLFormElement>("form")?.requestSubmit());
    await settle();
    expect(h.postJson).toHaveBeenCalledTimes(1);
    expect(h.postJson).toHaveBeenCalledWith("/access/declaration", { declaration: "judge" });
    expect(q('[data-testid="app"]')).not.toBeNull();
  });

  it("SEC-15 W0b a refused or already recorded answer re-reads what the server holds instead of guessing", async () => {
    const reads = [access(null), access("visitor")];
    const h = http(
      async () => reads.shift(),
      async () => {
        throw new TiloApiError("locked", 409, false, true, "declaration_locked");
      },
    );
    await show(h);
    const visitor = [...container.querySelectorAll<HTMLInputElement>('input[type="radio"]')].find(
      (i) => i.value === "visitor",
    );
    await act(async () => visitor?.click());
    await act(async () => q<HTMLFormElement>("form")?.requestSubmit());
    await settle();
    expect(h.getJson).toHaveBeenCalledTimes(2);
    expect(q('[data-testid="under-construction"]')).not.toBeNull();
  });

  it("SEC-15 W0b when the server cannot be asked the app is not shown; a retry asks again", async () => {
    const reads: Array<() => Promise<unknown>> = [
      async () => {
        throw new TiloApiError("down", 503, true);
      },
      async () => access("judge"),
    ];
    const h = http(() => (reads.shift() as () => Promise<unknown>)());
    await show(h);
    expect(q('[data-testid="app"]')).toBeNull();
    expect(text()).toMatch(/could not check|try again/i);
    const retry = [...container.querySelectorAll("button")].find((b) =>
      /try again/i.test(b.textContent ?? ""),
    );
    await act(async () => retry?.click());
    await settle();
    expect(q('[data-testid="app"]')).not.toBeNull();
  });

  it("SEC-15 W0b the layer holds no password field and no free text", async () => {
    await show(http(async () => access(null)));
    expect(
      container.querySelectorAll('input[type="password"], input[type="text"], textarea'),
    ).toHaveLength(0);
  });
});
