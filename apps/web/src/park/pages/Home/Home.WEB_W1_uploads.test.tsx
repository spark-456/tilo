// @vitest-environment happy-dom
// WEB-W1 (FR-INT-01, FR-UX-13): the Home composer's file button and image paste are back. They are always shown;
// when uploads cannot work (no live deployment, a demo, or a Quick ask) the button is disabled with an honest
// line, never hidden; when they can, a picked or pasted file shows a chip and goes out on the one POST /intake.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q } from "../../../../test-support/park/componentsHarness";
import { clickEl, mountHome, settle } from "../../../../test-support/park/homeHarness";
import {
  confirm,
  mountLiveHome,
  pickSize,
  toPlan,
} from "../../../../test-support/park/liveHomeHarness";
import { BRIEF_SUPPLIER_COMPARISON } from "../../../api/fixtures/brief";
import type { Api } from "../../api/index";
import { createLiveApi } from "../../api/liveApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const INTAKE = {
  task_id: "t_up1",
  brief: BRIEF_SUPPLIER_COMPARISON,
  questions: [],
  files: [{ filename: "quote.pdf", status: "ok", safety_flagged: false }],
};
const NOT_SET_UP = "Uploads need setup; the owner has not finished it.";

function live() {
  const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    if (init?.method === "POST" && path === "/intake") return json(INTAKE);
    if (path.startsWith("/worlds")) return json({ worlds: [], next_cursor: null });
    if (path.startsWith("/cards")) return json({ cards: [], next_cursor: null });
    return json({ detail: "Not Found" }, 404);
  });
  const api: Api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const posts = () => fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST");
  return { api, posts };
}

const pdf = () => new File(["%PDF-1.4"], "quote.pdf", { type: "application/pdf" });
const png = () =>
  new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], "shot.png", { type: "image/png" });
const exe = () => new File(["MZ"], "run.exe", { type: "application/octet-stream" });

function attach(el: HTMLElement, files: File[]) {
  const input = q(el, 'input[type="file"]') as HTMLInputElement;
  Object.defineProperty(input, "files", { value: files, configurable: true });
  act(() => {
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
function paste(el: HTMLElement, files: File[]) {
  const event = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "clipboardData", { value: { files, getData: () => "" } });
  act(() => {
    q(el, '[aria-label="Describe your task"]').dispatchEvent(event);
  });
}
const fileButton = (el: HTMLElement) =>
  q(el, '[data-testid="composer-attach"]') as HTMLButtonElement;

describe("WEB-W1 composer uploads", () => {
  it("FR_UX_13_W1_the_file_button_is_always_shown_and_says_why_when_uploads_are_not_set_up", async () => {
    const rig = await mountHome(); // fixture mode: no live deployment behind the page
    const button = fileButton(rig.el);
    expect(button).not.toBeNull();
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(rig.el.textContent).toContain(NOT_SET_UP);
    expect(rig.el.textContent).toContain("Start task"); // the task flow is untouched
  });

  it("FR_INT_01_W1_a_picked_file_shows_a_chip_and_goes_out_on_the_one_intake_post", async () => {
    const { api, posts } = live();
    const rig = await mountLiveHome(api);
    expect(fileButton(rig.el).getAttribute("aria-disabled")).not.toBe("true");
    attach(rig.el, [pdf()]);
    expect(rig.el.textContent).toContain("quote.pdf");
    await toPlan(rig, "Compare these quotes");
    await confirm(rig);
    expect(posts()).toHaveLength(1);
    const form = posts()[0]?.[1]?.body as FormData;
    expect(form.get("text")).toBe("Compare these quotes");
    expect((form.getAll("files") as File[]).map((f) => f.name)).toEqual(["quote.pdf"]);
    await settle();
    expect(rig.el.textContent).not.toContain("quote.pdf"); // sent: the chip is gone
  });

  it("FR_INT_01_W1_a_pasted_image_becomes_a_chip_and_can_be_removed", async () => {
    const { api } = live();
    const rig = await mountLiveHome(api);
    paste(rig.el, [png()]);
    expect(rig.el.textContent).toContain("shot.png");
    clickEl(q(rig.el, '[aria-label="Remove shot.png"]'));
    await settle();
    expect(rig.el.textContent).not.toContain("shot.png");
  });

  it("FR_INT_01_W1_an_unsupported_type_is_refused_plainly_and_never_staged", async () => {
    const { api, posts } = live();
    const rig = await mountLiveHome(api);
    attach(rig.el, [exe()]);
    expect(rig.el.textContent).toContain(
      "run.exe is not accepted; attach PDF, DOCX, PPTX, XLSX, CSV, PNG or JPG files.",
    );
    expect(rig.el.querySelector('[aria-label="Remove run.exe"]')).toBeNull();
    await toPlan(rig, "Compare these quotes");
    await confirm(rig);
    const form = posts()[0]?.[1]?.body as FormData;
    expect(form.getAll("files")).toHaveLength(0);
  });

  it("FR_UX_13_W1_a_quick_ask_makes_no_task_so_uploads_are_off_with_a_reason", async () => {
    const { api } = live();
    const rig = await mountLiveHome(api);
    await pickSize(rig, "Quick task");
    const quick = [...rig.el.querySelectorAll("button")].find((b) => b.textContent === "Quick");
    if (quick) clickEl(quick);
    await settle();
    expect(fileButton(rig.el).getAttribute("aria-disabled")).toBe("true");
    expect(rig.el.textContent).toMatch(/Uploads work with Thinking tasks/);
  });
});
