// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { join } from "node:path";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { declared, rulesOf } from "../../../../test-support/park/pageCss";
import { liveWorldsApi, mountWorld } from "../../../../test-support/park/worldHarness";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { HttpClient } from "../../../api/http";

vi.mock("../../../worldView/LiveStageEmbed", () => ({
  default: () => <div data-testid="live-stage-stub" />,
  LiveChat: () => null,
}));

afterEach(cleanup);

it("CX_WORLD_LAYOUT_1_places_the_work_sections_after_the_world_stage", async () => {
  const rows = EVENTS_VILLAGE_BASIC.map((event) => ({ ...event, world_id: "k1" }));
  const client = new HttpClient({
    baseUrl: "https://api.test",
    fetch: async () => new Response(JSON.stringify({ events: rows })),
    pollMs: 60_000,
  });
  const { el } = await mountWorld({ api: liveWorldsApi(), client });
  const header = el.querySelector(".park-world-head");
  const stage = el.querySelector(".park-world-top");
  const proposals = el.querySelector('[aria-label="Skill proposals"]');
  const teamItems = el.querySelector('[aria-label="Team work items"]');
  const addItem = el.querySelector('[aria-label="Add a work item"]');

  expect(header).not.toBeNull();
  expect(stage).not.toBeNull();
  expect(proposals).not.toBeNull();
  expect(teamItems).not.toBeNull();
  expect(addItem).not.toBeNull();
  expect(
    header?.compareDocumentPosition(stage as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    stage?.compareDocumentPosition(proposals as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    stage?.compareDocumentPosition(teamItems as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    stage?.compareDocumentPosition(addItem as Node) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it.each([1440, 390])("CX_WORLD_LAYOUT_1_offsets_convene_from_the_agent_count_at_%i_px", (vw) => {
  const root = document.createElement("div");
  root.setAttribute("data-park", "");
  root.innerHTML =
    '<div class="park-world-map--live"><div class="park-world-tag"></div><div class="park-world-livestage"><button class="tw-convene"></button></div></div>';
  const tag = root.querySelector(".park-world-tag") as HTMLDivElement;
  const button = root.querySelector(".tw-convene") as HTMLButtonElement;
  const rules = rulesOf(join(__dirname, "World.css"), vw);
  const tagStyle = declared(tag, rules);
  const buttonStyle = declared(button, rules);

  const tagHeight = Number.parseFloat(tagStyle.get("height") ?? "");
  const tagMinHeight = Number.parseFloat(tagStyle.get("min-height") ?? "");
  const tagBottom =
    Number.parseFloat(tagStyle.get("top") ?? "0") +
    Math.max(
      Number.isFinite(tagHeight) ? tagHeight : 0,
      Number.isFinite(tagMinHeight) ? tagMinHeight : 0,
    );
  const buttonTop = Number.parseFloat(buttonStyle.get("top") ?? "0");
  expect(buttonStyle.get("left")).toBe("20px");
  expect(buttonTop).toBeGreaterThanOrEqual(tagBottom);
});
