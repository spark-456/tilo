// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  makeApp,
  renderPage,
  spyApi,
  tileFor,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { connectors } from "../../api/fixtures";

afterEach(cleanup);

it("HR W23 missing connector account never invents a connection time in tile or drawer", async () => {
  const api = spyApi();
  const base = connectors[0];
  if (!base) throw new Error("connector fixture missing");
  const c = { ...base, acct: "" };
  api.getConnectors.mockResolvedValue({ data: [c], source: "fixture" });
  const { container } = await renderPage(makeApp(), api);
  await waitFor(() => !!tileFor(container, c.name), "connector tile");
  expect(container.textContent).toContain("Account not available");
  expect(container.textContent).not.toContain("Connected just now");
  const tile = tileFor(container, c.name);
  if (!tile) throw new Error("connector tile missing");
  click(tile);
  const drawer = container.querySelector('[role="dialog"]');
  expect(drawer?.textContent).toContain("Account not available");
  expect(drawer?.textContent).not.toContain("Connected just now");
});
