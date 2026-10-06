// @vitest-environment happy-dom
// WEB-10 render + copy (plan section 10; design "Tilo App Team.dc.html", inventory.md "Team"): every designed
// element is on the page, every visible string is the design's, the data comes only through the park Api, and
// the page never passes fixture numbers off as live. Interface pinned here, for the builder:
// - `TeamPage({ app })` from ./TeamPage; an optional `api?: Api` prop overrides the default (fixture) Api, so a
//   test can inject a spy or the live stub (the default comes from useParkApi() once WEB-3a lands it).
// - members and matrix rows are <tr> or role="row" elements; a row's DIRECT children are its columns in the design's order;
//   a matrix cell carries data-granted="true|false"; the coverage section (aria-label "Approval coverage")
//   rows are role="row" too (4 children: what, who, wait, action).
// - the helped bar is the element inside the HELPED TILO cell with an inline width ("61%").
// Defaults taken where the design/PRD is silent (listed in the WEB-10 report): the page adds no copy of its
// own (the shell shows "Sample data"), "1 people" is the design's own count formula, kept for parity.
import { afterEach, describe, expect, it } from "vitest";
import * as fx from "../../api/fixtures";
import { createLiveApi } from "../../api/liveApi";
import { COPY, COVERAGE, FIRST_PAINT_STRINGS, MATRIX, PEOPLE, ROLES, RULES } from "./teamExpect";
import {
  cleanup,
  inputNamed,
  makeApp,
  maybeSelectOf,
  ownText,
  region,
  renderTeam,
  rowsOf,
  selectNamed,
  selectOf,
  spyApi,
  strings,
  switchNamed,
} from "./testApp";

afterEach(cleanup);

const text = (el: Element | null | undefined): string => (el?.textContent ?? "").trim();
const kids = (el: Element): Element[] => [...el.children];

describe("WEB_10_team_render: heading, intro and invite field", () => {
  it("WEB_10_team_renders_heading_count_intro_and_invite_row", async () => {
    const { root } = await renderTeam(makeApp());
    const h1s = [...root.querySelectorAll("h1")];
    expect(h1s.map(text), "exactly one h1, the page title").toEqual([COPY.title]);
    expect(strings(root).has(COPY.count), "count beside the title").toBe(true);
    expect(strings(root).has(COPY.intro)).toBe(true);
    const email = inputNamed(root, "Invite by email");
    expect(email.placeholder).toBe(COPY.emailPlaceholder);
    expect(email.value).toBe("");
    expect(email.closest("div")?.querySelector("svg"), "mail icon inside the field").not.toBeNull();
    const invite = [...root.querySelectorAll("button")].find((b) => text(b) === COPY.invite);
    expect(invite, "Invite button").toBeDefined();
    expect(invite?.disabled, "never disabled: it explains itself with a toast instead").toBe(false);
  });

  it("WEB_10_team_has_one_filled_primary_button_UX_1", async () => {
    const { root } = await renderTeam(makeApp());
    expect(root.querySelectorAll("button.park-btn--primary")).toHaveLength(1);
  });
});

describe("WEB_10_team_render: members", () => {
  it("WEB_10_team_members_table_has_the_design_header_and_five_people_in_order", async () => {
    const { root } = await renderTeam(makeApp());
    const members = region(root, "Members");
    const rows = rowsOf(members);
    expect(rows, "one header row plus five people").toHaveLength(1 + PEOPLE.length);
    const header = rows[0] as HTMLElement;
    expect(kids(header).map(text), "six columns, the last (more button) has no title").toEqual([
      ...COPY.headers,
      "",
    ]);
    PEOPLE.forEach((p, i) => {
      const row = rows[i + 1] as HTMLElement;
      const cols = kids(row);
      expect(cols, `${p.name}: six columns`).toHaveLength(6);
      const [who, role, limit, helped, active, more] = cols as [
        HTMLElement,
        HTMLElement,
        HTMLElement,
        HTMLElement,
        HTMLElement,
        HTMLElement,
      ];
      expect(strings(who), `${p.name}: avatar initials, name, email and team`).toEqual(
        new Set(p.id === "am" ? [p.init, p.name, COPY.you, p.sub] : [p.init, p.name, p.sub]),
      );
      const select = selectOf(role);
      expect(select.getAttribute("aria-label")).toBe(`Role for ${p.name}`);
      expect(select.value).toBe(p.role);
      expect([...select.options].map((o) => o.value)).toEqual([...ROLES]);
      expect(select.disabled, `${p.name}: only your own role is locked`).toBe(p.id === "am");
      expect(text(limit)).toBe(p.limit);
      expect(ownText(helped.firstElementChild as Element)).toBe(p.helped);
      const bar = [...helped.querySelectorAll<HTMLElement>("[style]")].find((e) => e.style.width);
      expect(bar?.style.width, `${p.name}: helped bar width`).toBe(p.bar);
      expect(text(active)).toBe(p.active);
      const btn = more.tagName === "BUTTON" ? more : (more.querySelector("button") as Element);
      expect(btn.getAttribute("aria-label")).toBe(`Show details for ${p.name}`);
      expect(btn.getAttribute("aria-expanded")).toBe("false");
    });
  });

  it("WEB_10_team_only_you_is_marked_and_no_one_is_a_backup_at_first", async () => {
    const { root } = await renderTeam(makeApp());
    const members = region(root, "Members");
    expect([...members.querySelectorAll("*")].filter((e) => ownText(e) === COPY.you)).toHaveLength(
      1,
    );
    expect(strings(members).has("Backup approver")).toBe(false);
  });
});

describe("WEB_10_team_render: approval coverage", () => {
  it("WEB_10_team_coverage_section_has_title_sub_link_and_four_rows", async () => {
    const { root } = await renderTeam(makeApp());
    const cov = region(root, "Approval coverage");
    expect([...cov.querySelectorAll("h2")].map(text)).toEqual([COPY.coverageTitle]);
    expect(strings(cov).has(COPY.coverageSub)).toBe(true);
    const link = [...cov.querySelectorAll("a")].find((a) => text(a) === COPY.waitLink);
    expect(link, "See wait times link").toBeDefined();
    const rows = rowsOf(cov);
    expect(rows).toHaveLength(COVERAGE.length);
    COVERAGE.forEach((c, i) => {
      const [what, who, wait, action] = kids(rows[i] as Element) as [
        HTMLElement,
        HTMLElement,
        HTMLElement,
        HTMLElement,
      ];
      expect(text(what)).toBe(c.what);
      const titles = [...who.querySelectorAll("[title]")].map((e) => e.getAttribute("title"));
      expect(titles, `${c.what}: approver avatars`).toEqual([...c.who]);
      expect([...who.querySelectorAll("[title]")].map(ownText)).toEqual([...c.initials]);
      expect(strings(who).has(c.names), `${c.what}: names`).toBe(true);
      expect(text(wait)).toBe(c.wait);
      const select = maybeSelectOf(action);
      if (c.covered) {
        expect(select, `${c.what}: covered rows have no backup picker`).toBeNull();
        expect(text(action)).toBe(COPY.covered);
        expect(action.querySelector("svg"), "check icon before Covered").not.toBeNull();
      } else {
        expect(text(action).startsWith(COPY.covered), `${c.what}: not covered`).toBe(false);
        expect(select?.getAttribute("aria-label")).toBe(`Add a backup for ${c.what}`);
        expect(select?.value).toBe("");
        expect(select?.options[0]?.textContent).toBe(COPY.addBackup);
        expect([...(select?.options ?? [])].slice(1).map(text)).toEqual([...c.options]);
        expect([...(select?.options ?? [])].slice(1).map((o) => o.value)).toEqual(
          c.options.map((n) => PEOPLE.find((p) => p.name === n)?.id),
        );
      }
    });
  });

  it("WEB_10_team_a_backup_in_prefs_from_the_ledger_is_shown_as_covered_at_once", async () => {
    // README: prefs.backup is set by Team and read back; with "tr" set, sharing has two approvers.
    const { root } = await renderTeam(makeApp({ prefs: { backup: "tr" } }));
    const rows = rowsOf(region(root, "Approval coverage"));
    const [, who, wait, action] = kids(rows[2] as Element);
    expect(strings(who as Element).has("Jin, Tom")).toBe(true);
    expect(text(wait)).toBe("About 20 min");
    expect(text(action)).toBe(COPY.covered);
    const members = rowsOf(region(root, "Members"));
    expect(strings(members[4] as Element).has("Backup approver"), "Tom is the backup").toBe(true);
  });
});

describe("WEB_10_team_render: rules and role matrix", () => {
  it("WEB_10_team_rules_card_has_the_asking_agent_and_five_switches", async () => {
    const { root } = await renderTeam(makeApp());
    const rules = region(root, "Approval rules");
    expect([...rules.querySelectorAll("h2")].map(text)).toEqual([COPY.rulesTitle]);
    expect(strings(rules).has(COPY.rulesSub)).toBe(true);
    expect(
      rules.querySelector("img"),
      "builder agent art (kit.agent renders an img) in the 44px amber tile",
    ).not.toBeNull();
    const switches = [...rules.querySelectorAll('[role="switch"]')];
    expect(switches.map((s) => s.getAttribute("aria-label"))).toEqual(RULES.map((r) => r[0]));
    for (const [when, who, on] of RULES) {
      const sw = switchNamed(rules, when);
      expect(sw.getAttribute("aria-checked"), when).toBe(String(on));
      expect(text(sw.parentElement?.firstElementChild), `${when}: title then sentence`).toBe(
        `${when}${who}`,
      );
    }
  });

  it("WEB_10_team_role_matrix_is_8_rules_by_4_roles_with_the_designed_checks", async () => {
    const { root } = await renderTeam(makeApp());
    const card = region(root, "What each role can do");
    expect([...card.querySelectorAll("h2")].map(text)).toEqual([COPY.matrixTitle]);
    const rows = rowsOf(card);
    expect(rows, "header plus eight rows").toHaveLength(1 + MATRIX.length);
    expect(
      kids(rows[0] as Element)
        .map(text)
        .filter(Boolean),
    ).toEqual([...ROLES]);
    MATRIX.forEach(([label, granted], i) => {
      const row = rows[i + 1] as Element;
      expect(text(kids(row)[0]), `row ${i}`).toBe(label);
      const cells = [...row.querySelectorAll("[data-granted]")];
      expect(
        cells.map((c) => c.getAttribute("data-granted")),
        label,
      ).toEqual(granted.map(String));
      for (const c of cells) expect(c.querySelector("svg"), `${label}: tick or dot`).not.toBeNull();
    });
  });
});

describe("WEB_10_team_copy: every visible string is the design's", () => {
  it("WEB_10_team_exact_copy_first_paint_has_no_missing_and_no_extra_string", async () => {
    const { root } = await renderTeam(makeApp());
    const got = strings(root);
    const want = new Set(FIRST_PAINT_STRINGS);
    expect({
      missing: [...want].filter((s) => !got.has(s)),
      extra: [...got].filter((s) => !want.has(s)),
    }).toEqual({ missing: [], extra: [] });
  });

  it("WEB_10_team_exact_copy_keeps_the_curly_apostrophe_and_ellipsis", async () => {
    const { root } = await renderTeam(makeApp());
    const got = strings(root);
    expect(got.has("Actions that can’t be undone")).toBe(true);
    expect(got.has("Add a backup…")).toBe(true);
    expect(got.has("Actions that can't be undone")).toBe(false);
  });

  it("WEB_10_team_accessible_names_match_the_design", async () => {
    const { root } = await renderTeam(makeApp());
    for (const n of ["Invite by email", "Members", "Approval coverage", "Approval rules"]) {
      expect(root.querySelector(`[aria-label="${n}"]`), n).not.toBeNull();
    }
    expect(root.querySelector('[aria-label="What each role can do"]')).not.toBeNull();
    for (const p of PEOPLE) selectNamed(root, `Role for ${p.name}`);
  });
});

describe("WEB_10_team_data: through the park Api only", () => {
  it("WEB_10_team_reads_team_helpers_skills_and_worlds_through_the_api", async () => {
    const api = spyApi();
    const added = [fx.makeWorld("quick", "Sort the mail", 1)];
    const app = makeApp({ added, dec: { depot: true, mail: false } });
    const { root } = await renderTeam(app, api);
    expect(api.getTeam).toHaveBeenCalled();
    expect(api.getLearn, "helper counts come from learn.helpers").toHaveBeenCalled();
    expect(api.getSkills, "OWNS SKILLS").toHaveBeenCalled();
    expect(
      api.getWorlds,
      "OWNS WORLDS reads the worlds with the shell's dec and added",
    ).toHaveBeenCalledWith(app.dec, added);
    expect(root.textContent).toContain("Alex Morgan");
  });

  it("WEB_10_team_not_connected_shows_not_connected_yet_and_no_sample_numbers", async () => {
    // Plan 6.1: a page whose endpoint is NotBuilt says so; it never shows sample numbers as if real.
    const { root } = await renderTeam(makeApp(), createLiveApi());
    expect(root.textContent).toContain("Not connected yet");
    for (const p of PEOPLE) expect(root.textContent, p.name).not.toContain(p.name);
    for (const s of ["£2,500", "2 h 10 min", "Operations lead"])
      expect(root.textContent).not.toContain(s);
    expect(root.querySelector("h1")?.textContent).toBe(COPY.title);
  });

  it("WEB_10_team_makes_no_live_or_real_time_claim_about_sample_data", async () => {
    // The shell owns the "Sample data" chip (README of the plan, section 10); the page must not contradict it.
    const { root } = await renderTeam(makeApp());
    expect(root.textContent ?? "").not.toMatch(/\blive\b|real[- ]time|just now|updated/i);
  });

  it("WEB_10_team_night_renders_the_same_content", async () => {
    const day = await renderTeam(makeApp());
    const dayStrings = strings(day.root);
    cleanup();
    const night = await renderTeam(makeApp({ time: "night", night: true }));
    expect(strings(night.root)).toEqual(dayStrings);
    expect(night.root.querySelector('[aria-label="Approval rules"] img')).not.toBeNull();
  });
});
