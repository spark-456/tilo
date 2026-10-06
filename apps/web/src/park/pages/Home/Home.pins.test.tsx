// @vitest-environment happy-dom
// WEB-4 acceptance: the map pins (README "Home": "Map pins: pins on the city mark three worlds. Their
// positions come from `app.pins`, which the shell computes from the scene's free spots"). The reference
// draws them inside Home: pin i of `app.pins` is world K1, Onboard 12 new hires, Invoice match (i = 0, 1, 2),
// a pill button with the world's name and a status line, a stem and a dot, at the pin's x/y in px.
// The reference drops a pin that would sit under a panel; the page's own boxes are the hero (top-left, 548
// wide), the Today panel (the right 400 px, only from 1180) and the composer (the bottom 250 px). A pin
// opens its world through `app.go("world", { id })`. The city itself comes from the shell (WEB-3b).
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { PIN_WORLDS } from "../../../../test-support/park/homeCopy";
import {
  NIGHT,
  clickEl,
  flat,
  goCalls,
  lastGo,
  mountHome,
  pinFor,
  pinsFor,
  placedAt,
  textOf,
} from "../../../../test-support/park/homeHarness";

afterEach(cleanup);

// At 1440 x 900 all three are clear of the panels: the hero ends at x 548 / y 510, the Today panel starts
// at x 1040 and the composer at y 650.
const CLEAR = [
  { x: 760, y: 300 },
  { x: 820, y: 560 },
  { x: 300, y: 600 },
];

describe("WEB_4_home_pins: three pins, one per world", () => {
  it("WEB_4_home_pins_each_pin_is_a_button_named_with_its_world_and_its_state", async () => {
    const { el } = await mountHome({ app: { pins: CLEAR } });
    expect(flat(textOf(pinFor(el, "K1 electric scooter")))).toBe(
      flat("K1 electric scooter 2 decisions need you"),
    );
    expect(flat(textOf(pinFor(el, "Onboard 12 new hires")))).toBe(
      flat("Onboard 12 new hires Running · 58%"),
    );
    expect(flat(textOf(pinFor(el, "Invoice match")))).toBe(
      flat("Invoice match Next run Mon 09:00"),
    );
    for (const name of ["K1 electric scooter", "Onboard 12 new hires", "Invoice match"]) {
      expect(pinFor(el, name).tagName, name).toBe("BUTTON");
      expect(pinFor(el, name).querySelector("svg"), `${name} icon`).not.toBeNull();
    }
  });

  it("WEB_4_home_pins_no_pins_in_app_pins_means_no_pin_on_the_page", async () => {
    const { el } = await mountHome({ app: { pins: [] } });
    for (const name of ["Invoice match", "Onboard 12 new hires"]) {
      expect(pinsFor(el, name)).toHaveLength(0);
    }
  });

  it("WEB_4_home_pins_each_pin_stands_at_its_x_and_y_in_pixels", async () => {
    const { el } = await mountHome({ app: { pins: CLEAR } });
    const names = ["K1 electric scooter", "Onboard 12 new hires", "Invoice match"];
    names.forEach((name, i) => {
      expect(placedAt(pinFor(el, name), el), name).toEqual(CLEAR[i]);
    });
  });

  it("WEB_4_home_pins_a_pin_opens_its_world_through_app_go", async () => {
    const rig = await mountHome({ app: { pins: CLEAR } });
    const names = ["K1 electric scooter", "Onboard 12 new hires", "Invoice match"];
    names.forEach((name, i) => {
      clickEl(pinFor(rig.el, name));
      expect(lastGo(rig.app), name).toEqual(["world", { id: PIN_WORLDS[i] }]);
    });
    expect(goCalls(rig.app)).toBe(3);
  });

  it("WEB_4_home_pins_at_night_the_hires_pin_says_overnight", async () => {
    const { el } = await mountHome({ app: { ...NIGHT, pins: CLEAR } });
    expect(flat(textOf(pinFor(el, "Onboard 12 new hires")))).toBe(
      flat("Onboard 12 new hires Running overnight · 58%"),
    );
  });
});

describe("WEB_4_home_pins: a pin never sits under a panel", () => {
  it("WEB_4_home_pins_a_pin_under_the_hero_is_dropped_and_the_others_keep_their_world", async () => {
    const hidden = { x: 300, y: 200 }; // inside the hero's box
    const rig = await mountHome({ app: { pins: [hidden, CLEAR[0] as { x: number; y: number }] } });
    expect(pinsFor(rig.el, "K1 electric scooter")).toHaveLength(0);
    // Pin 1 is still the hires pin: the world follows the pin's index, not its place among the drawn ones.
    expect(flat(textOf(pinFor(rig.el, "Onboard 12 new hires")))).toBe(
      flat("Onboard 12 new hires Running · 58%"),
    );
  });

  it("WEB_4_home_pins_a_pin_under_the_composer_is_dropped", async () => {
    const { el } = await mountHome({ app: { pins: [{ x: 900, y: 800 }, ...CLEAR.slice(1)] } });
    expect(pinsFor(el, "K1 electric scooter")).toHaveLength(0);
    expect(pinsFor(el, "Onboard 12 new hires")).toHaveLength(1);
  });

  it("WEB_4_home_pins_a_pin_under_the_Today_panel_is_dropped_from_1180_and_shown_below_it", async () => {
    const underToday = [CLEAR[0] as { x: number; y: number }, { x: 1000, y: 300 }];
    const wide = await mountHome({ app: { pins: underToday, vw: 1440 } });
    expect(pinsFor(wide.el, "Onboard 12 new hires")).toHaveLength(0);
    cleanup();
    const narrow = await mountHome({ app: { pins: underToday, vw: 1100, vh: 900 } });
    expect(pinsFor(narrow.el, "Onboard 12 new hires"), "no side panel under 1180").toHaveLength(1);
  });
});
