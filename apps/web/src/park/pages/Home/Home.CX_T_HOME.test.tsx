// @vitest-environment happy-dom
// CX_T_HOME: the Home assistant uses served Home data as optional context and sends through the existing Quick API.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q } from "../../../../test-support/park/componentsHarness";
import {
  clickEl,
  control,
  mountHome,
  settle,
  textOf,
} from "../../../../test-support/park/homeHarness";
import { liveSourced } from "../../../../test-support/park/liveHomeHarness";
import type { Api } from "../../api/index";
import { withQuickContext } from "./homeData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("CX_T_HOME Home assistant", () => {
  it("CX_T_HOME keeps selected served context within the Quick API character limit", () => {
    const contexts = [
      { id: "agenda", label: "Today’s agenda", detail: "🗓️".repeat(600) },
    ];
    const question = withQuickContext("Summarize my day", contexts, ["agenda"]);
    expect(Array.from(question)).toHaveLength(500);
    expect(question.startsWith("Summarize my day\n\nToday’s agenda: ")).toBe(true);
  });

  it("CX_T_HOME opens context chips from Home data and asks through Quick", async () => {
    const startWorld = vi.fn(async () => ({
      data: {
        kind: "answered",
        text: "Your day has two agenda items.",
        cost: null,
      },
      source: "live",
    }));
    const api = liveSourced({ startWorld } as unknown as Partial<Api>);
    const rig = await mountHome({ api });
    clickEl(control(rig.el, "Ask Tilo"));
    const panel = rig.el.querySelector<HTMLElement>('[aria-label="Ask Tilo"]');
    expect(panel).not.toBeNull();
    expect(textOf(panel!)).toContain("Recent worlds");
    expect(textOf(panel!)).toContain("Today’s agenda");
    expect(textOf(panel!)).toContain("Needs you");
    clickEl(control(panel!, "Today’s agenda"));
    const input = panel!.querySelector<HTMLInputElement>(
      'input[aria-label="Ask Tilo a question"]',
    );
    expect(input?.value).toContain("Today’s agenda");
    clickEl(q(panel!, 'button[aria-label="Send"]'));
    await settle();
    expect(startWorld).toHaveBeenCalledWith("quick", expect.stringContaining("Today’s agenda"), "quick");
    expect(textOf(panel!)).toContain("Your day has two agenda items.");
  });
});
