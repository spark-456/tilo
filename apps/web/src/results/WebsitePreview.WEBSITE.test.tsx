// @vitest-environment happy-dom
import { readFileSync, readdirSync, statSync } from "node:fs";
import { act, createElement } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WebsitePreview } from "./WebsitePreview";

vi.mock("../api/ClientProvider", () => ({
  API_URL: "https://api.example.test",
  authToken: async () => "test-token",
}));

const bytes = "<!doctype html><title>Saved</title>";
const artifact = {
  artifact_id: "site_1",
  version: 2,
  title: "Saved site",
  content_sha256: "010203",
};
let container: HTMLDivElement;
let root: Root;
let fetchMock: ReturnType<typeof vi.fn>;
const sourceRoot = `${process.cwd()}/src`;
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function sourceFiles(path: string): string[] {
  return readdirSync(path).flatMap((name) => {
    const child = `${path}/${name}`;
    return statSync(child).isDirectory() ? sourceFiles(child) : /\.tsx?$/.test(name) ? [child] : [];
  });
}

async function mount(): Promise<void> {
  await act(async () => {
    root.render(createElement(WebsitePreview, { worldId: "world_1", artifact }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function frame(): HTMLIFrameElement {
  const found = container.querySelector("iframe");
  if (!found) throw new Error("preview frame is missing");
  return found;
}

function shellWindow(): Window {
  const target = { postMessage: vi.fn() } as unknown as Window;
  Object.defineProperty(frame(), "contentWindow", { configurable: true, value: target });
  return target;
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
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    if (args[0] instanceof DOMException && args[0].name === "NotSupportedError") return;
    console.warn(...args);
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("WebsitePreview WEBSITE", () => {
  it("test_WEBSITE_WS_10_never_grants_same_origin_to_any_web_source", () => {
    const forbidden = ["allow", "same", "origin"].join("-");
    expect(
      sourceFiles(sourceRoot).some((path) => readFileSync(path, "utf8").includes(forbidden)),
    ).toBe(false);
  });

  it("test_WEBSITE_WS_10_uses_the_exact_opaque_sandbox_and_version_label", async () => {
    await mount();
    expect(frame().getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame().getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame().getAttribute("allow")).toBe("");
    expect(frame().getAttribute("src")).toBe("https://api.example.test/preview/website");
    expect(container.textContent).toContain("Version 2");
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.example.test/worlds/world_1/result?artifact=site_1&version=2",
      { headers: { Authorization: "Bearer test-token" }, cache: "no-store" },
    );
  });

  it("CX_WEB_3_WS_11_sends_once_when_the_shell_first_loads", async () => {
    await mount();
    const shell = shellWindow();
    const post = vi.mocked(shell.postMessage);
    expect(post).not.toHaveBeenCalled();
    await act(async () => frame().dispatchEvent(new Event("load")));
    await act(async () => frame().dispatchEvent(new Event("load")));
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith({ tilo: "preview", html: bytes }, "*");
  });

  it("CX_WEB_3_WS_12_ignores_untrusted_and_duplicate_preview_written_messages", async () => {
    await mount();
    const shell = shellWindow();
    await act(async () => frame().dispatchEvent(new Event("load")));
    await act(async () => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { tilo: "preview-written" },
          origin: "https://attacker.test",
          source: shell,
        }),
      );
    });
    await act(async () => frame().dispatchEvent(new Event("load")));
    expect(container.querySelector("iframe")).not.toBeNull();
    await act(async () =>
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { tilo: "preview-written" },
          origin: "null",
          source: shell,
        }),
      ),
    );
    await act(async () =>
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { tilo: "preview-written" },
          origin: "null",
          source: shell,
        }),
      ),
    );
    expect(container.querySelector("iframe")).not.toBeNull();
  });

  it("test_CX_WEB_RECHECK_4_WS_12_closes_only_on_a_load_after_preview_written", async () => {
    await mount();
    const shell = shellWindow();
    await act(async () => frame().dispatchEvent(new Event("load")));
    await act(async () =>
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { tilo: "preview-written" },
          origin: "null",
          source: shell,
        }),
      ),
    );
    expect(container.querySelector("iframe")).not.toBeNull();
    await act(async () => frame().dispatchEvent(new Event("load")));
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain(
      "This website tried to leave Tilo. The preview was closed.",
    );
  });

  it("CX_WEB_3_WS_12_closes_the_frame_when_preview_written_does_not_arrive_in_eight_seconds", async () => {
    await mount();
    shellWindow();
    vi.useFakeTimers();
    await act(async () => frame().dispatchEvent(new Event("load")));
    await act(async () => vi.advanceTimersByTimeAsync(8_001));
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain("Preview unavailable, open the file instead.");
    vi.useRealTimers();
  });

  it("test_WEBSITE_WS_13_downloads_only_an_octet_stream_blob", async () => {
    await mount();
    const create = vi.mocked(URL.createObjectURL);
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const download = container.querySelector("button[aria-label='Download website']");
    expect(download).not.toBeNull();
    await act(async () => (download as HTMLButtonElement).click());
    const downloaded = create.mock.calls[0]?.[0] as Blob;
    expect(downloaded.type).toBe("application/octet-stream");
    expect(click).toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:download");
  });

  it("test_WEBSITE_WS_14_hides_the_preview_when_the_saved_hash_does_not_match", async () => {
    vi.stubGlobal("crypto", {
      subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array([9]).buffer) },
    });
    await mount();
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.textContent).toContain("This file changed, so it is not shown");
  });
});
