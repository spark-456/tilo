// @vitest-environment happy-dom
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AgentSprite } from "./AgentSprite";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

function renderSprite(props: Parameters<typeof AgentSprite>[0]) {
  act(() => {
    root.render(<AgentSprite {...props} />);
  });
}

describe("TW-2 AgentSprite component", () => {
  it("renders 32x40 box scaled by scale k", () => {
    renderSprite({ scale: 2, col: "#E8643F" });
    const el = container.querySelector(".tw-sprite") as HTMLElement;
    expect(el).toBeDefined();
    expect(el.style.width).toBe("64px");
    expect(el.style.height).toBe("80px");
    expect(el.getAttribute("aria-hidden")).toBe("true");
  });

  it("renders accessible image role when label is supplied", () => {
    renderSprite({ label: "Director Juno" });
    const el = container.querySelector(".tw-sprite") as HTMLElement;
    expect(el.getAttribute("role")).toBe("img");
    expect(el.getAttribute("aria-label")).toBe("Director Juno");
    expect(el.getAttribute("aria-hidden")).toBeNull();
  });

  it("renders glowing lit ring when lit is true and hides it when false", () => {
    renderSprite({ lit: true, col: "#3F7FE0" });
    expect(container.querySelector(".tw-sprite__ring")).not.toBeNull();

    renderSprite({ lit: false, col: "#3F7FE0" });
    expect(container.querySelector(".tw-sprite__ring")).toBeNull();
  });

  it("renders director crown for kind=director and lead spike for kind=lead", () => {
    renderSprite({ kind: "director" });
    expect(container.querySelector('.tw-sprite[data-kind="director"]')).not.toBeNull();

    renderSprite({ kind: "lead" });
    expect(container.querySelector('.tw-sprite[data-kind="lead"]')).not.toBeNull();

    renderSprite({ kind: "agent" });
    expect(container.querySelector('.tw-sprite[data-kind="agent"]')).not.toBeNull();
  });

  it("renders walking classes when walk is A or B and frame is not set", () => {
    renderSprite({ walk: "A", n: 4 });
    expect(container.querySelector(".tw-sprite__bob--walkA")).not.toBeNull();
    expect(container.querySelector(".tw-sprite__legL--walkA")).not.toBeNull();
    expect(container.querySelector(".tw-sprite__armL--walkA")).not.toBeNull();
  });

  it("renders static walk frames correctly (contact, down, pass, up)", () => {
    for (const frame of ["contact", "down", "pass", "up"] as const) {
      renderSprite({ frame });
      expect(container.querySelector(".tw-sprite")).not.toBeNull();
    }
  });

  it("handles moods: work, talk, think, happy, sad, hand", () => {
    renderSprite({ mood: "happy" });
    expect(container.querySelector(".tw-sprite__bob--happy")).not.toBeNull();

    renderSprite({ mood: "work" });
    expect(container.querySelector(".tw-sprite__armL--work")).not.toBeNull();

    renderSprite({ mood: "sad" });
    expect(container.querySelector('.tw-sprite[data-mood="sad"]')).not.toBeNull();
  });
});
