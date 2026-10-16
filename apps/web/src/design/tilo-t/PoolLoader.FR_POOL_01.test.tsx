// @vitest-environment happy-dom
import { act, createElement } from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { settle } from "../../park/pages/Team/testApp";
import { PoolLoader } from "./PoolLoader";

afterEach(cleanup);

it("FR_POOL_01_task_loader_waits_for_world_started_and_names_world_planned", async () => {
  const mounted = mount(
    createElement(PoolLoader, {
      kind: "task",
      events: [],
      children: createElement("p", null, "World"),
    }),
  );
  await settle();
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();

  mounted.render(
    createElement(
      PoolLoader,
      {
        kind: "task",
        events: [{ type: "world.started" }],
        children: createElement("p", null, "World"),
      },
    ),
  );
  await settle();
  const status = mounted.container.querySelector('[role="status"]');
  expect(status?.getAttribute("aria-live")).toBe("polite");
  expect(mounted.container.querySelector('[aria-busy="true"]')).not.toBeNull();
  expect(status?.textContent).toContain("world.started");
  expect(status?.textContent).toContain("world.planned");
});

it("FR_POOL_01_site_loader_waits_300ms_before_showing", async () => {
  const mounted = mount(
    createElement(PoolLoader, {
      kind: "site",
      loading: true,
      children: createElement("p", null, "Home"),
    }),
  );
  await settle();
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();
  await act(async () => new Promise((resolve) => setTimeout(resolve, 310)));
  expect(mounted.container.querySelector('[role="status"]')).not.toBeNull();
  expect(mounted.container.querySelector('[aria-busy="true"]')).not.toBeNull();
});
