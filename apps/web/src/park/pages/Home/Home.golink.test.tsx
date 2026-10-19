// @vitest-environment happy-dom
// WEB-4: the Home links are real addresses, and only a plain left click is handled in the page. A click with
// Ctrl, Cmd, Shift or Alt, or with the middle button, is left to the browser (open in a new tab or window),
// so the page does not call `app.go` and the default action is not cancelled.
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  control,
  goCalls,
  mountHome,
  todayRegion,
} from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

/** Dispatches a click the way the browser would and returns whether its default action may proceed. */
function click(el: Element, init: MouseEventInit): boolean {
  let proceeded = true;
  act(() => {
    proceeded = el.dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true, ...init }),
    );
  });
  return proceeded;
}

describe("WEB_4_home_golink: modified clicks belong to the browser", () => {
  const MODIFIED: readonly [string, MouseEventInit][] = [
    ["ctrl", { ctrlKey: true }],
    ["cmd", { metaKey: true }],
    ["shift", { shiftKey: true }],
    ["alt", { altKey: true }],
    ["middle button", { button: 1 }],
  ];

  for (const [name, init] of MODIFIED) {
    it(`WEB_4_home_golink_${name.replace(" ", "_")}_click_is_left_to_the_browser`, async () => {
      const rig = await mountHome();
      const link = control(
        rig.el.querySelector('section[aria-label="Sample worlds"]') as HTMLElement,
        "All worlds",
      );
      expect(link.tagName).toBe("A");
      expect(click(link, init)).toBe(true);
      expect(goCalls(rig.app)).toBe(0);
    });
  }

  it("WEB_4_home_golink_a_plain_left_click_goes_through_app_go_and_is_cancelled", async () => {
    const rig = await mountHome();
    const link = control(
      rig.el.querySelector('section[aria-label="Sample worlds"]') as HTMLElement,
      "All worlds",
    );
    expect(click(link, { button: 0 })).toBe(false);
    expect(goCalls(rig.app)).toBe(1);
  });
});
