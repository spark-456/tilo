// @vitest-environment happy-dom
// FR-AGT-14 (ported from the retired S-03 "Repeat weekly" tests): the confirm card's optional weekly repeat. Off by
// default; on, it shows weekday, time and the browser time zone prefilled (Monday 09:00) and Start hands the
// cadence over; an invalid time stops Start; off again posts nothing. The schedule call itself is the one-step
// start's (oneStep.OLD-UI-OUT.test.ts).
import type { PlanMakeChoice } from "@tilo/contracts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q } from "../../../../test-support/park/componentsHarness";
import { clickEl, settle, typeInto } from "../../../../test-support/park/homeHarness";
import type { RunPlan } from "../../api/oneStep";
import { RunCard } from "./RunCard";

afterEach(cleanup);

const PLAN: RunPlan = {
  taskId: "t_1",
  goal: "Compare three suppliers",
  lines: [],
  approachId: "a_balanced",
  approachLabel: "Balanced",
  credits: { min: 8, max: 20 },
  cap: 20,
  usd: 1,
  time: "2–5 min",
  makeChoices: [],
};

const MAKER_CHOICE: PlanMakeChoice = {
  deliverable: 0,
  selected: "native",
  options: [
    { make_with: "native", label: "Tilo", status: "ready", suggested: false, note: null },
    {
      make_with: "connector:lovable",
      label: "Lovable",
      status: "ready",
      suggested: true,
      note: "For a large site",
    },
    {
      make_with: "connector:canva",
      label: "Canva",
      status: "needs_setup",
      suggested: false,
      note: "Connect Canva first",
    },
  ],
};

function card(over: { busy?: boolean; error?: string | null; plan?: RunPlan } = {}) {
  const onStart = vi.fn();
  const m = mount(
    <RunCard
      plan={over.plan ?? PLAN}
      busy={over.busy ?? false}
      error={over.error ?? null}
      onStart={onStart}
      onCancel={() => undefined}
      onEdit={() => undefined}
    />,
  );
  return { m, el: m.container, onStart };
}
const startButton = (el: HTMLElement) => q<HTMLButtonElement>(el, "button.park-home-confirm");
const toggle = (el: HTMLElement) => q<HTMLInputElement>(el, '[data-testid="repeat-weekly"]');

describe("FR-AGT-14 confirm card: Repeat weekly", () => {
  it("is off by default and Start hands over no cadence", async () => {
    const { el, onStart } = card();
    expect(toggle(el).checked).toBe(false);
    expect(el.querySelector('[data-testid="repeat-weekday"]')).toBeNull();
    clickEl(startButton(el));
    expect(onStart).toHaveBeenCalledWith(null, []);
  });

  it("switched on shows Monday 09:00 and the browser's zone, and Start hands over exactly that cadence", async () => {
    const { el, onStart } = card();
    clickEl(toggle(el));
    await settle();
    expect(q<HTMLSelectElement>(el, '[data-testid="repeat-weekday"]').value).toBe("0");
    expect(q<HTMLInputElement>(el, '[data-testid="repeat-time"]').value).toBe("09:00");
    const tz = q(el, '[data-testid="repeat-tz"]').textContent ?? "";
    expect(tz.length).toBeGreaterThan(0);
    clickEl(startButton(el));
    expect(onStart).toHaveBeenCalledWith({ weekday: 0, hour: 9, minute: 0, tz }, []);
  });

  it("an invalid time stops Start and says what to enter; switching off again hands over nothing", async () => {
    const { el, onStart } = card();
    clickEl(toggle(el));
    await settle();
    typeInto(q<HTMLInputElement>(el, '[data-testid="repeat-time"]'), "");
    await settle();
    expect(startButton(el).disabled).toBe(true);
    expect(el.textContent).toContain("Enter a time such as 09:00.");
    clickEl(toggle(el));
    await settle();
    expect(startButton(el).disabled).toBe(false);
    clickEl(startButton(el));
    expect(onStart).toHaveBeenCalledWith(null, []);
  });

  it("shows the budget line with the cap Start approves and a labelled meter", () => {
    const { el } = card();
    expect(q(el, '[data-testid="budget-line"]').textContent).toContain("up to 20 credits");
    expect(q(el, '[data-testid="budget-meter"]').getAttribute("aria-label")).toContain(
      "your cap is 20",
    );
  });

  it("WEBSITE_MK_08 shows every maker in order, suggests Lovable, and disables setup-only picks", () => {
    const m = mount(
      <RunCard
        plan={{ ...PLAN, makeChoices: [MAKER_CHOICE] }}
        busy={false}
        error={null}
        onStart={() => undefined}
        onCancel={() => undefined}
        onEdit={() => undefined}
      />,
    );
    const section = m.container.querySelector('[aria-label="Where to make it"]');
    const text = section?.textContent ?? "";
    expect(section).not.toBeNull();
    expect(text.indexOf("Tilo")).toBeLessThan(text.indexOf("Lovable"));
    expect(text).toContain("Suggested");
    expect(text).toContain("For a large site");
    expect(text).toContain("Connect Canva first");
    expect(section?.querySelector<HTMLInputElement>('input[value="native"]')?.checked).toBe(true);
    expect(
      section?.querySelector<HTMLInputElement>('input[value="connector:canva"]')?.disabled,
    ).toBe(true);
    expect(section?.querySelector('a[href="/connectors"]')).not.toBeNull();
    m.unmount();
  });

  it("WEBSITE_MK_05 changing maker hands the selected choice to Start; unlisted markdown has no chooser", () => {
    const onStart = vi.fn();
    const m = mount(
      <RunCard
        plan={{ ...PLAN, makeChoices: [MAKER_CHOICE] }}
        busy={false}
        error={null}
        onStart={onStart}
        onCancel={() => undefined}
        onEdit={() => undefined}
      />,
    );
    const el = m.container;
    clickEl(q<HTMLInputElement>(el, 'input[value="connector:lovable"]'));
    clickEl(startButton(el));
    expect(onStart.mock.calls[0]?.[1]?.[0]?.selected).toBe("connector:lovable");
    m.unmount();
    const noChoice = card({ plan: { ...PLAN, goal: "Write a markdown note" } });
    expect(noChoice.el.querySelector('[aria-label="Where to make it"]')).toBeNull();
  });
});
