// WEB-9 test support: the Agenda page inside the shared `ParkProvider` (the real store, AppCtx and Api
// wrapper), with the fixture Api spied, a navigate spy and a scheduler that never fires by itself.
// Nothing here is bundled.
import { type ReactElement, act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { vi } from "vitest";
import type { Api } from "../../src/park/api/index";
import { ParkProvider, useApp, useParkStore } from "../../src/park/app/context";
import { AgendaPage } from "../../src/park/pages/Agenda/AgendaPage";
import { fakeApi, fakeScheduler } from "./appHarness";

export interface HarnessOpts {
  api?: Api;
  vw?: number;
  time?: "day" | "night";
}

function Host(): ReactElement {
  const app = useApp();
  return (
    <div data-park="" data-time={app.time}>
      <AgendaPage app={app} />
    </div>
  );
}

function Store({ bind }: { bind: (s: ReturnType<typeof useParkStore>) => void }): null {
  bind(useParkStore());
  return null;
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

/**
 * Mount the page on /park/agenda and wait for the Api result. Returns the container, the spied Api, the
 * navigate spy (receives the path `app.go` builds), the store's current toast message, and `decideFromOutside`
 * (another page approving through the shell store).
 */
export async function renderAgenda(opts: HarnessOpts = {}) {
  window.history.pushState({}, "", "/park/agenda");
  const spy = fakeApi();
  const api: Api = opts.api ?? spy;
  const navigate = vi.fn();
  const held: { store?: ReturnType<typeof useParkStore> } = {};
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() =>
    root.render(
      <ParkProvider
        api={api}
        navigate={navigate}
        schedule={fakeScheduler().schedule}
        viewport={{ vw: opts.vw ?? 1440, vh: 900 }}
      >
        <Store
          bind={(s) => {
            held.store = s;
          }}
        />
        <Host />
      </ParkProvider>,
    ),
  );
  roots.push({ root, container });
  if (opts.time) act(() => held.store?.setPref("time", opts.time));
  await settle();
  return {
    container,
    spy,
    navigate,
    toast: () => held.store?.getState().toast?.message,
    decideFromOutside: (k: "depot" | "mail") => act(() => held.store?.decide(k)),
  };
}

export async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}
