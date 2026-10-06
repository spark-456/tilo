// WEB-7 test support: a fake `app` (the README AppCtx) around the Ledger page. `decide` changes the host's
// own `dec`, like the shell's store does, so a test sees the page react. Nothing here is bundled.
import { type ReactElement, act, useState } from "react";
import { type Root, createRoot } from "react-dom/client";
import { vi } from "vitest";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import type { DecisionKey } from "../../api/types";
import { LedgerPage } from "./LedgerPage";
import type { AppCtx } from "./appCtx";

export interface Calls {
  go: ReturnType<typeof vi.fn>;
  decide: ReturnType<typeof vi.fn>;
  toast: ReturnType<typeof vi.fn>;
}

export interface HarnessOpts {
  api?: Api;
  vw?: number;
  time?: "day" | "night";
  prefs?: Record<string, unknown>;
}

function Host({ opts, calls }: { opts: HarnessOpts; calls: Calls }): ReactElement {
  const [dec, setDec] = useState<Partial<Record<DecisionKey, boolean>>>({});
  const [api] = useState(() => opts.api ?? createFixtureApi());
  const time = opts.time ?? "day";
  const app: AppCtx = {
    page: "ledger",
    params: {},
    go: (page, params) => calls.go(page, params),
    dec,
    decide: (key) => {
      calls.decide(key);
      setDec((d) => ({ ...d, [key]: true }));
    },
    needsLeft: 2,
    added: [],
    addWorld: () => {
      throw new Error("not used by the Ledger");
    },
    toast: (msg, label, action) => calls.toast(msg, label, action),
    time,
    night: time === "night",
    motion: "still",
    setPref: () => undefined,
    prefs: opts.prefs ?? {},
    vw: opts.vw ?? 1440,
    vh: 900,
    pins: [],
    ready: true,
  };
  return (
    <div data-park="" data-time={time}>
      <LedgerPage app={app} api={api} />
    </div>
  );
}

Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);

const roots: { root: Root; container: HTMLElement }[] = [];

/** Unmount every page mounted by renderLedger. Call from afterEach and between renders in one test. */
export function cleanup(): void {
  for (const { root, container } of roots.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
  document.body.replaceChildren();
}

function mount(ui: ReactElement): { container: HTMLElement } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => root.render(ui));
  roots.push({ root, container });
  return { container };
}

/** Mount the page, wait for the Api result, and return the container with the recorded calls. */
export async function renderLedger(opts: HarnessOpts = {}) {
  const calls: Calls = { go: vi.fn(), decide: vi.fn(), toast: vi.fn() };
  const m = mount(<Host opts={opts} calls={calls} />);
  await settle();
  return { ...m, calls };
}

export async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
