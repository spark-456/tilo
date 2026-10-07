// @vitest-environment happy-dom
// WEB-3a: ParkProvider, useParkApi and useApp (plan section 10 "Plugging in"; README "The `app` prop").
// Pinned surface, park/app/context.tsx:
//   ParkProvider(props: { api?: Api; navigate?: (to: string) => void; schedule?: Schedule;
//                         viewport?: { vw: number; vh: number }; children: ReactNode })
//   useParkApi(): Api      every resolved result calls store.noteSource(result.source); rejections pass through
//   useApp(): AppCtx       store + route + viewport; `pins: []` and `ready: true` for now
//   useParkStore(): ParkStore
// With no `viewport` the window size is used and follows `resize`; with no `api`, parkApi(import.meta.env).
import { type ReactElement, act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { decisions } from "../api/fixtures/decisions";
import { API_METHODS, type Api } from "../api/index";
import { NotBuilt } from "../api/liveApi";
import type { AppCtx } from "./AppCtx";
import { ParkProvider, useApp, useParkApi, useParkStore } from "./context";
import type { ParkStore } from "./store";

interface Seen {
  app: AppCtx;
  api: Api;
  store: ParkStore;
  renders: number;
}
const seen = {} as Seen;

function Probe() {
  seen.app = useApp();
  seen.api = useParkApi();
  seen.store = useParkStore();
  seen.renders += 1;
  return <output data-testid="probe">{`${seen.app.page}|${seen.app.needsLeft}`}</output>;
}

const flush = () => act(async () => undefined);

function setup(path = "/park/home", extra: Partial<Parameters<typeof ParkProvider>[0]> = {}) {
  window.history.pushState({}, "", path);
  const api = fakeApi();
  const navigate = vi.fn();
  const sch = fakeScheduler();
  const tree = (viewport = { vw: 1280, vh: 720 }): ReactElement => (
    <ParkProvider
      api={api}
      navigate={navigate}
      schedule={sch.schedule}
      viewport={viewport}
      {...extra}
    >
      <Probe />
    </ParkProvider>
  );
  const m = mount(tree());
  return { api, navigate, sch, m, tree };
}

beforeEach(() => {
  seen.renders = 0;
});
afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

describe("WEB_3a_context: useApp builds the AppCtx", () => {
  it("WEB_3a_context_useApp_reads_page_and_params_from_the_url", () => {
    setup("/park/skills?id=sk2");
    expect(seen.app.page).toBe("skills");
    expect(seen.app.params).toEqual({ id: "sk2" });
  });

  it("WEB_3a_context_useApp_world_id_comes_from_the_path", () => {
    setup("/park/world/k1");
    expect(seen.app.page).toBe("world");
    expect(seen.app.params).toEqual({ id: "k1" });
  });

  it("WEB_3a_context_useApp_starts_with_the_prototypes_state_and_the_injected_viewport", () => {
    setup();
    expect(seen.app).toMatchObject({
      page: "home",
      params: {},
      dec: {},
      needsLeft: 2,
      added: [],
      prefs: {},
      time: "day",
      night: false,
      motion: "calm",
      vw: 1280,
      vh: 720,
      pins: [],
      ready: true,
    });
    for (const fn of ["go", "decide", "addWorld", "toast", "setPref"] as const) {
      expect(typeof seen.app[fn]).toBe("function");
    }
  });

  it("WEB_3a_context_decide_updates_dec_needsLeft_and_shows_the_toast", () => {
    const { api } = setup();
    seen.store.setDecisions(decisions); // the shell does this once the Api has returned them (WEB-3b)
    act(() => seen.app.decide("depot"));
    expect(seen.app.dec.depot).toBe(true);
    expect(seen.app.needsLeft).toBe(1);
    expect(api.decide).toHaveBeenCalledWith("depot");
    expect(seen.store.getState().toast?.message).toBe("Approved £3,420 for Laptop Depot");
    expect(document.querySelector('[data-testid="probe"]')?.textContent).toBe("home|1");
  });

  it("WEB_3a_context_undo_through_the_toast_action_restores_needsLeft", () => {
    setup();
    act(() => seen.app.decide("depot"));
    act(() => seen.store.getState().toast?.action?.());
    expect(seen.app.dec.depot).toBe(false);
    expect(seen.app.needsLeft).toBe(2);
  });

  it("WEB_3a_context_go_navigates_through_the_injected_navigate", () => {
    const { navigate } = setup();
    act(() => seen.app.go("ledger"));
    act(() => seen.app.go("world", { id: "k1" }));
    expect(navigate).toHaveBeenNthCalledWith(1, "/park/ledger");
    expect(navigate).toHaveBeenNthCalledWith(2, "/park/world/k1");
  });

  it("WEB_3a_context_go_without_an_injected_navigate_pushes_the_path_and_updates_the_page", () => {
    window.history.pushState({}, "", "/park/home");
    mount(
      <ParkProvider api={fakeApi()} viewport={{ vw: 1280, vh: 720 }}>
        <Probe />
      </ParkProvider>,
    );
    act(() => seen.app.go("agenda"));
    expect(window.location.pathname).toBe("/park/agenda");
    expect(seen.app.page).toBe("agenda");
  });

  it("WEB_3a_context_setPref_night_gives_time_night_and_night_true", () => {
    setup();
    act(() => seen.app.setPref("time", "night"));
    expect(seen.app.time).toBe("night");
    expect(seen.app.night).toBe(true);
    act(() => seen.app.setPref("motion", "still"));
    expect(seen.app.motion).toBe("still");
    expect(seen.app.prefs).toEqual({ time: "night", motion: "still" });
  });

  it("WEB_3a_context_addWorld_returns_the_world_and_adds_it_to_added", () => {
    setup();
    let w: ReturnType<AppCtx["addWorld"]> | undefined;
    act(() => {
      w = seen.app.addWorld("quick", "Order lunch");
    });
    expect(w?.id).toBe("new1");
    expect(seen.app.added.map((x) => x.id)).toEqual(["new1"]);
  });

  it("WEB_3a_context_toast_from_a_page_reaches_the_store", () => {
    const { sch } = setup();
    act(() => seen.app.toast("Saved", "Open", () => undefined));
    expect(seen.store.getState().toast).toMatchObject({ message: "Saved", actionLabel: "Open" });
    expect(sch.schedule).toHaveBeenCalledWith(expect.any(Function), 4200);
  });

  it("WEB_3a_context_the_app_object_is_stable_while_nothing_changes", () => {
    const { m, tree } = setup();
    const first = seen.app;
    m.render(tree({ vw: 1280, vh: 720 }));
    expect(seen.app).toBe(first);
    act(() => seen.store.markRead());
    expect(seen.app).toBe(first); // `read` is not part of AppCtx
  });

  it("WEB_3a_context_a_new_viewport_changes_vw_and_vh", () => {
    const { m, tree } = setup();
    m.render(tree({ vw: 390, vh: 844 }));
    expect(seen.app.vw).toBe(390);
    expect(seen.app.vh).toBe(844);
  });

  it("WEB_3a_context_without_a_viewport_prop_the_window_size_is_used_and_follows_resize", () => {
    window.history.pushState({}, "", "/park/home");
    const hd = (
      window as unknown as { happyDOM: { setViewport(v: { width: number; height: number }): void } }
    ).happyDOM;
    hd.setViewport({ width: 800, height: 600 });
    mount(
      <ParkProvider api={fakeApi()}>
        <Probe />
      </ParkProvider>,
    );
    expect(seen.app.vw).toBe(800);
    expect(seen.app.vh).toBe(600);
    act(() => {
      hd.setViewport({ width: 1024, height: 700 });
      window.dispatchEvent(new Event("resize"));
    });
    expect(seen.app.vw).toBe(1024);
    expect(seen.app.vh).toBe(700);
  });

  it("WEB_3a_context_the_page_follows_popstate", () => {
    setup("/park/home");
    act(() => {
      window.history.pushState({}, "", "/park/team?focus=share");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(seen.app.page).toBe("team");
    expect(seen.app.params).toEqual({ focus: "share" });
  });
});

describe("WEB_3a_context: useParkApi notes where every result came from", () => {
  it("WEB_3a_context_the_default_api_is_the_fixture_api", async () => {
    window.history.pushState({}, "", "/park/home");
    mount(
      <ParkProvider>
        <Probe />
      </ParkProvider>,
    );
    const r = await seen.api.getUser();
    await flush();
    expect(r.source).toBe("fixture");
    expect(seen.store.getState().sources).toEqual({ fixture: true, live: false });
  });

  it("WEB_3a_context_nothing_is_noted_before_the_first_result", () => {
    setup();
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: false });
  });

  it("WEB_3a_context_a_live_result_is_noted_as_live", async () => {
    const api = fakeApi();
    const live = {
      ...api,
      getToday: () => Promise.resolve({ data: { a: 1 }, source: "live" as const }),
    } as unknown as Api;
    window.history.pushState({}, "", "/park/home");
    mount(
      <ParkProvider api={live}>
        <Probe />
      </ParkProvider>,
    );
    await seen.api.getToday();
    await flush();
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: true });
  });

  it("WEB_3a_context_the_wrapped_api_has_every_method_and_returns_the_same_data", async () => {
    const { api } = setup();
    for (const m of API_METHODS) expect(typeof seen.api[m]).toBe("function");
    const direct = await api.getDecisions();
    const wrapped = await seen.api.getDecisions();
    expect(wrapped.source).toBe("fixture");
    expect(wrapped.data).toEqual(direct.data);
  });

  it("WEB_3a_context_arguments_reach_the_underlying_api", async () => {
    const { api } = setup();
    await seen.api.decide("mail");
    expect(api.decide).toHaveBeenCalledWith("mail");
    await seen.api.setPref("backup", "p2");
    expect(api.setPref).toHaveBeenCalledWith("backup", "p2");
  });

  it("WEB_3a_context_a_NotBuilt_rejection_passes_through_unchanged", async () => {
    const err = new NotBuilt("getLedger");
    const api = { ...fakeApi(), getLedger: () => Promise.reject(err) } as unknown as Api;
    window.history.pushState({}, "", "/park/home");
    mount(
      <ParkProvider api={api}>
        <Probe />
      </ParkProvider>,
    );
    await expect(seen.api.getLedger()).rejects.toBe(err);
    await flush();
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: false });
  });
});
