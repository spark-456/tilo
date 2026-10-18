// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { ResultTab } from "../worldView/live/ResultTab";
import { AppPanel } from "./AppPanel";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("P0-TILO-APPS previews delivered HTML in Tilo and only shows a published URL after success", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
  const view = mount(
    <AppPanel artifactId="art_1" title="Survey" html="<form><input name='name'></form>" />,
  );
  await act(async () => Promise.resolve());
  const frame = view.container.querySelector("iframe");
  expect(frame?.getAttribute("sandbox")).toBe("allow-scripts allow-forms");
  expect(frame?.srcdoc).toContain("<script");
  const button = [...view.container.querySelectorAll("button")].find((node) =>
    node.textContent?.includes("Publish as a website"),
  );
  expect(button).toBeDefined();
  await act(async () => button?.click());
  expect(view.container.textContent).not.toContain("/u/");
  expect(view.container.textContent).toContain("could not be published");
});

it("P0-TILO-APPS Result tab embeds delivered HTML instead of rendering it as text", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
  const html = "<form><input name='answer'></form>";
  const view = mount(
    <ResultTab
      worldId="w1"
      events={[
        {
          seq: 1,
          type: "artifact.delivered",
          ts: "2026-10-18T10:00:00Z",
          credits: 0,
          summary: "Survey ready",
          data: { artifact: { artifact_id: "art_1", label: "Survey" }, format: "website" },
        },
      ]}
      shared={{
        view: { status: "file", blob: new Blob([html], { type: "text/html" }) },
        retry: () => undefined,
      }}
    />,
  );
  await act(async () => Promise.resolve());
  expect(view.container.querySelector("iframe")?.srcdoc).toContain(html);
  expect(view.container.textContent).toContain("Publish as a website");
});
