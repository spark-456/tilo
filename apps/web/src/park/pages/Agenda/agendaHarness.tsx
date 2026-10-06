// WEB-9 test support: a fake `app` (the README AppCtx) around the Agenda page. `decide` changes the host's
// own `dec`, like the shell's store does; `decideFromOutside` is another page approving (a test sees the
// Agenda react). Nothing here is bundled.
import { type ReactElement, act, useEffect, useState } from "react";
import { type Root, createRoot } from "react-dom/client";
import { vi } from "vitest";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import type { DecisionKey } from "../../api/types";
import { AgendaPage } from "./AgendaPage";
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
}

type Dec = Partial<Record<DecisionKey, boolean>>;

function Host({
  opts,
  calls,
  bind,
}: { opts: HarnessOpts; calls: Calls; bind: (f: (k: DecisionKey) => void) => void }): ReactElement {
  const [dec, setDec] = useState<Dec>({});
  const [api] = useState(() => opts.api ?? createFixtureApi());
  const time = opts.time ?? "day";
  useEffect(() => bind((key) => setDec((d) => ({ ...d, [key]: true }))), [bind]);
  const app: AppCtx = {
    page: "agenda",
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
      throw new Error("not used by the Agenda");
    },
    toast: (msg, label, action) => calls.toast(msg, label, action),
    time,
    night: time === "night",
    motion: "still",
    setPref: () => undefined,
    prefs: {},
    vw: opts.vw ?? 1440,
    vh: 900,
    pins: [],
    ready: true,
  };
  return (
    <div data-park="" data-time={time}>
      <AgendaPage app={app} api={api} />
    </div>
  );
}

Reflect.set(globalThis, "IS_REACT_ACT_ENVIRONMENT", true);

const roots: { root: Root; container: HTMLElement }[] = [];

/** Unmount every page mounted by renderAgenda. Call from afterEach and between renders in one test. */
export function cleanup(): void {
  for (const { root, container } of roots.splice(0)) {
    act(() => root.unmount());
    container.remove();
  }
  document.body.replaceChildren();
}

/** Mount the page, wait for the Api result, and return the container, the recorded calls and a way to approve from elsewhere. */
export async function renderAgenda(opts: HarnessOpts = {}) {
  const calls: Calls = { go: vi.fn(), decide: vi.fn(), toast: vi.fn() };
  let approve: (k: DecisionKey) => void = () => undefined;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() =>
    root.render(
      <Host
        opts={opts}
        calls={calls}
        bind={(f) => {
          approve = f;
        }}
      />,
    ),
  );
  roots.push({ root, container });
  await settle();
  return { container, calls, decideFromOutside: (k: DecisionKey) => act(() => approve(k)) };
}

export async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
