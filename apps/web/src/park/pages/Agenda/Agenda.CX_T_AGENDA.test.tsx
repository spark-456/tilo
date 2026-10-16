// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount, q } from "../../../../test-support/park/componentsHarness";
import { settle, typeInto } from "../../../../test-support/park/skillsHarness";
import { AgendaNewMenu } from "./AgendaNewMenu";

afterEach(cleanup);

it("CX_T_AGENDA_new_menu_creates_a_pin_only_after_the_api_records_it", async () => {
  let release = () => {};
  const createPin = vi.fn(
    (_title: string, _key: string) =>
      new Promise<void>((resolve) => {
        release = resolve;
      }),
  );
  const changed = vi.fn();
  const { container } = mount(
    <AgendaNewMenu createPin={createPin} onPinCreated={changed} canHost />,
  );
  click(q(container, "summary"));
  expect(q(container, '[aria-label="Calendar item"]').getAttribute("aria-disabled")).toBe(
    "true",
  );
  click(q(container, 'button[role="menuitem"]'));
  typeInto(q<HTMLInputElement>(container, 'input[name="pin-title"]'), "Call Lin back");
  click(q(container, 'button[type="submit"]'));
  expect(createPin).toHaveBeenCalledWith("Call Lin back", expect.any(String));
  expect(container.textContent).not.toContain("Pin saved");
  expect(changed).not.toHaveBeenCalled();
  await act(async () => {
    release();
    await settle();
  });
  expect(changed).toHaveBeenCalledOnce();
  expect(container.textContent).toContain("Pin saved");
  expect(q(container, 'a[href="#agenda-meetings"]').textContent).toContain("Meeting with Tilo");
});

it("CX_T_AGENDA_new_menu_keeps_unavailable_actions_disabled", () => {
  const { container } = mount(
    <AgendaNewMenu createPin={null} onPinCreated={vi.fn()} canHost={false} />,
  );
  click(q(container, "summary"));
  expect(q(container, '[aria-label="Pin"]').getAttribute("aria-disabled")).toBe("true");
  expect(container.querySelector("button")).toBeNull();
  expect(q(container, '[aria-label="Meeting with Tilo"]').getAttribute("aria-disabled")).toBe(
    "true",
  );
});

it("CX_T_AGENDA_pin_error_does_not_claim_the_write_failed_or_refresh_the_list", async () => {
  const changed = vi.fn();
  const { container } = mount(
    <AgendaNewMenu
      createPin={vi.fn(async () => Promise.reject(new Error("response lost")))}
      onPinCreated={changed}
      canHost
    />,
  );
  click(q(container, "summary"));
  click(q(container, 'button[role="menuitem"]'));
  typeInto(q<HTMLInputElement>(container, 'input[name="pin-title"]'), "Call Lin back");
  click(q(container, 'button[type="submit"]'));
  await settle();
  expect(container.textContent).toContain("Could not confirm");
  expect(changed).not.toHaveBeenCalled();
});
