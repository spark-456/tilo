// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import type { RunEvent } from "../../park/pages/World/useRunEvents";
import { ResultTab } from "./ResultTab";

const cleanups: (() => void)[] = [];
afterEach(() => {
  for (const undo of cleanups.splice(0)) undo();
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const file = (name: string, type: string): Blob =>
  new Blob([readFileSync(resolve(process.cwd(), "src/results/fixtures", name))], { type });

const delivered = (format: string, label: string): RunEvent => ({
  seq: 1,
  type: "artifact.delivered",
  ts: "2026-10-20T10:00:00.000Z",
  credits: 0,
  summary: `${label} is ready.`,
  data: { artifact: { artifact_id: "art_main", label }, format },
});

const shared = (blob: Blob) => ({
  view: { status: "file" as const, blob },
  retry: () => undefined,
});

const settle = async () => {
  for (let i = 0; i < 8; i++) await act(async () => new Promise((r) => setTimeout(r, 20)));
};

/** Blob URLs without replacing `URL` itself (happy-dom builds its iframe locations with it). */
function stubBlobUrls(url: string): void {
  const urls = URL as unknown as Record<string, unknown>;
  const before = { create: urls.createObjectURL, revoke: urls.revokeObjectURL };
  urls.createObjectURL = () => url;
  urls.revokeObjectURL = () => undefined;
  cleanups.push(() => {
    urls.createObjectURL = before.create;
    urls.revokeObjectURL = before.revoke;
  });
}

function saveSpy(): string[] {
  const names: string[] = [];
  stubBlobUrls("blob:x");
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    names.push(this.download);
  });
  return names;
}

const buttonNamed = (root: HTMLElement, label: string) =>
  [...root.querySelectorAll("button")].find((b) => b.textContent?.trim() === label);

describe("P0_DOCS_OUT the Result tab previews Word and Excel files", () => {
  it("P0_DOCS_OUT_xlsx_result_shows_its_sheet_as_a_table_with_sheet_tabs", async () => {
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_x"
          events={[delivered("xlsx", "Sales sheet")]}
          shared={shared(file("sales.xlsx", XLSX))}
        />
      </div>,
    );
    await settle();
    const preview = m.container.querySelector('[data-testid="result-preview"]');
    expect(preview?.getAttribute("data-kind")).toBe("xlsx");
    const tabs = [...m.container.querySelectorAll('[role="tab"]')].map((t) => t.textContent);
    expect(tabs).toEqual(["Summary", "Summary 2"]);
    await act(async () => (m.container.querySelectorAll('[role="tab"]')[1] as HTMLElement).click());
    await settle();
    const headers = [...m.container.querySelectorAll("th")].map((th) => th.textContent);
    expect(headers).toEqual(["Region", "Closed on", "Units", "Unit price", "Revenue"]);
    expect(m.container.textContent).toContain("152.5");
  });

  it("P0_DOCS_OUT_docx_result_shows_its_headings_bullets_and_table", async () => {
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_d"
          events={[delivered("docx", "Sales report")]}
          shared={shared(file("sales.docx", DOCX))}
        />
      </div>,
    );
    await settle();
    const preview = m.container.querySelector('[data-testid="result-preview"]');
    expect(preview?.getAttribute("data-kind")).toBe("docx");
    expect([...(preview?.querySelectorAll("h4") ?? [])].map((h) => h.textContent)).toEqual([
      "Summary",
      "Next steps",
    ]);
    expect(preview?.textContent).toContain("• North grew");
    expect(preview?.querySelectorAll("th")).toHaveLength(5);
  });

  it("P0_DOCS_OUT_unreadable_office_file_still_offers_open_and_download", async () => {
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_bad"
          events={[delivered("xlsx", "Broken")]}
          shared={shared(new Blob(["not a zip"], { type: XLSX }))}
        />
      </div>,
    );
    await settle();
    expect(m.container.textContent).toContain("Open or download this file to read it.");
    expect(buttonNamed(m.container, "Open result")).toBeTruthy();
    expect(buttonNamed(m.container, "Download")).toBeTruthy();
  });

  it.each([
    ["docx", "Sales report", DOCX, "Sales report.docx"],
    ["xlsx", "Sales sheet", XLSX, "Sales sheet.xlsx"],
    ["pdf", "Quarterly review", "application/pdf", "Quarterly review.pdf"],
    ["docx", "Plan.docx", DOCX, "Plan.docx"],
  ])(
    "P0_DOCS_OUT_%s_download_is_named_with_its_real_extension (%s)",
    async (format, label, type, expected) => {
      const names = saveSpy();
      const m = mount(
        <div data-park="">
          <ResultTab
            worldId="w_name"
            events={[delivered(format, label)]}
            shared={shared(new Blob(["x"], { type }))}
          />
        </div>,
      );
      await settle();
      act(() => buttonNamed(m.container, "Download")?.click());
      expect(names).toEqual([expected]);
    },
  );

  it("P0_DOCS_OUT_pdf_result_is_previewed_in_the_viewer_frame", async () => {
    stubBlobUrls("blob:pdf");
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_pdf"
          events={[delivered("pdf", "Flyer")]}
          shared={shared(new Blob(["%PDF-1.4"], { type: "application/pdf" }))}
        />
      </div>,
    );
    await settle();
    expect(
      m.container.querySelector('[data-testid="result-preview"] iframe')?.getAttribute("src"),
    ).toBe("blob:pdf");
  });
});
