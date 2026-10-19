// @vitest-environment happy-dom
// WEB-11 honesty in deployed mode (plan 6.1 and section 10): the live Api rejects every method with NotBuilt.
// The page, given that Api through <ParkProvider api={createLiveApi()}>, shows the EmptyState "Not connected
// yet" and never sample connectors as if real. (The "Sample data" chip is the shell's, not the page's.)
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  connectButtons,
  connectedTiles,
  flush,
  hasExactText,
  makeApp,
  renderPage,
  textOf,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { HttpClient } from "../../../api/http";
import { connectors } from "../../api/fixtures";
import { createLiveApi } from "../../api/liveApi";

afterEach(cleanup);

describe("WEB_11_connectors_honesty: a NotBuilt endpoint is not sample data", () => {
  it("W_COPY_1_FR_ACC_03_unavailable_data_never_promises_a_connection", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const app = makeApp();
    // Deployed mode has an HTTP run client and no run yet. The default fixture client would add the sample run's
    // connections ("Gmail: Connected") after its async layout read, so the assertion below raced that read
    // (it passed alone and failed in the slower Cloud Build gate, GATE-WEB-REDS-2).
    const run = new HttpClient({
      baseUrl: "https://api.example.test",
      fetch: async () => new Response("{}", { status: 404 }),
    });
    const m = await renderPage(app, createLiveApi(), "day", run);
    await waitFor(
      () => hasExactText(m.container, "Connector data is unavailable"),
      "the EmptyState",
    );
    await flush();
    const text = textOf(m.container);
    expect(text).toContain("The connector list is unavailable. No connection status can be shown.");
    expect(text).not.toContain("once this workspace is connected");
    expect(text).not.toContain("Sample recorded run");
    expect(text).toContain("No run yet");
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
