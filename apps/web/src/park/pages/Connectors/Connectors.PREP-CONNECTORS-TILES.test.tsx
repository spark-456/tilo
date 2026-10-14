// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { makeApp, renderPage, spyApi } from "../../../../test-support/park/connectorsDom";
import { NotBuilt } from "../../api/liveApi";
import { partnerTilesEnabled } from "../../api/partnerTilesEnv";

function setPartnerTiles(value: string): void {
  const meta = document.createElement("meta");
  meta.name = "tilo-partner-tiles";
  meta.content = value;
  document.head.append(meta);
}

beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-10-14T13:00:00Z"));
});

afterEach(() => {
  cleanup();
  for (const meta of document.querySelectorAll('meta[name="tilo-partner-tiles"]')) meta.remove();
  vi.restoreAllMocks();
});

it("PREP-CONNECTORS-TILES defaults off unless explicitly enabled", () => {
  for (const value of [undefined, "", "false", "0", "1", "TRUE", true]) {
    expect(partnerTilesEnabled(value)).toBe(false);
  }
  expect(partnerTilesEnabled("true")).toBe(true);
});

for (const state of ["fixture", "live", "unavailable", "team"] as const) {
  it(`PREP-CONNECTORS-TILES flag off pins existing ${state} page exactly`, async () => {
    setPartnerTiles("false");
    const api = spyApi();
    if (state === "live") api.getConnectors.mockResolvedValue({ source: "live", data: [] });
    if (state === "unavailable") api.getConnectors.mockRejectedValue(new Error("unavailable"));
    if (state === "team") api.getConnectors.mockRejectedValue(new NotBuilt("getConnectors"));
    const { container } = await renderPage(makeApp(), api);
    expect(container.innerHTML).toMatchSnapshot();
  });
}

it("PREP-CONNECTORS-TILES explicit flag shows exact owner requirements without actions or extra reads", async () => {
  setPartnerTiles("true");
  const api = spyApi();
  api.getConnectors.mockResolvedValue({ source: "live", data: [] });
  const app = makeApp();
  const { container } = await renderPage(app, api);
  const section = container.querySelector('[aria-label="Partner preparation"]');
  expect(section).not.toBeNull();
  for (const name of ["Canva", "Slack", "Lovable"]) {
    expect(section?.textContent).toContain(`Needs the workspace owner's ${name} app`);
  }
  expect(section?.textContent).toContain("Lovable MCP");
  expect(section?.querySelectorAll(".park-card")).toHaveLength(3);
  expect(section?.querySelectorAll(".park-chip")).toHaveLength(3);
  expect(section?.querySelectorAll("button, a, input, form")).toHaveLength(0);
  expect(section?.textContent).not.toMatch(/connected|ready to use/i);
  expect(api.getConnectors).toHaveBeenCalledTimes(1);
  for (const [name, call] of Object.entries(api)) {
    if (name !== "getConnectors") expect(call, name).not.toHaveBeenCalled();
  }
  expect(app.toast).not.toHaveBeenCalled();
  expect(app.go).not.toHaveBeenCalled();
});
