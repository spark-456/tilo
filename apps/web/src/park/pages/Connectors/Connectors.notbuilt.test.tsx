// @vitest-environment happy-dom
// WEB-11 honesty in deployed mode (plan 6.1 and section 10): with VITE_TILO_API_URL set the Park Api is
// the live one and every method rejects with NotBuilt. The page then shows the EmptyState "Not connected
// yet", never sample connectors as if real, and no "Sample data" chip (there is no sample to label).
// The env is stubbed before the page module is loaded, in this file only (one file, one module graph).
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  connectButtons,
  connectedTiles,
  flush,
  hasExactText,
  renderPage,
  textOf,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { connectors } from "../../api/fixtures";
import { testApp } from "./testApp";

beforeAll(() => {
  vi.stubEnv("VITE_TILO_API_URL", "http://127.0.0.1:9");
});
afterAll(() => {
  vi.unstubAllEnvs();
});
afterEach(cleanup);

describe("WEB_11_connectors_honesty: a NotBuilt endpoint is not sample data", () => {
  it("WEB_11_connectors_honesty_not_built_shows_Not_connected_yet_and_no_fixture_connectors", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const app = testApp();
    const m = await renderPage(app);
    await waitFor(() => hasExactText(m.container, "Not connected yet"), "the EmptyState");
    await flush();
    const text = textOf(m.container);
    for (const c of connectors)
      expect(text, `${c.name} must not appear as live`).not.toContain(c.name);
    expect(connectedTiles(m.container)).toHaveLength(0);
    expect(connectButtons(m.container)).toHaveLength(0);
    expect(hasExactText(m.container, "Sample data")).toBe(false);
    expect(text).not.toMatch(/\d+ connected/);
    expect(text).not.toContain("HubSpot sign-in expires");
    expect(app.toast).not.toHaveBeenCalled();
    expect(err.mock.calls, "a rejected NotBuilt is handled, not thrown").toEqual([]);
    err.mockRestore();
  });
});
