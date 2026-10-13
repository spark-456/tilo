// @vitest-environment happy-dom
// M1 / FR_MTG_09: when hosting is not connected, S-26 sends the person to the Connectors page, where the meeting host
// is signed in. It stays hidden for any other refusal (the link would promise a fix that is not the cause).
import type { Meeting } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { TiloApiError } from "../api/http";
import { HostMeeting } from "./HostMeeting";
import { ALL_MEETINGS, SIGNED_IN } from "./data";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const SCHEDULED = ALL_MEETINGS.find((m) => m.id === "mt_q4_plan_next") as Meeting;

async function refused(error: Error) {
  const client = { hostMeeting: vi.fn(async () => Promise.reject(error)) };
  const box = document.createElement("div");
  document.body.append(box);
  await act(async () =>
    createRoot(box).render(
      <ClientProvider client={client as unknown as TiloClient}>
        <HostMeeting meeting={SCHEDULED} me={SIGNED_IN} pollMs={1} tries={1} />
      </ClientProvider>,
    ),
  );
  const ask = [...box.querySelectorAll("button")].find(
    (b) => b.textContent === "Host this meeting",
  );
  await act(async () => (ask as HTMLElement).click());
  return box;
}
const link = (box: Element) =>
  [...box.querySelectorAll("a")].find((a) => a.textContent === "Open Connectors");

describe("M1_FR_MTG_09_host_meeting_connectors_link", () => {
  it("M1_FR_MTG_09_not_connected_links_to_the_connectors_page", async () => {
    const box = await refused(
      new TiloApiError("x", 503, true, true, null, false, "not_configured"),
    );
    expect(box.textContent).toContain("Hosting isn't connected yet");
    expect(link(box)?.getAttribute("href")).toBe("/connectors");
  });

  it("M1_FR_MTG_09_other_refusals_show_no_connectors_link", async () => {
    const box = await refused(new TiloApiError("x", 409, false, true, null, false, "not_hostable"));
    expect(link(box)).toBeUndefined();
  });
});
