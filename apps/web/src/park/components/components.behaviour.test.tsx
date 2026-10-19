// @vitest-environment happy-dom
// WEB-2 behaviour (plan section 4, README "Core components" and "Interactions and motion"): roles and
// names, keyboard and pointer behaviour, and the controlled-component contracts of the Park core
// components. Mounts with react-dom in happy-dom (the repo has no @testing-library); see
// test-support/park/componentsHarness.tsx. The styles are pinned in components.styles.test.tsx.
//
// Defaults taken where the README is silent (all listed in the WEB-2 report):
// - SegmentedControl is a radio group (role radiogroup / radio, aria-checked) or a tab list (tablist / tab,
//   aria-selected); either passes. Arrow keys move and select, wrapping at the ends (WAI-ARIA).
// - Toast has no dismiss control (the design has none); onDismiss runs after the action is taken.
// - Popover is role "dialog", Menu is role "menu" (the design uses exactly these).
import fc from "fast-check";
import { type ReactNode, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  active,
  cleanup,
  click,
  dispatchClick,
  focus,
  mount,
  nameOf,
  press,
  pressDocument,
  q,
  qa,
} from "../../../test-support/park/componentsHarness";
import {
  ArtTile,
  Button,
  Card,
  KpiTile,
  ListRow,
  Menu,
  ModalScrim,
  PageSheet,
  Popover,
  SegmentedControl,
  StatusChip,
  SummaryPill,
  Switch,
  TOAST_MS,
  Toast,
} from "./index";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const classesOf = (el: Element): string[] => [...el.classList];

describe("WEB_2_exports: the barrel exposes the core components by name", () => {
  it("WEB_2_exports_every_core_component_and_TOAST_MS_is_a_named_export", async () => {
    const mod = await import("./index");
    expect(Object.keys(mod)).toEqual(
      expect.arrayContaining([
        "Button",
        "SegmentedControl",
        "Switch",
        "StatusChip",
        "SummaryPill",
        "KpiTile",
        "ListRow",
        "ArtTile",
        "Card",
        "PageSheet",
        "Toast",
        "TOAST_MS",
        "Popover",
        "Menu",
        "ModalScrim",
      ]),
    );
    expect(Object.keys(mod)).not.toContain("default");
  });
});

describe("WEB_2_button: primary, secondary and needs are real buttons", () => {
  it.each(["primary", "secondary", "needs"] as const)(
    "WEB_2_button_%s_is_a_real_button_with_type_button_and_its_own_class",
    (variant) => {
      const { container } = mount(<Button variant={variant}>Save</Button>);
      const btn = q(container, "button");
      expect(btn.tagName).toBe("BUTTON");
      expect(btn.getAttribute("type")).toBe("button");
      expect(nameOf(btn)).toBe("Save");
      const cls = classesOf(btn);
      expect(cls).toContain("park-btn");
      expect(cls).toContain(`park-btn--${variant}`);
      for (const other of ["primary", "secondary", "needs"].filter((v) => v !== variant))
        expect(cls).not.toContain(`park-btn--${other}`);
      expect(cls).toContain("park-btn--md");
    },
  );

  it("WEB_2_button_size_sm_swaps_the_size_class", () => {
    const { container } = mount(
      <Button variant="secondary" size="sm">
        Small
      </Button>,
    );
    const cls = classesOf(q(container, "button"));
    expect(cls).toContain("park-btn--sm");
    expect(cls).not.toContain("park-btn--md");
  });

  it("WEB_2_button_click_calls_onClick_once", () => {
    const onClick = vi.fn();
    const { container } = mount(
      <Button variant="primary" onClick={onClick}>
        Go
      </Button>,
    );
    click(q(container, "button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("WEB_2_button_disabled_blocks_onClick_and_is_disabled_for_assistive_tech", () => {
    const onClick = vi.fn();
    const { container } = mount(
      <Button variant="secondary" disabled onClick={onClick}>
        Nope
      </Button>,
    );
    const btn = q<HTMLButtonElement>(container, "button");
    expect(btn.disabled).toBe(true);
    click(btn);
    dispatchClick(btn);
    press(btn, "Enter");
    press(btn, " ");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("WEB_2_button_enter_and_space_activate_it_like_any_button", () => {
    const onClick = vi.fn();
    const { container } = mount(
      <Button variant="needs" onClick={onClick}>
        Review
      </Button>,
    );
    const btn = q(container, "button");
    press(btn, "Enter");
    press(btn, " ");
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it("WEB_2_button_leading_icon_comes_first_is_hidden_from_assistive_tech_and_marks_the_button", () => {
    const { container } = mount(
      <Button variant="primary" icon={<svg data-testid="ic" viewBox="0 0 20 20" />}>
        Start
      </Button>,
    );
    const btn = q(container, "button");
    const icon = q(btn, '[data-testid="ic"]');
    expect(icon.closest('[aria-hidden="true"]'), "the icon wrapper is aria-hidden").not.toBeNull();
    expect(btn.firstElementChild?.contains(icon), "the icon comes before the label").toBe(true);
    expect(classesOf(btn)).toContain("park-btn--icon");
    expect(btn.textContent).toBe("Start");
  });

  it("WEB_2_button_without_an_icon_has_no_icon_class", () => {
    const { container } = mount(<Button variant="primary">Start</Button>);
    expect(classesOf(q(container, "button"))).not.toContain("park-btn--icon");
  });

  it("WEB_2_button_aria_label_and_type_submit_pass_through", () => {
    const { container } = mount(
      <Button variant="secondary" type="submit" aria-label="Send the invite">
        Send
      </Button>,
    );
    const btn = q(container, "button");
    expect(btn.getAttribute("type")).toBe("submit");
    expect(nameOf(btn)).toBe("Send the invite");
  });
});

describe("WEB_2_switch: a 44x26 role=switch", () => {
  function Sw({ start = false, onChange }: { start?: boolean; onChange?: (v: boolean) => void }) {
    const [on, set] = useState(start);
    return (
      <Switch
        label="Tilo joins and takes notes"
        checked={on}
        onChange={(v) => {
          set(v);
          onChange?.(v);
        }}
      />
    );
  }

  it("WEB_2_switch_is_a_button_with_role_switch_a_name_and_aria_checked", () => {
    const { container } = mount(<Sw />);
    const sw = q(container, '[role="switch"]');
    expect(sw.tagName).toBe("BUTTON");
    expect(sw.getAttribute("type")).toBe("button");
    expect(nameOf(sw)).toBe("Tilo joins and takes notes");
    expect(sw.getAttribute("aria-checked")).toBe("false");
  });

  it("WEB_2_switch_click_toggles_and_aria_checked_follows", () => {
    const onChange = vi.fn();
    const { container } = mount(<Sw onChange={onChange} />);
    const sw = q(container, '[role="switch"]');
    click(sw);
    expect(onChange).toHaveBeenLastCalledWith(true);
    expect(sw.getAttribute("aria-checked")).toBe("true");
    click(sw);
    expect(onChange).toHaveBeenLastCalledWith(false);
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("WEB_2_switch_space_and_enter_toggle_it", () => {
    const onChange = vi.fn();
    const { container } = mount(<Sw onChange={onChange} />);
    const sw = q(container, '[role="switch"]');
    focus(sw);
    press(sw, " ");
    expect(sw.getAttribute("aria-checked")).toBe("true");
    press(sw, "Enter");
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(onChange.mock.calls).toEqual([[true], [false]]);
  });

  it("WEB_2_switch_track_and_knob_classes_follow_the_state", () => {
    const { container } = mount(<Sw />);
    const sw = q(container, '[role="switch"]');
    const knob = q(sw, ".park-switch__knob");
    expect(classesOf(sw)).toContain("park-switch");
    expect(classesOf(sw)).not.toContain("park-switch--on");
    expect(classesOf(knob)).not.toContain("park-switch__knob--on");
    click(sw);
    expect(classesOf(sw)).toContain("park-switch--on");
    expect(classesOf(knob)).toContain("park-switch__knob--on");
  });

  it("WEB_2_switch_disabled_does_not_toggle", () => {
    const onChange = vi.fn();
    const { container } = mount(
      <Switch label="Locked" checked={false} disabled onChange={onChange} />,
    );
    const sw = q<HTMLButtonElement>(container, '[role="switch"]');
    expect(sw.disabled).toBe(true);
    click(sw);
    dispatchClick(sw);
    press(sw, " ");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("WEB_2_switch_knob_has_no_inline_transform_or_transition", () => {
    const { container } = mount(<Sw start />);
    const knob = q(container, ".park-switch__knob");
    expect(knob.getAttribute("style") ?? "").not.toMatch(/transition|animation/i);
    // The 18px travel lives in the stylesheet (WEB_2_styles_switch_...), not in an inline style.
    expect(knob.style.transition).toBe("");
  });
});

describe("WEB_2_segmented: plain and sliding", () => {
  const OPTS = [
    { value: "a", label: "Alpha" },
    { value: "b", label: "Beta" },
    { value: "c", label: "Gamma" },
    { value: "d", label: "Delta" },
  ] as const;

  function Seg({
    start = "a",
    sliding = false,
    onChange,
  }: {
    start?: string;
    sliding?: boolean;
    onChange?: (v: string) => void;
  }) {
    const [v, set] = useState<string>(start);
    const change = (n: string) => {
      set(n);
      onChange?.(n);
    };
    return sliding ? (
      <SegmentedControl label="View" options={OPTS} value={v} onChange={change} sliding />
    ) : (
      <SegmentedControl label="View" options={OPTS} value={v} onChange={change} />
    );
  }

  const ITEM = '[role="radio"], [role="tab"]';
  const GROUP = '[role="radiogroup"], [role="tablist"]';
  const selected = (el: Element) =>
    el.getAttribute("aria-checked") === "true" || el.getAttribute("aria-selected") === "true";
  const strip = (v: string): string => v.replace(/\s+/g, "");
  /** The thumb's inline transform, whitespace removed: the number and its unit (reference: "%"). */
  const slide = (el: Element): { n: number; unit: string } | null => {
    const m = /transform:translateX\((-?[\d.]+)(%|px)?\)/.exec(
      strip(el.getAttribute("style") ?? ""),
    );
    return m ? { n: Number.parseFloat(m[1] ?? ""), unit: m[2] ?? "" } : null;
  };
  const inline = (el: Element): string => strip(el.getAttribute("style") ?? "");

  it("WEB_2_segmented_is_a_named_group_of_items_with_exactly_one_selected", () => {
    const { container } = mount(<Seg start="b" />);
    const group = q(container, GROUP);
    expect(group.getAttribute("aria-label")).toBe("View");
    const items = qa(group, ITEM);
    expect(items.map((i) => nameOf(i))).toEqual(["Alpha", "Beta", "Gamma", "Delta"]);
    expect(items.filter(selected).map((i) => nameOf(i))).toEqual(["Beta"]);
    expect(classesOf(group)).toContain("park-seg");
    for (const it of items) expect(classesOf(it)).toContain("park-seg__item");
    expect(items.filter((i) => classesOf(i).includes("park-seg__item--on")).map(nameOf)).toEqual([
      "Beta",
    ]);
  });

  it("WEB_2_segmented_items_are_buttons_that_do_not_submit_forms", () => {
    const { container } = mount(<Seg />);
    for (const it of qa(container, ITEM)) {
      expect(it.tagName).toBe("BUTTON");
      expect(it.getAttribute("type")).toBe("button");
    }
  });

  it("WEB_2_segmented_click_selects_and_reports_the_value", () => {
    const onChange = vi.fn();
    const { container } = mount(<Seg onChange={onChange} />);
    const items = qa(container, ITEM);
    click(items[2] as HTMLElement);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("c");
    expect(qa(container, ITEM).filter(selected).map(nameOf)).toEqual(["Gamma"]);
  });

  it("WEB_2_segmented_roving_tabindex_only_the_selected_item_is_in_the_tab_order", () => {
    const { container } = mount(<Seg start="c" />);
    const tabbable = qa<HTMLButtonElement>(container, ITEM).filter((i) => i.tabIndex >= 0);
    expect(tabbable.map(nameOf)).toEqual(["Gamma"]);
  });

  it("WEB_2_segmented_arrow_keys_move_select_and_wrap", () => {
    const onChange = vi.fn();
    const { container } = mount(<Seg onChange={onChange} />);
    const items = () => qa(container, ITEM);
    focus(items()[0] as HTMLElement);
    press(active() as Element, "ArrowRight");
    expect(onChange).toHaveBeenLastCalledWith("b");
    expect(active()).toBe(items()[1]);
    press(active() as Element, "ArrowDown");
    expect(onChange).toHaveBeenLastCalledWith("c");
    press(active() as Element, "ArrowLeft");
    expect(onChange).toHaveBeenLastCalledWith("b");
    press(active() as Element, "ArrowUp");
    expect(onChange).toHaveBeenLastCalledWith("a");
    // wrap: left from the first goes to the last, right from the last goes to the first
    press(active() as Element, "ArrowLeft");
    expect(onChange).toHaveBeenLastCalledWith("d");
    expect(items().filter(selected).map(nameOf)).toEqual(["Delta"]);
    press(active() as Element, "ArrowRight");
    expect(onChange).toHaveBeenLastCalledWith("a");
    expect(active()).toBe(items()[0]);
  });

  it("WEB_2_segmented_plain_has_no_thumb", () => {
    const { container } = mount(<Seg />);
    expect(container.querySelector(".park-seg__thumb")).toBeNull();
    expect(classesOf(q(container, GROUP))).not.toContain("park-seg--sliding");
  });

  it("WEB_2_segmented_sliding_thumb_translates_by_index_times_100_percent_with_no_gap", () => {
    const { container } = mount(<Seg sliding start="a" />);
    const track = q(container, GROUP);
    expect(classesOf(track)).toContain("park-seg--sliding");
    const thumb = q(container, ".park-seg__thumb");
    expect(thumb.getAttribute("aria-hidden")).toBe("true");
    // Reference: width calc((100% - 6px)/N), transform translateX(i*100%); N = 4 here.
    expect(inline(thumb)).toContain("width:calc((100%-6px)/4)");
    expect(slide(thumb)?.n).toBe(0);
    click(qa(container, ITEM)[1] as HTMLElement);
    expect(slide(thumb)).toEqual({ n: 100, unit: "%" });
    click(qa(container, ITEM)[3] as HTMLElement);
    expect(slide(thumb)).toEqual({ n: 300, unit: "%" });
    expect(inline(thumb), "motion arrives in WEB-3 (BQ-WEB-3)").not.toMatch(/transition|animation/);
  });

  it("WEB_2_segmented_sliding_track_is_an_N_column_grid_through_an_inline_style", () => {
    const { container } = mount(<Seg sliding />);
    expect(inline(q(container, GROUP))).toContain("grid-template-columns:repeat(4,minmax(0,1fr))");
  });

  it("WEB_2_segmented_sliding_items_have_no_inline_width_and_carry_the_slide_class", () => {
    const { container } = mount(<Seg sliding start="b" />);
    for (const it of qa(container, ITEM)) {
      expect(it.getAttribute("style") ?? "").not.toMatch(/width/);
      expect(classesOf(it)).toContain("park-seg__item--slide");
    }
    // the thumb is the selected surface, so no item is the plain "on" item
    expect(qa(container, ITEM).some((i) => classesOf(i).includes("park-seg__item--on"))).toBe(
      false,
    );
  });

  it("WEB_2_segmented_plain_items_are_not_slide_items_and_the_track_has_no_inline_grid", () => {
    const { container } = mount(<Seg />);
    for (const it of qa(container, ITEM))
      expect(classesOf(it)).not.toContain("park-seg__item--slide");
    expect(inline(q(container, GROUP))).not.toContain("grid-template-columns");
  });

  it("WEB_2_segmented_sliding_keeps_the_same_roles_and_keyboard", () => {
    const { container } = mount(<Seg sliding />);
    focus(qa(container, ITEM)[0] as HTMLElement);
    press(active() as Element, "ArrowRight");
    expect(slide(q(container, ".park-seg__thumb"))).toEqual({ n: 100, unit: "%" });
    expect(qa(container, ITEM).filter(selected).map(nameOf)).toEqual(["Beta"]);
  });

  it("WEB_2_segmented_property_thumb_is_index_times_100_percent_and_width_over_N_for_any_N", () => {
    fc.assert(
      fc.property(fc.integer({ min: 2, max: 6 }), fc.nat(), (count, pick) => {
        const options = Array.from({ length: count }, (_, i) => ({
          value: `v${i}`,
          label: `Item ${i}`,
        }));
        const index = pick % count;
        const m = mount(
          <SegmentedControl
            label="Any"
            options={options}
            value={`v${index}`}
            onChange={() => undefined}
            sliding
          />,
        );
        const thumb = q(m.container, ".park-seg__thumb");
        const t = slide(thumb);
        const ok =
          t?.n === index * 100 &&
          (index === 0 || t.unit === "%") &&
          inline(thumb).includes(`width:calc((100%-6px)/${count})`) &&
          inline(q(m.container, GROUP)).includes(`repeat(${count},minmax(0,1fr))`);
        m.unmount();
        return ok;
      }),
      { numRuns: 20 },
    );
  });

  it("WEB_2_segmented_sliding_no_longer_takes_an_itemWidth_prop", () => {
    // Type-level: the typecheck test (WEB_2_typecheck) fails if the marked line stops being an error.
    const el = (
      <SegmentedControl
        label="x"
        options={OPTS}
        value="a"
        onChange={() => undefined}
        sliding
        // @ts-expect-error itemWidth was removed: the sliding track fills its container
        itemWidth={96}
      />
    );
    expect(el).toBeTruthy();
  });

  it("WEB_2_segmented_option_tone_colours_the_selected_label_and_defaults_to_ink", () => {
    const options = [
      { value: "off", label: "Off", tone: "ink2" },
      { value: "read", label: "Read", tone: "sch" },
      { value: "draft", label: "Draft", tone: "heroInk" },
      { value: "act", label: "Act", tone: "amberInk" },
      { value: "plain", label: "Plain" },
    ] as const;
    function Tones() {
      const [v, set] = useState<string>("off");
      return <SegmentedControl label="Tool" options={options} value={v} onChange={set} sliding />;
    }
    const { container } = mount(<Tones />);
    const TONE_CLASSES = ["ink", "ink2", "sch", "heroInk", "amberInk"].map(
      (t) => `park-seg__item--${t}`,
    );
    const toneOf = (el: Element) => classesOf(el).filter((c) => TONE_CLASSES.includes(c));
    const want = ["ink2", "sch", "heroInk", "amberInk", "ink"];
    for (let i = 0; i < options.length; i++) {
      click(qa(container, ITEM)[i] as HTMLElement);
      const items = qa(container, ITEM);
      expect(toneOf(items[i] as Element), `selected item ${i}`).toEqual([
        `park-seg__item--${want[i]}`,
      ]);
      for (let j = 0; j < items.length; j++)
        if (j !== i) expect(toneOf(items[j] as Element), `unselected item ${j}`).toEqual([]);
    }
  });

  it("WEB_2_segmented_size_lg_marks_the_track_and_every_item_and_md_is_the_default", () => {
    const lg = mount(
      <SegmentedControl
        label="Board style"
        options={[
          { value: "pin", label: "Pinboard" },
          { value: "grp", label: "Grouped" },
        ]}
        value="pin"
        onChange={() => undefined}
        sliding
        size="lg"
      />,
    );
    expect(classesOf(q(lg.container, GROUP))).toContain("park-seg--lg");
    for (const it of qa(lg.container, ITEM)) expect(classesOf(it)).toContain("park-seg__item--lg");
    const md = mount(<Seg sliding />);
    expect(classesOf(q(md.container, GROUP))).not.toContain("park-seg--lg");
    for (const it of qa(md.container, ITEM))
      expect(classesOf(it)).not.toContain("park-seg__item--lg");
  });

  it("WEB_2_segmented_property_n_right_arrows_come_back_to_the_start", () => {
    fc.assert(
      fc.property(fc.integer({ min: 2, max: 6 }), (count) => {
        const options = Array.from({ length: count }, (_, i) => ({
          value: `v${i}`,
          label: `I${i}`,
        }));
        function Wrap() {
          const [v, set] = useState("v0");
          return <SegmentedControl label="Loop" options={options} value={v} onChange={set} />;
        }
        const m = mount(<Wrap />);
        focus(qa(m.container, ITEM)[0] as HTMLElement);
        for (let i = 0; i < count; i++) press(active() as Element, "ArrowRight");
        const sel = qa(m.container, ITEM).filter(selected).map(nameOf);
        m.unmount();
        return sel.length === 1 && sel[0] === "I0";
      }),
      { numRuns: 15 },
    );
  });
});

describe("WEB_2_chip_and_pill: status chip and summary pill", () => {
  const TONES = ["ok", "hero", "amber", "neutral"] as const;

  it.each(TONES)("WEB_2_chip_tone_%s_has_its_own_class_and_shows_its_text", (tone) => {
    const { container } = mount(<StatusChip tone={tone}>Trusted</StatusChip>);
    const chip = q(container, ".park-chip");
    expect(classesOf(chip)).toContain(`park-chip--${tone}`);
    expect(chip.textContent).toBe("Trusted");
    expect(chip.tagName).toBe("SPAN");
  });

  it.each(TONES)("WEB_2_pill_tone_%s_has_its_own_class_and_shows_its_text", (tone) => {
    const { container } = mount(<SummaryPill tone={tone}>3 trusted</SummaryPill>);
    const pill = q(container, ".park-pill");
    expect(classesOf(pill)).toContain(`park-pill--${tone}`);
    expect(pill.textContent).toBe("3 trusted");
  });

  it("WEB_2_chip_size_sm_adds_park_chip_sm_and_md_is_the_default", () => {
    const sm = mount(
      <StatusChip tone="ok" size="sm">
        Trusted
      </StatusChip>,
    );
    expect(classesOf(q(sm.container, ".park-chip"))).toContain("park-chip--sm");
    expect(classesOf(q(sm.container, ".park-chip"))).toContain("park-chip--ok");
    const md = mount(<StatusChip tone="ok">Trusted</StatusChip>);
    expect(classesOf(q(md.container, ".park-chip"))).not.toContain("park-chip--sm");
    const md2 = mount(
      <StatusChip tone="ok" size="md">
        Trusted
      </StatusChip>,
    );
    expect(classesOf(q(md2.container, ".park-chip"))).not.toContain("park-chip--sm");
  });

  it("WEB_2_pill_defaults_to_the_neutral_tone", () => {
    const { container } = mount(<SummaryPill>2 learning</SummaryPill>);
    expect(classesOf(q(container, ".park-pill"))).toContain("park-pill--neutral");
  });
});

describe("WEB_2_kpi: KPI tile", () => {
  it("WEB_2_kpi_shows_label_value_and_sub_in_their_own_parts", () => {
    const { container } = mount(<KpiTile label="Spent so far" value="£2,412" sub="of £8,000" />);
    expect(q(container, ".park-kpi__label").textContent).toBe("Spent so far");
    expect(q(container, ".park-kpi__value").textContent).toBe("£2,412");
    expect(q(container, ".park-kpi__sub").textContent).toBe("of £8,000");
    const root = q(container, ".park-kpi");
    expect(root.tagName).not.toBe("BUTTON");
    expect(container.querySelector("button")).toBeNull();
  });

  it("WEB_2_kpi_sub_is_optional", () => {
    const { container } = mount(<KpiTile label="Hours handed back" value="42" />);
    expect(container.querySelector(".park-kpi__sub")).toBeNull();
  });

  it("WEB_2_kpi_with_onClick_is_one_real_button_that_calls_it", () => {
    const onClick = vi.fn();
    const { container } = mount(
      <KpiTile label="Waiting on you" value="£3,420" tone="amber" onClick={onClick} />,
    );
    const root = q(container, ".park-kpi");
    expect(root.tagName).toBe("BUTTON");
    expect(root.getAttribute("type")).toBe("button");
    click(root);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it.each(["amber", "ok", "sch"] as const)("WEB_2_kpi_tone_%s_adds_its_class", (tone) => {
    const { container } = mount(<KpiTile label="L" value="1" tone={tone} />);
    expect(classesOf(q(container, ".park-kpi"))).toContain(`park-kpi--${tone}`);
  });
});

describe("WEB_2_list_row: grid 44px 1fr auto", () => {
  it("WEB_2_list_row_always_has_three_cells_lead_body_trail", () => {
    const { container } = mount(<ListRow>Only a body</ListRow>);
    const row = q(container, ".park-row");
    expect([...row.children].map((c) => c.className)).toEqual([
      "park-row__lead",
      "park-row__body",
      "park-row__trail",
    ]);
    expect(q(row, ".park-row__body").textContent).toBe("Only a body");
  });

  it("WEB_2_list_row_puts_lead_and_trail_in_their_cells", () => {
    const { container } = mount(
      <ListRow lead={<i data-testid="lead" />} trail={<b data-testid="trail">£40</b>}>
        Invoice run
      </ListRow>,
    );
    expect(q(container, ".park-row__lead").querySelector('[data-testid="lead"]')).not.toBeNull();
    expect(q(container, ".park-row__trail").textContent).toBe("£40");
  });

  it("WEB_2_list_row_selected_has_the_on_class_and_aria_current", () => {
    const { container } = mount(
      <>
        <ListRow selected>Picked</ListRow>
        <ListRow>Other</ListRow>
      </>,
    );
    const [a, b] = qa(container, ".park-row");
    expect(classesOf(a as Element)).toContain("park-row--on");
    expect((a as Element).getAttribute("aria-current")).toBe("true");
    expect(classesOf(b as Element)).not.toContain("park-row--on");
    expect((b as Element).hasAttribute("aria-current")).toBe(false);
  });

  it("WEB_2_list_row_without_onClick_is_not_interactive", () => {
    const { container } = mount(<ListRow>Static</ListRow>);
    const row = q(container, ".park-row");
    expect(row.tagName).not.toBe("BUTTON");
    expect(row.getAttribute("role")).toBeNull();
    expect(row.hasAttribute("tabindex")).toBe(false);
    expect(classesOf(row)).not.toContain("park-row--action");
  });

  it("WEB_2_list_row_with_onClick_is_a_focusable_button_and_enter_or_space_or_click_activate_it", () => {
    const onClick = vi.fn();
    const { container } = mount(<ListRow onClick={onClick}>Open the world</ListRow>);
    const row = q(container, ".park-row");
    expect(classesOf(row)).toContain("park-row--action");
    const isButton = row.tagName === "BUTTON" || row.getAttribute("role") === "button";
    expect(isButton, "an actionable row is a button").toBe(true);
    expect((row as HTMLElement).tabIndex).toBeGreaterThanOrEqual(0);
    expect(nameOf(row)).toContain("Open the world");
    click(row);
    expect(onClick).toHaveBeenCalledTimes(1);
    focus(row);
    press(row, "Enter");
    expect(onClick).toHaveBeenCalledTimes(2);
    press(row, " ");
    expect(onClick).toHaveBeenCalledTimes(3);
  });
});

describe("WEB_2_art_tile: square tile, art on the bottom edge", () => {
  it("WEB_2_art_tile_is_44_square_by_default_and_renders_the_art", () => {
    const { container } = mount(
      <ArtTile>
        <svg data-testid="art" />
      </ArtTile>,
    );
    const tile = q(container, ".park-art");
    expect(tile.style.width).toBe("44px");
    expect(tile.style.height).toBe("44px");
    expect(tile.querySelector('[data-testid="art"]')).not.toBeNull();
    expect(classesOf(tile)).toContain("park-art--sunk");
  });

  it("WEB_2_art_tile_size_and_tint_props_apply", () => {
    const { container } = mount(
      <ArtTile size={64} tint="amber">
        <i />
      </ArtTile>,
    );
    const tile = q(container, ".park-art");
    expect(tile.style.width).toBe("64px");
    expect(tile.style.height).toBe("64px");
    expect(classesOf(tile)).toContain("park-art--amber");
    expect(classesOf(tile)).not.toContain("park-art--sunk");
  });
});

describe("WEB_2_card_and_sheet: surfaces", () => {
  it("WEB_2_card_renders_children_in_a_park_card", () => {
    const { container } = mount(
      <Card>
        <p>Cost per run</p>
      </Card>,
    );
    const card = q(container, ".park-card");
    expect(card.textContent).toBe("Cost per run");
  });

  it("WEB_2_page_sheet_renders_children_in_a_park_sheet", () => {
    const { container } = mount(
      <PageSheet>
        <h1>Ledger</h1>
      </PageSheet>,
    );
    const sheet = q(container, ".park-sheet");
    expect(sheet.querySelector("h1")?.textContent).toBe("Ledger");
  });
});

describe("WEB_2_toast: presentational, no timer inside", () => {
  it("WEB_2_toast_TOAST_MS_is_4200", () => {
    expect(TOAST_MS).toBe(4200);
  });

  it("WEB_2_toast_is_a_polite_status_with_the_message_and_a_check_dot", () => {
    const { container } = mount(
      <Toast message="Approved £3,420 for Laptop Depot" onDismiss={() => undefined} />,
    );
    const toast = q(container, ".park-toast");
    expect(toast.getAttribute("role")).toBe("status");
    expect(toast.getAttribute("aria-live")).toBe("polite");
    expect(toast.textContent).toContain("Approved £3,420 for Laptop Depot");
    const dot = q(toast, ".park-toast__dot");
    expect(dot.getAttribute("aria-hidden")).toBe("true");
    expect(classesOf(toast)).not.toContain("park-toast--inline");
  });

  it("WEB_2_toast_without_an_action_label_has_no_button", () => {
    const { container } = mount(<Toast message="Saved" onDismiss={() => undefined} />);
    expect(container.querySelector("button")).toBeNull();
  });

  it("WEB_2_toast_action_calls_onAction_then_onDismiss_once_each", () => {
    const order: string[] = [];
    const { container } = mount(
      <Toast
        message="Approved"
        actionLabel="Undo"
        onAction={() => order.push("action")}
        onDismiss={() => order.push("dismiss")}
      />,
    );
    const btn = q(container, "button");
    expect(btn.getAttribute("type")).toBe("button");
    expect(nameOf(btn)).toBe("Undo");
    expect(classesOf(btn)).toContain("park-toast__action");
    click(btn);
    expect(order).toEqual(["action", "dismiss"]);
  });

  it("WEB_2_toast_action_label_without_onAction_still_dismisses", () => {
    const onDismiss = vi.fn();
    const { container } = mount(
      <Toast message="Opened" actionLabel="Open" onDismiss={onDismiss} />,
    );
    click(q(container, "button"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("WEB_2_toast_inline_flag_adds_the_inline_class_for_galleries", () => {
    const { container } = mount(<Toast message="Sample" inline onDismiss={() => undefined} />);
    expect(classesOf(q(container, ".park-toast"))).toContain("park-toast--inline");
  });

  it("WEB_2_toast_starts_no_timer_and_never_hides_itself", () => {
    vi.useFakeTimers();
    const onDismiss = vi.fn();
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const { container } = mount(
      <Toast message="Approved" actionLabel="Undo" onDismiss={onDismiss} />,
    );
    expect(vi.getTimerCount(), "the 4.2 s auto-hide belongs to the shell store (WEB-3)").toBe(0);
    vi.advanceTimersByTime(TOAST_MS * 3);
    expect(onDismiss).not.toHaveBeenCalled();
    expect(container.querySelector(".park-toast")).not.toBeNull();
    expect(setTimeoutSpy).not.toHaveBeenCalled();
    expect(setIntervalSpy).not.toHaveBeenCalled();
  });
});

describe("WEB_2_menu: rows are menuitems; Escape and the backdrop close", () => {
  const ITEMS = (log: string[]) => [
    { id: "profile", label: "Profile and settings", onSelect: () => log.push("profile") },
    { id: "connectors", label: "Connectors", onSelect: () => log.push("connectors") },
    { id: "signout", label: "Sign out", onSelect: () => log.push("signout") },
  ];

  function Host({ log, onClosed }: { log: string[]; onClosed?: () => void }) {
    const [open, set] = useState(false);
    return (
      <div>
        <button type="button" data-testid="trigger" aria-haspopup="menu" onClick={() => set(true)}>
          Account
        </button>
        {open ? (
          <Menu
            label="Account"
            items={ITEMS(log)}
            onClose={() => {
              set(false);
              onClosed?.();
            }}
          />
        ) : null}
      </div>
    );
  }

  const open = (container: HTMLElement) => {
    const trigger = q(container, '[data-testid="trigger"]');
    focus(trigger);
    click(trigger);
    return trigger;
  };

  it("WEB_2_menu_is_a_named_menu_of_menuitem_buttons", () => {
    const log: string[] = [];
    const { container } = mount(<Host log={log} />);
    open(container);
    const menu = q(container, '[role="menu"]');
    expect(menu.getAttribute("aria-label")).toBe("Account");
    expect(classesOf(menu)).toContain("park-popover");
    const rows = qa(menu, '[role="menuitem"]');
    expect(rows.map(nameOf)).toEqual(["Profile and settings", "Connectors", "Sign out"]);
    for (const r of rows) {
      expect(r.tagName).toBe("BUTTON");
      expect(r.getAttribute("type")).toBe("button");
      expect(classesOf(r)).toContain("park-menu__row");
    }
  });

  it("WEB_2_menu_moves_focus_to_the_first_row_when_it_opens", () => {
    const { container } = mount(<Host log={[]} />);
    open(container);
    expect(nameOf(active() as Element)).toBe("Profile and settings");
  });

  it("WEB_2_menu_arrow_keys_move_focus_between_rows_and_wrap", () => {
    const { container } = mount(<Host log={[]} />);
    open(container);
    press(active() as Element, "ArrowDown");
    expect(nameOf(active() as Element)).toBe("Connectors");
    press(active() as Element, "ArrowDown");
    press(active() as Element, "ArrowDown");
    expect(nameOf(active() as Element)).toBe("Profile and settings");
    press(active() as Element, "ArrowUp");
    expect(nameOf(active() as Element)).toBe("Sign out");
  });

  it("WEB_2_menu_choosing_a_row_calls_its_onSelect_then_closes_and_returns_focus", () => {
    const log: string[] = [];
    const onClosed = vi.fn();
    const { container } = mount(<Host log={log} onClosed={onClosed} />);
    const trigger = open(container);
    click(qa(container, '[role="menuitem"]')[1] as HTMLElement);
    expect(log).toEqual(["connectors"]);
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[role="menu"]')).toBeNull();
    expect(active()).toBe(trigger);
  });

  it("WEB_2_menu_escape_on_the_focused_row_closes_it_once_and_focus_returns_to_the_trigger", () => {
    const onClosed = vi.fn();
    const { container } = mount(<Host log={[]} onClosed={onClosed} />);
    const trigger = open(container);
    press(active() as Element, "Escape");
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[role="menu"]')).toBeNull();
    expect(active()).toBe(trigger);
  });

  it("WEB_2_menu_escape_anywhere_on_the_document_closes_it", () => {
    const onClosed = vi.fn();
    const { container } = mount(<Host log={[]} onClosed={onClosed} />);
    open(container);
    document.body.focus();
    pressDocument("Escape");
    expect(onClosed).toHaveBeenCalledTimes(1);
  });

  it("WEB_2_menu_backdrop_click_closes_it_and_a_click_inside_does_not", () => {
    const onClosed = vi.fn();
    const { container } = mount(<Host log={[]} onClosed={onClosed} />);
    const trigger = open(container);
    click(q(container, '[role="menu"]'));
    expect(onClosed).not.toHaveBeenCalled();
    click(q(container, ".park-popover__backdrop"));
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[role="menu"]')).toBeNull();
    expect(active()).toBe(trigger);
  });

  it("WEB_2_menu_inline_has_no_backdrop_and_the_inline_class_for_galleries", () => {
    const { container } = mount(
      <Menu label="Static" inline items={ITEMS([])} onClose={() => undefined} />,
    );
    expect(container.querySelector(".park-popover__backdrop")).toBeNull();
    expect(classesOf(q(container, '[role="menu"]'))).toContain("park-popover--inline");
  });

  it("WEB_2_menu_width_prop_sets_the_panel_width", () => {
    const { container } = mount(
      <Menu label="W" width={300} items={ITEMS([])} onClose={() => undefined} />,
    );
    expect(q(container, '[role="menu"]').style.width).toBe("300px");
  });
});

describe("WEB_2_popover: the generic panel", () => {
  function Host({ onClosed, children }: { onClosed?: () => void; children?: ReactNode }) {
    const [open, set] = useState(false);
    return (
      <div>
        <button type="button" data-testid="trigger" onClick={() => set(true)}>
          Notifications
        </button>
        {open ? (
          <Popover
            label="Notifications"
            width={392}
            onClose={() => {
              set(false);
              onClosed?.();
            }}
          >
            {children}
          </Popover>
        ) : null}
      </div>
    );
  }

  it("WEB_2_popover_is_a_named_dialog_with_its_children_and_width", () => {
    const { container } = mount(
      <Host>
        <p data-testid="body">Nothing new</p>
      </Host>,
    );
    focus(q(container, '[data-testid="trigger"]'));
    click(q(container, '[data-testid="trigger"]'));
    const dlg = q(container, '[role="dialog"]');
    expect(dlg.getAttribute("aria-label")).toBe("Notifications");
    expect(dlg.style.width).toBe("392px");
    expect(classesOf(dlg)).toContain("park-popover");
    expect(dlg.querySelector('[data-testid="body"]')).not.toBeNull();
  });

  it("WEB_2_popover_escape_and_backdrop_call_onClose_and_focus_returns", () => {
    const onClosed = vi.fn();
    const { container } = mount(<Host onClosed={onClosed}>x</Host>);
    const trigger = q(container, '[data-testid="trigger"]');
    focus(trigger);
    click(trigger);
    pressDocument("Escape");
    expect(onClosed).toHaveBeenCalledTimes(1);
    expect(active()).toBe(trigger);
    focus(trigger);
    click(trigger);
    click(q(container, ".park-popover__backdrop"));
    expect(onClosed).toHaveBeenCalledTimes(2);
    expect(active()).toBe(trigger);
  });

  it("WEB_2_popover_removes_its_document_listener_when_it_closes", () => {
    const onClosed = vi.fn();
    const { container } = mount(<Host onClosed={onClosed}>x</Host>);
    focus(q(container, '[data-testid="trigger"]'));
    click(q(container, '[data-testid="trigger"]'));
    click(q(container, ".park-popover__backdrop"));
    pressDocument("Escape");
    pressDocument("Escape");
    expect(onClosed).toHaveBeenCalledTimes(1);
  });
});

describe("WEB_2_scrim: modal scrim", () => {
  it("WEB_2_scrim_click_on_the_scrim_calls_onClose_but_a_click_on_its_child_does_not", () => {
    const onClose = vi.fn();
    const { container } = mount(
      <ModalScrim onClose={onClose}>
        <div data-testid="card">Opening city</div>
      </ModalScrim>,
    );
    click(q(container, '[data-testid="card"]'));
    expect(onClose).not.toHaveBeenCalled();
    click(q(container, ".park-scrim"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("WEB_2_scrim_without_onClose_ignores_clicks_and_renders_its_children", () => {
    const { container } = mount(
      <ModalScrim>
        <span data-testid="kid">kid</span>
      </ModalScrim>,
    );
    click(q(container, ".park-scrim"));
    expect(q(container, '[data-testid="kid"]').textContent).toBe("kid");
  });

  it("WEB_2_scrim_inline_flag_adds_the_inline_class_for_galleries", () => {
    const { container } = mount(<ModalScrim inline>x</ModalScrim>);
    expect(classesOf(q(container, ".park-scrim"))).toContain("park-scrim--inline");
  });
});
