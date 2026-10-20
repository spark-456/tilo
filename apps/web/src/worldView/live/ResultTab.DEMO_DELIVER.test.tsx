// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import type { RunEvent } from "../../park/pages/World/useRunEvents";
import { ResultTab } from "./ResultTab";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** The events a live run records for its delivered file (20 Oct, Firestore): no label anywhere, a fixed summary. */
function liveRun(mediaType: string): RunEvent[] {
  const at = "2026-10-20T08:53:00.000Z";
  const artifact = { artifact_id: "art_44GSP7QQR55XF4C7MFJ588MR9Q", version: 1 };
  return [
    {
      seq: 46,
      type: "agent.assigned",
      ts: at,
      credits: 0,
      actor: "A_lead1",
      target: "A_w2",
      summary: "The Lead gave it: Global Timezones and Cities Reference",
      data: {},
    },
    {
      seq: 47,
      type: "artifact.created",
      ts: at,
      credits: 0,
      actor: "A_w2",
      target: artifact.artifact_id,
      summary: "The agent made an item.",
      data: { artifact, media_type: mediaType, size_bytes: 120 },
    },
    {
      seq: 49,
      type: "artifact.delivered",
      ts: at,
      credits: 0,
      actor: "A_w2",
      target: artifact.artifact_id,
      summary: "The item was delivered.",
      data: { artifact, format: "in_app", outbox_id: null },
    },
  ] as unknown as RunEvent[]; // fmt: skip
}

describe("DEMO_DELIVER a live delivered file", () => {
  it("DEMO_DELIVER_a_live_csv_is_named_by_its_unit_previewed_as_a_table_and_saved_as_csv", async () => {
    let saved = "";
    vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved = this.download;
    });
    const csv = "\ufeffZone,Offset\r\nAsia/Tokyo,9\r\n";
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_zones"
          events={liveRun("text/csv")}
          shared={{
            view: { status: "file", blob: new Blob([csv], { type: "text/csv" }) },
            retry: () => undefined,
          }}
        />
      </div>,
    );
    await act(async () => Promise.resolve());
    expect(m.container.querySelector("h2")?.textContent).toBe(
      "Global Timezones and Cities Reference",
    );
    expect(m.container.querySelector(".tw-res-type-pill")?.textContent).toContain("CSV");
    expect([...m.container.querySelectorAll("th")].map((th) => th.textContent)).toEqual([
      "Zone",
      "Offset",
    ]);
    const download = [...m.container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Download",
    );
    act(() => download?.click());
    expect(saved).toBe("Global Timezones and Cities Reference.csv");
  });

  it("DEMO_DELIVER_a_live_pdf_is_named_by_its_unit_never_by_its_artifact_id", () => {
    const m = mount(
      <div data-park="">
        <ResultTab worldId="w_report" events={liveRun("application/pdf")} />
      </div>,
    );
    expect(m.container.querySelector("h2")?.textContent).toBe(
      "Global Timezones and Cities Reference",
    );
    expect(m.container.textContent).not.toContain("art_44GSP7QQR55XF4C7MFJ588MR9Q");
  });
});
