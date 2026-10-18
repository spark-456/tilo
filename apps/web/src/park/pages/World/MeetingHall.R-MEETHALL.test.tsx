// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { displayCredits } from "../../../worldView/live/RoomThread";
import { MeetingHall } from "./MeetingHall";

afterEach(cleanup);

describe("R-MEETHALL meeting controls", () => {
  it("R-MEETHALL presents role chips and a pill lead selector without agent ids", async () => {
    const client = {
      getJson: vi.fn(async (path: string) =>
        path.endsWith("/events")
          ? { events: [{ actor: "A_two", district: "d1" }] }
          : {
              semantic: {
                levels: [{ districts: [{ id: "d1", lead: "A_one" }] }],
                agents: [
                  { id: "A_one", rank: "lead" },
                  { id: "A_two", rank: "writer" },
                ],
              },
            },
      ),
      postJson: vi.fn(),
    };
    await act(async () => {
      mount(<MeetingHall worldId="w_one" client={client} />);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(document.body.textContent).not.toContain("A_one");
    expect(document.body.textContent).not.toContain("A_two");
    expect(
      document.querySelector('.park-meeting-rolepill[aria-pressed="true"]')?.textContent,
    ).toContain("Lead");
    expect(document.querySelector(".park-meeting-agentchip")?.textContent).toContain("Writer");
    expect(document.querySelector(".park-meeting-convene")?.textContent).toContain("Convene");
    expect(document.querySelector(".park-meeting-setup select")).toBeNull();
  });

  it("R-MEETHALL rounds conversation credits to one decimal", () => {
    expect(displayCredits(0.6774899999999988)).toBe("0.7");
    expect(displayCredits(2)).toBe("2");
  });
});
