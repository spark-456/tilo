// @vitest-environment happy-dom
import { act, createElement } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebsitePreview } from "./WebsitePreview";

vi.mock("../api/ClientProvider", () => ({
  API_URL: "https://api.example.test",
  authToken: async () => "test-token",
}));

const bytes =
  "<!doctype html><title>Quiz & Form</title><div id='answers'>0</div><button id='btn'>Submit</button>";
const artifact = {
  artifact_id: "site_p0",
  version: 1,
  title: "Customer Questionnaire",
  content_sha256: "010203",
};

let container: HTMLDivElement;
let root: Root;
let fetchMock: ReturnType<typeof vi.fn>;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

async function mountPreview(props = {}): Promise<void> {
  await act(async () => {
    root.render(createElement(WebsitePreview, { worldId: "world_p0", artifact, ...props }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function frame(): HTMLIFrameElement {
  const found = container.querySelector("iframe");
  if (!found) throw new Error("preview frame is missing");
  return found;
}

beforeEach(() => {
  (
    window as unknown as { happyDOM: { settings: { disableIframePageLoading: boolean } } }
  ).happyDOM.settings.disableIframePageLoading = true;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    arrayBuffer: async () => new TextEncoder().encode(bytes).buffer,
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("crypto", {
    subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array([1, 2, 3]).buffer) },
  });
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:download"),
    revokeObjectURL: vi.fn(),
  });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("P0_TILO_APPS WebsitePreview", () => {
  it("P0_TILO_APPS_renders_open_full_screen_button_and_toggles_fullscreen", async () => {
    await mountPreview();
    const fsButton = container.querySelector('button[aria-label="Open full screen"]');
    expect(fsButton).not.toBeNull();
    expect(fsButton?.textContent).toContain("Open full screen");

    await act(async () => (fsButton as HTMLButtonElement).click());
    expect(container.querySelector('button[aria-label="Exit full screen"]')).not.toBeNull();
  });

  it("P0_TILO_APPS_renders_copy_link_button_signed_in_and_copies_address", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    await mountPreview({ isSignedIn: true });
    const copyButton = container.querySelector('button[aria-label="Copy link"]');
    expect(copyButton).not.toBeNull();
    expect(copyButton?.textContent).toContain("Copy link");

    await act(async () => (copyButton as HTMLButtonElement).click());
    expect(writeText).toHaveBeenCalledWith(window.location.href);
    expect(container.textContent).toContain("Link copied");
  });

  it("P0_TILO_APPS_hides_copy_link_button_when_not_signed_in", async () => {
    await mountPreview({ isSignedIn: false });
    const copyButton = container.querySelector('button[aria-label="Copy link"]');
    expect(copyButton).toBeNull();
  });

  it("P0_TILO_APPS_renders_download_as_html_button_and_downloads_html", async () => {
    await mountPreview();
    const downloadButton = container.querySelector('button[aria-label="Download website"]');
    expect(downloadButton).not.toBeNull();
    expect(downloadButton?.textContent).toContain("Download as .html");

    let saved = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      saved = this.download;
    });

    await act(async () => (downloadButton as HTMLButtonElement).click());
    expect(saved).toBe("Customer Questionnaire.html");
  });

  it("P0_TILO_APPS_sandboxed_preview_allows_scripts_for_interactive_forms", async () => {
    await mountPreview();
    const iframe = frame();
    expect(iframe.getAttribute("sandbox")).toBe("allow-scripts");
  });
});
