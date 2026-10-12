// @vitest-environment happy-dom
// FR-CHN-17d: the "Browser notifications" control. Absent without a live flow; off by default; honest words.
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, click, mount, q } from "../../../../test-support/park/componentsHarness";
import type { PushFlow, PushView } from "../../../api/push";
import { PushControl } from "./PushControl";

const settle = () => act(async () => undefined);
const CONSENT =
  "Tilo may send notifications to this device for your own approvals and updates. You can turn this off any time.";
const button = (root: ParentNode, text: string) =>
  [...root.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === text,
  ) as HTMLButtonElement;

function flowOf(first: PushView) {
  let view = first;
  const calls: string[] = [];
  const flow: PushFlow = {
    read: async () => view,
    enable: async () => {
      calls.push("enable");
      view = {
        here: true,
        permission: "granted",
        state: { devices: 1, delivery: "off_until_owner_policy" },
      };
      return { ok: true, state: view.state as NonNullable<PushView["state"]> };
    },
    disable: async () => {
      calls.push("disable");
      view = {
        here: false,
        permission: "granted",
        state: { devices: 0, delivery: "off_until_owner_policy" },
      };
      return { ok: true, state: view.state as NonNullable<PushView["state"]> };
    },
  };
  return { flow, calls };
}

afterEach(cleanup);

describe("FR-CHN-17d Browser notifications control", () => {
  it("FR-CHN-17 renders nothing without a live flow (fixture world, demo)", async () => {
    const m = mount(<PushControl flow={null} />);
    await settle();
    expect(m.container.textContent).toBe("");
    const bare = mount(<PushControl />); // no API url in tests: the deployment has no live flow
    await settle();
    expect(bare.container.textContent).toBe("");
  });

  it("FR-CHN-17 is off by default, turns on only on a click, and says nothing is sent until the owner's policy", async () => {
    const { flow, calls } = flowOf({
      here: false,
      permission: "default",
      state: { devices: 0, delivery: "off_until_owner_policy" },
    });
    const m = mount(<PushControl flow={flow} />);
    await settle();
    const sw = q<HTMLButtonElement>(m.container, '[role="switch"]');
    expect(sw.getAttribute("aria-label")).toBe("Browser notifications");
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(m.container.textContent).toContain("Off. Turn on");
    expect(calls).toEqual([]); // reading never enables anything
    click(sw);
    await settle();
    expect(calls).toEqual([]); // the switch only asks: nothing is enabled before the owner confirms
    expect(m.container.textContent).toContain(CONSENT);
    click(button(m.container, "Not now"));
    await settle();
    expect(m.container.textContent).not.toContain(CONSENT);
    expect(calls).toEqual([]);
    click(q(m.container, '[role="switch"]'));
    await settle();
    click(button(m.container, "Turn on"));
    await settle();
    await settle();
    expect(calls).toEqual(["enable"]);
    expect(q(m.container, '[role="switch"]').getAttribute("aria-checked")).toBe("true");
    expect(m.container.textContent).toContain("nothing is sent yet"); // this fake answers: no policy took effect
    expect(m.container.textContent).toContain("owner's push policy");
    click(q(m.container, '[role="switch"]'));
    await settle();
    await settle();
    expect(calls).toEqual(["enable", "disable"]);
    expect(m.container.textContent).toContain("Off. Turn on");
  });

  it("FR-CHN-17 states each refusal plainly", async () => {
    const cases: [PushView, string][] = [
      [{ here: false, permission: "unsupported", state: null }, "cannot show notifications"],
      [{ here: false, permission: "denied", state: null }, "blocked notifications"],
      [
        { here: true, permission: "granted", state: { devices: 1, delivery: "ready" } },
        "On for this browser.",
      ],
    ];
    for (const [view, text] of cases) {
      const m = mount(<PushControl flow={flowOf(view).flow} />);
      await settle();
      expect(m.container.textContent).toContain(text);
      cleanup();
    }
  });
});
