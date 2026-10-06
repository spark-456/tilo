// @vitest-environment happy-dom
// WEB-3b: usePageApp() is the `app` a page gets. `go('world', { id })` runs the loader; `go('world')` with no
// id has no world to open, so it goes to the worlds list (never to a default world).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import type { AppCtx } from "./AppCtx";
import { ParkProvider, usePageApp, useParkStore } from "./context";
import type { ParkStore } from "./store";

const seen = {} as { app: AppCtx; store: ParkStore };
function Probe() {
  seen.app = usePageApp();
  seen.store = useParkStore();
  return null;
}

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

function setup() {
  window.history.pushState({}, "", "/park/home");
  const navigate = vi.fn();
  mount(
    <ParkProvider
      api={fakeApi()}
      navigate={navigate}
      schedule={fakeScheduler().schedule}
      viewport={{ vw: 1280, vh: 720 }}
    >
      <Probe />
    </ParkProvider>,
  );
  return navigate;
}

describe("WEB_3b_pageapp: go('world')", () => {
  it("WEB_3b_pageapp_a_world_with_an_id_opens_through_the_loader", () => {
    const navigate = setup();
    act(() => seen.app.go("world", { id: "comp" }));
    expect(seen.store.getState().wl).toMatchObject({ id: "comp", step: 0 });
    expect(navigate).not.toHaveBeenCalled();
  });

  it("WEB_3b_pageapp_a_world_without_an_id_goes_to_the_worlds_list", () => {
    const navigate = setup();
    act(() => seen.app.go("world"));
    expect(navigate).toHaveBeenCalledWith("/park/worlds");
    expect(seen.store.getState().wl).toBeNull();
  });
});
