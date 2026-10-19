// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import type { Api } from "../../park/api";
import { installResultReader } from "../../park/api/results";
import type { RunEvent } from "../../park/pages/World/useRunEvents";
import { ResultTab } from "./ResultTab";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const delivered = (format: string, label: string): RunEvent => ({
  seq: 1,
  type: "artifact.delivered",
  ts: "2026-10-19T10:00:00.000Z",
  credits: 0,
  summary: `${label} is ready.`,
  data: { artifact: { artifact_id: "art_main", label }, format },
});

const fileView = (text: string, type: string) => ({
  view: { status: "file" as const, blob: new Blob([text], { type }) },
  retry: () => undefined,
});

describe("P0_RESULTS inline delivery", () => {
  it("P0_RESULTS_uses_the_name_of_the_delivered_artifact_version", () => {
    const created = {
      seq: 1,
      type: "artifact.created",
      ts: "2026-10-19T10:00:00.000Z",
      credits: 0,
      summary: "Draft made.",
      item: { label: "Draft.md" },
      data: { artifact: { artifact_id: "art_main", version: 1 } },
    } as RunEvent;
    const versioned = {
      ...created,
      seq: 2,
      type: "artifact.versioned",
      item: { label: "Final.md" },
      data: { artifact: { artifact_id: "art_main", version: 2 } },
    } as RunEvent;
    const delivery = {
      ...delivered("in_app", "The item"),
      seq: 3,
      summary: "The item was delivered.",
      data: { artifact: { artifact_id: "art_main", version: 2 }, format: "in_app" },
    };
    const m = mount(
      <div data-park="">
        <ResultTab worldId="w_versioned" events={[created, versioned, delivery]} />
      </div>,
    );
    expect(m.container.querySelector("h2")?.textContent).toBe("Final.md");
  });

  it("P0_RESULTS_keeps_delivery_event_details_out_of_the_result_page", () => {
    const m = mount(
      <div data-park="">
        <ResultTab worldId="w_clean" events={[delivered("md", "Decision.md")]} />
      </div>,
    );
    expect(m.container.textContent).not.toContain("artifact.delivered");
    expect(m.container.textContent).not.toContain("Other services coming later");
    expect(m.container.querySelectorAll('[data-testid="run-result"]')).toHaveLength(1);
  });

  it("P0_RESULTS_main_download_uses_the_recorded_filename", async () => {
    let saved = "";
    vi.stubGlobal("URL", {
      createObjectURL: () => "blob:download",
      revokeObjectURL: () => undefined,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved = this.download;
    });
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_budget"
          events={[delivered("csv", "Budget.csv")]}
          shared={fileView("Item,Cost\nFood,42", "text/csv")}
        />
      </div>,
    );
    const download = [...m.container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Download",
    );
    await act(async () => Promise.resolve());
    act(() => download?.click());
    expect(saved).toBe("Budget.csv");
  });

  it("P0_RESULTS_open_working_image_uses_its_recorded_file_type", async () => {
    const opened: string[] = [];
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn((blob: Blob) => {
        opened.push(blob.type);
        return "blob:working-image";
      }),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const api = {} as Api;
    installResultReader(
      api,
      async () => new Blob(["image bytes"], { type: "application/octet-stream" }),
    );
    const work = {
      ...delivered("png", "chart.png"),
      seq: 2,
      data: { artifact: { artifact_id: "art_work", label: "chart.png" }, format: "png" },
    };
    const m = mount(
      <div data-park="">
        <ResultTab api={api} worldId="w_files" events={[delivered("md", "Main.md"), work]} />
      </div>,
    );
    const open = m.container.querySelector<HTMLButtonElement>(
      'button[aria-label="Open working file: chart.png"]',
    );
    await act(async () => open?.click());
    expect(opened).toContain("image/png");
  });

  it("P0_RESULTS_unknown_recorded_type_cannot_turn_a_download_into_active_content", async () => {
    const opened: string[] = [];
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn((blob: Blob) => {
        opened.push(blob.type);
        return "blob:unknown-file";
      }),
      revokeObjectURL: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const api = {} as Api;
    installResultReader(
      api,
      async () => new Blob(["content"], { type: "application/octet-stream" }),
    );
    const created = {
      seq: 2,
      type: "artifact.created",
      ts: "2026-10-19T10:00:00.000Z",
      credits: 0,
      summary: "A file was made.",
      item: { label: "Unknown file" },
      data: { artifact: { artifact_id: "art_work" }, media_type: "application/xhtml+xml" },
    } as RunEvent;
    const work = {
      ...delivered("in_app", "Unknown file"),
      seq: 3,
      data: { artifact: { artifact_id: "art_work", label: "Unknown file" }, format: "in_app" },
    };
    const m = mount(
      <div data-park="">
        <ResultTab
          api={api}
          worldId="w_files"
          events={[delivered("md", "Main.md"), created, work]}
        />
      </div>,
    );
    const open = m.container.querySelector<HTMLButtonElement>(
      'button[aria-label="Open working file: Unknown file"]',
    );
    await act(async () => open?.click());
    expect(opened).toContain("application/octet-stream");
  });

  it("P0_RESULTS_previews_markdown_with_math_when_download_type_is_generic", async () => {
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_notes"
          events={[delivered("md", "Notes.md")]}
          shared={fileView("# Direction\nGo $\\to$ home.", "application/octet-stream")}
        />
      </div>,
    );
    await act(async () => {
      for (let i = 0; i < 3; i++) await Promise.resolve();
    });
    expect(m.container.querySelector('[data-testid="result-preview"] h3')?.textContent).toBe(
      "Direction",
    );
    expect(m.container.querySelector('[data-testid="result-preview"]')?.textContent).toContain(
      "Go → home.",
    );
  });

  it("P0_RESULTS_previews_a_pdf_inline", () => {
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => "about:blank#pdf-preview"),
        revokeObjectURL: vi.fn(),
      }),
    );
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_report"
          events={[delivered("pdf", "Report.pdf")]}
          shared={fileView("%PDF-1.4", "application/pdf")}
        />
      </div>,
    );
    expect(
      m.container.querySelector<HTMLIFrameElement>('[data-testid="result-preview"] iframe')?.src,
    ).toBe("about:blank#pdf-preview");
  });

  it("P0_RESULTS_pdf_preview_uses_recorded_type_when_download_is_generic", () => {
    const types: string[] = [];
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn((blob: Blob) => {
          types.push(blob.type);
          return "about:blank#pdf-preview";
        }),
        revokeObjectURL: vi.fn(),
      }),
    );
    mount(
      <div data-park="">
        <ResultTab
          worldId="w_report"
          events={[delivered("pdf", "Report.pdf")]}
          shared={fileView("%PDF-1.4", "application/octet-stream")}
        />
      </div>,
    );
    expect(types).toContain("application/pdf");
  });

  it("P0_RESULTS_preserves_a_recorded_unicode_filename", () => {
    const m = mount(
      <div data-park="">
        <ResultTab worldId="w_budget" events={[delivered("csv", "Café ₹.csv")]} />
      </div>,
    );
    expect(m.container.querySelector("h2")?.textContent).toBe("Café ₹.csv");
  });

  it("P0_RESULTS_uses_the_recorded_artifact_name_for_in_app_files", async () => {
    const created = {
      seq: 1,
      type: "artifact.created",
      ts: "2026-10-19T10:00:00.000Z",
      credits: 0,
      summary: "The agent made an item.",
      item: { label: "Actual forecast.csv" },
      data: { artifact: { artifact_id: "art_main", version: 1 }, media_type: "text/csv" },
    } as RunEvent;
    const delivery = {
      ...delivered("in_app", "The item"),
      seq: 2,
      summary: "The item was delivered.",
      data: { artifact: { artifact_id: "art_main", version: 1 }, format: "in_app" },
    };
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_csv"
          events={[created, delivery]}
          shared={fileView("Item,Cost\nFood,42", "application/octet-stream")}
        />
      </div>,
    );
    await act(async () => {
      for (let i = 0; i < 3; i++) await Promise.resolve();
    });
    expect(m.container.querySelector("h2")?.textContent).toBe("Actual forecast.csv");
    expect(
      m.container.querySelector('[data-testid="result-preview"] table')?.textContent,
    ).toContain("Food");
  });

  it("P0_RESULTS_no_artifact_never_shows_sample_content", () => {
    const m = mount(
      <div data-park="">
        <ResultTab worldId="w_empty" />
      </div>,
    );
    expect(m.container.querySelector('[data-testid="run-result"]')).toBeNull();
    expect(m.container.textContent).toContain("Nothing delivered yet");
    expect(m.container.textContent).not.toContain("Porto");
    expect(m.container.textContent).not.toContain("venue-shortlist");
  });

  it("P0_RESULTS_csv_previews_recorded_rows_as_a_table", async () => {
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_csv"
          events={[delivered("csv", "budget.csv")]}
          shared={fileView('Item,Cost\n"Food, drinks",42\n', "text/csv")}
        />
      </div>,
    );
    await act(async () => {
      for (let i = 0; i < 3; i++) await Promise.resolve();
    });
    const table = m.container.querySelector('[data-testid="result-preview"] table');
    expect(table?.textContent).toContain("Item");
    expect(table?.textContent).toContain("Food, drinks");
    expect(table?.querySelectorAll("tbody tr")).toHaveLength(1);
  });

  it("P0_RESULTS_html_uses_an_isolated_sandbox_preview", async () => {
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_html"
          events={[delivered("html", "site.html")]}
          shared={fileView("<h1>Actual site</h1><script>top.alert(1)</script>", "text/html")}
        />
      </div>,
    );
    await act(async () => {
      for (let i = 0; i < 3; i++) await Promise.resolve();
    });
    const frame = m.container.querySelector<HTMLIFrameElement>(
      '[data-testid="result-preview"] iframe',
    );
    expect(frame).not.toBeNull();
    expect(frame?.getAttribute("sandbox")).toBe("");
    expect(frame?.getAttribute("srcdoc")).toContain("Actual site");
  });

  it("P0_RESULTS_image_previews_the_delivered_blob", () => {
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn(() => "blob:preview"),
        revokeObjectURL: vi.fn(),
      }),
    );
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_image"
          events={[delivered("png", "chart.png")]}
          shared={fileView("image bytes", "image/png")}
        />
      </div>,
    );
    expect(
      m.container.querySelector<HTMLImageElement>('[data-testid="result-preview"] img')?.src,
    ).toBe("blob:preview");
  });

  it("P0_RESULTS_image_preview_uses_recorded_type_when_download_is_generic", () => {
    const types: string[] = [];
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn((blob: Blob) => {
        types.push(blob.type);
        return "blob:preview";
      }),
      revokeObjectURL: vi.fn(),
    });
    mount(
      <div data-park="">
        <ResultTab
          worldId="w_image"
          events={[delivered("png", "chart.png")]}
          shared={fileView("image bytes", "application/octet-stream")}
        />
      </div>,
    );
    expect(types).toContain("image/png");
  });

  it("P0_RESULTS_open_image_uses_the_recorded_type_when_download_is_octet_stream", () => {
    const opened: string[] = [];
    vi.stubGlobal(
      "URL",
      Object.assign(URL, {
        createObjectURL: vi.fn((blob: Blob) => {
          opened.push(blob.type);
          return "blob:preview";
        }),
        revokeObjectURL: vi.fn(),
      }),
    );
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_image"
          events={[delivered("png", "chart.png")]}
          shared={fileView("image bytes", "application/octet-stream")}
        />
      </div>,
    );
    const open = [...m.container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Open result",
    );
    act(() => open?.click());
    expect(opened).toContain("image/png");
  });

  it("P0_RESULTS_main_action_row_can_copy_real_text", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const text = "# Decision\nMove $\\to$ option B.";
    const blob = new Blob([text], { type: "text/markdown" });
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_text"
          events={[delivered("md", "Decision.md")]}
          shared={{
            view: { status: "text", blob, text, kind: "markdown", cut: false },
            retry: () => undefined,
          }}
        />
      </div>,
    );
    const copy = [...m.container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Copy",
    );
    expect(copy).toBeDefined();
    await act(async () => copy?.click());
    expect(writeText).toHaveBeenCalledWith(text);
    expect(m.container.textContent).toContain("Move → option B.");
  });
});
