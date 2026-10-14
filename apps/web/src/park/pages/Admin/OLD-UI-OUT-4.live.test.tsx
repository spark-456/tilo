// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { ClientProvider } from "../../../api/ClientProvider";
import type { TiloClient } from "../../../api/client";
import { forgetWorld } from "../../../world/lastWorld";
import { RunSectionView } from "./RunSections";
afterEach(cleanup);
it("OLD-UI-OUT-4 live account without a run never requests sample data", async () => {
  forgetWorld();
  window.history.replaceState({}, "", "/settings?section=autonomy");
  const subscribeEvents = vi.fn();
  const getLayout = vi.fn();
  const getDelivery = vi.fn();
  const client = { subscribeEvents, getLayout, getDelivery } as unknown as TiloClient;
  const m = mount(
    <ClientProvider client={client}>
      <RunSectionView section="autonomy" />
    </ClientProvider>,
  );
  await act(async () => undefined);
  expect(m.container.textContent).toContain("No run yet.");
  expect(subscribeEvents).not.toHaveBeenCalled();
  expect(getLayout).not.toHaveBeenCalled();
  expect(getDelivery).not.toHaveBeenCalled();
});
