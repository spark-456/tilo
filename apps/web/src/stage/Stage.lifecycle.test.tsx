// @vitest-environment jsdom
//
// PRD-9.7/PRD-18.2: mounting and unmounting the Stage — including mid-init,
// before PixiJS's async `Application.init()` resolves — must not throw and
// must not leave a stray canvas behind. `pixi.js` is mocked so the test
// controls exactly when "init" resolves relative to unmount, which a real
// WebGL context (and jsdom, which has none) cannot do deterministically.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Tells React this environment supports `act()` (jsdom via a custom vitest
// environment, not react-dom/test-utils' own auto-detection).
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { deferredInits, destroySpy } = vi.hoisted(() => ({
  deferredInits: [] as Array<() => void>,
  destroySpy: vi.fn(),
}));

vi.mock("pixi.js", () => {
  class Graphics {
    clear() {
      return this;
    }
    moveTo() {
      return this;
    }
    lineTo() {
      return this;
    }
    closePath() {
      return this;
    }
    stroke() {
      return this;
    }
  }
  class Application {
    canvas = document.createElement("canvas");
    ticker = { stop: vi.fn() };
    stage = { addChild: vi.fn() };
    renderer = { resize: vi.fn(), render: vi.fn() };
    init() {
      return new Promise<void>((resolve) => {
        deferredInits.push(resolve);
      });
    }
    destroy(...args: unknown[]) {
      destroySpy(...args);
    }
  }
  return { Application, Graphics };
});

// Imported after the mock is declared; vitest hoists `vi.mock` above this.
const { Stage } = await import("./Stage");

// Two microtask turns is enough for the chained `app.init().then(cb1)` (and,
// on unmount, the cleanup's further `.then(cb2)` on that same promise) to run.
const flushMicrotasks = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

/** Pops the resolver for the Stage's (single, per-test) `Application.init()`
 * call, without a `!` non-null assertion (forbidden by this repo's Biome
 * config — see e2e/support/assertions.ts). */
function takeInitResolver(): () => void {
  const resolve = deferredInits.shift();
  if (!resolve) throw new Error("expected a pending Application.init() to resolve");
  return resolve;
}

beforeEach(() => {
  deferredInits.length = 0;
  destroySpy.mockClear();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
    (() => ({})) as unknown as typeof HTMLCanvasElement.prototype.getContext,
  );
  // jsdom has no matchMedia; the Stage reads `prefers-reduced-motion` via it.
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("PRD-9.7/PRD-18.2 Stage lifecycle", () => {
  it("unmounting before init() resolves destroys the app exactly once, with no thrown error and no leftover canvas", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    let root!: Root;

    act(() => {
      root = createRoot(container);
      root.render(<Stage />);
    });
    expect(deferredInits).toHaveLength(1);

    expect(() => {
      act(() => {
        root.unmount();
      });
    }).not.toThrow();

    // init() resolves only now, after the component is already gone.
    await act(async () => {
      const resolveInit = takeInitResolver();
      expect(() => resolveInit()).not.toThrow();
      await flushMicrotasks();
    });

    expect(destroySpy).toHaveBeenCalledTimes(1);
    expect(container.querySelector("canvas")).toBeNull();

    document.body.removeChild(container);
  });

  it("an ordinary unmount after init() resolved destroys the app exactly once, with no leftover canvas", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    let root!: Root;

    act(() => {
      root = createRoot(container);
      root.render(<Stage />);
    });

    await act(async () => {
      takeInitResolver()();
      await flushMicrotasks();
    });
    expect(container.querySelector("canvas")).not.toBeNull();

    await act(async () => {
      root.unmount();
      await flushMicrotasks();
    });

    expect(destroySpy).toHaveBeenCalledTimes(1);
    expect(container.querySelector("canvas")).toBeNull();

    document.body.removeChild(container);
  });
});
