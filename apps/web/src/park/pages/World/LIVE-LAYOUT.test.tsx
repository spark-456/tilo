// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { HttpClient } from "../../../api/http";
import { MeetingHall } from "./MeetingHall";
import { SkillProposals } from "./SkillProposals";

afterEach(cleanup);
it.each([
  [404, 404],
  [500, 200],
  [200, 200],
])(
  "LIVE-LAYOUT FR-WLD-05 layout %s and events %s do not hide access or server failures",
  async (layoutStatus, eventsStatus) => {
    const fetch = vi.fn(async (url: RequestInfo | URL) => {
      const events = String(url).endsWith("/events");
      return new Response(
        events && eventsStatus === 200 ? '{"events":[]}' : '{"detail":"Not Found"}',
        {
          status: events ? eventsStatus : layoutStatus,
        },
      );
    });
    let panel!: ReturnType<typeof mount>;
    await act(async () => {
      panel = mount(
        <MeetingHall
          worldId="w_live"
          client={new HttpClient({ baseUrl: "https://api.test", fetch })}
        />,
      );
    });
    expect(panel.container.querySelector('[role="alert"]')).not.toBeNull();
    expect(panel.container.textContent).not.toContain(
      "No recorded lead is available for this world.",
    );
  },
);
it("LIVE-LAYOUT FR-WLD-05 a readable world without layout has no invented attendees or alert", async () => {
  const error = vi.spyOn(console, "error");
  const fetch = vi.fn(async (url: RequestInfo | URL) =>
    String(url).endsWith("/events")
      ? new Response('{"events":[]}')
      : new Response('{"detail":"Not Found"}', { status: 404 }),
  );
  let panel!: ReturnType<typeof mount>;
  await act(async () => {
    panel = mount(
      <MeetingHall
        worldId="w_live"
        client={new HttpClient({ baseUrl: "https://api.test", fetch })}
      />,
    );
  });
  expect(panel.container.textContent).toContain("No recorded lead is available for this world.");
  expect(panel.container.querySelector('[role="alert"]')).toBeNull();
  expect(panel.container.querySelector("form")).toBeNull();
  expect(error).not.toHaveBeenCalled();
  error.mockRestore();
});
it.each([404, 403, 500])(
  "LIVE-LAYOUT FR-AGT-15 proposal read %s preserves its meaning",
  async (status) => {
    const error = vi.spyOn(console, "error");
    const fetch = vi.fn(async () => new Response('{"detail":"Not Found"}', { status }));
    let panel!: ReturnType<typeof mount>;
    await act(async () => {
      panel = mount(
        <SkillProposals
          worldId="w_live"
          client={new HttpClient({ baseUrl: "https://api.test", fetch })}
        />,
      );
    });
    if (status === 404) {
      expect(panel.container.textContent).toContain(
        "Skill proposals are not available for this world yet.",
      );
      expect(panel.container.querySelector('[role="alert"]')).toBeNull();
      expect(panel.container.textContent).not.toContain("No skill proposals yet.");
    } else expect(panel.container.querySelector('[role="alert"]')).not.toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(error).not.toHaveBeenCalled();
    error.mockRestore();
  },
);
