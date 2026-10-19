// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import type { RunEvent } from "../../park/pages/World/useRunEvents";
import { ResultTab } from "./ResultTab";

vi.mock("../../api/ClientProvider", () => ({
  API_URL: "https://api.example.test",
  authToken: async () => "test-token",
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

beforeEach(() => {
  (
    window as unknown as { happyDOM: { settings: { disableIframePageLoading: boolean } } }
  ).happyDOM.settings.disableIframePageLoading = true;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: async () => new TextEncoder().encode("<!doctype html><title>App</title>").buffer,
    }),
  );
  vi.stubGlobal("crypto", {
    subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3]).buffer) },
  });
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: () => "blob:download",
    revokeObjectURL: () => undefined,
  });
});

const makeEvents = (format: string, title: string): RunEvent[] => [
  {
    seq: 1,
    type: "artifact.created",
    ts: "2026-10-19T10:00:00.000Z",
    credits: 0,
    summary: `${title} created.`,
    item: { label: title },
    data: {
      artifact: { artifact_id: "art_site", version: 1 },
      content_sha256: "010203",
      media_type: "text/html",
      size_bytes: 500,
    },
  } as unknown as RunEvent,
  {
    seq: 2,
    type: "artifact.delivered",
    ts: "2026-10-19T10:01:00.000Z",
    credits: 0,
    summary: `${title} is ready.`,
    data: {
      artifact: { artifact_id: "art_site", version: 1 },
      format,
      make_with: "native",
      outbox_id: null,
    },
  },
];

describe("P0_TILO_APPS ResultTab website preview", () => {
  it("P0_TILO_APPS_website_deliverable_renders_sandboxed_preview_frame", async () => {
    const events = makeEvents("website", "Customer Questionnaire");
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="world_apps"
          events={events}
          shared={{
            view: {
              status: "file",
              blob: new Blob(["<!doctype html><title>Customer Questionnaire</title>"], {
                type: "text/html",
              }),
            },
            retry: () => undefined,
          }}
        />
      </div>,
    );
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());

    // Should mount sandboxed iframe with allow-scripts, NOT raw sandbox=""
    const iframe = m.container.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.getAttribute("sandbox")).toBe("allow-scripts");
  });

  it("P0_TILO_APPS_website_deliverable_has_fullscreen_copy_and_download_html_actions", async () => {
    const events = makeEvents("website", "Signup Form");
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="world_form"
          events={events}
          shared={{
            view: {
              status: "file",
              blob: new Blob(["<!doctype html><title>Signup Form</title>"], { type: "text/html" }),
            },
            retry: () => undefined,
          }}
        />
      </div>,
    );
    await act(async () => Promise.resolve());
    await act(async () => Promise.resolve());

    // Actions should offer "Open full screen", "Copy link", "Download as .html"
    const buttons = [...m.container.querySelectorAll("button")];
    const buttonTexts = buttons.map((b) => b.textContent?.trim());
    expect(buttonTexts.some((t) => t?.includes("Open full screen"))).toBe(true);
    expect(buttonTexts.some((t) => t?.includes("Copy link"))).toBe(true);
    expect(buttonTexts.some((t) => t?.includes("Download as .html"))).toBe(true);
  });
});
