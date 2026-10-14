// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import type { Decision } from "../api/types";
import { QuestionAnswer } from "./QuestionAnswer";

afterEach(cleanup);
const d: Decision = {
  k: "depot",
  world: "w_1",
  title: "Choose basis",
  body: "Price",
  yes: "Per pack",
  icon: "",
  done: "",
  toast: "",
  approvedTitle: "",
  questionOptions: [{ id: "per_pack", label: "Per pack" }],
};
it("FR-HIL-10 sends typed text and retains option controls with 44 px targets", () => {
  const send = vi.fn();
  const { container } = mount(<QuestionAnswer d={d} onDecide={send} />);
  const input = container.querySelector("textarea")!;
  expect(container.textContent).toContain("Type my own answer");
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(
      input,
      "Compare net price",
    );
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  act(() => {
    container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(send).toHaveBeenCalledWith("depot", "Compare net price");
  const buttons = [...container.querySelectorAll("button")];
  expect(buttons.every((b) => b.style.minHeight === "44px")).toBe(true);
  act(() => buttons[0]!.click());
  expect(send).toHaveBeenLastCalledWith("depot", undefined, "per_pack");
});
it("FR-HIL-10 rejects blank text in plain words and hides input on other cards", () => {
  const send = vi.fn();
  const rig = mount(<QuestionAnswer d={d} onDecide={send} />);
  act(() => {
    rig.container
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  expect(send).not.toHaveBeenCalled();
  expect(rig.container.querySelector('[role="alert"]')!.textContent).toContain("Type an answer");
  const { questionOptions, ...other } = d;
  rig.render(<QuestionAnswer d={other} onDecide={send} />);
  expect(rig.container.querySelector("textarea")).toBeNull();
});
