// @vitest-environment happy-dom
// WEB-10 interactions (design "Tilo App Team.dc.html" script, inventory.md "Team" toasts; README AppCtx contract):
// invite, role change, member details, backup approvers, rule switches, the Ledger link, the focus flash.
// Each toast is the design's exact string with no extra argument; navigation is app.go only; Team never calls
// app.decide (nothing on this page approves spend). Interface pinned beyond render tests: the coverage section
// carries data-flash="true" while `params.focus === "share"` (the 1.8 s clearing needs a timer, deferred to
// WEB-3b, so it is not asserted); the expanded details block shows fact pairs (key element, then its sibling).
import fc from "fast-check";
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { press } from "../../../../test-support/park/componentsHarness";
import {
  COPY,
  COVERAGE,
  LIMIT_BY_ROLE,
  PEOPLE,
  ROLES,
} from "../../../../test-support/park/teamExpect";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import * as fx from "../../api/fixtures";
import {
  buttonNamed,
  choose,
  clickAndSettle,
  inputNamed,
  optionNames,
  ownText,
  region,
  rowsOf,
  selectNamed,
  selectOf,
  settle,
  strings,
  switchNamed,
  typeInto,
} from "./testApp";

afterEach(cleanup);

const text = (el: Element | null | undefined): string => (el?.textContent ?? "").trim();
const kids = (el: Element): HTMLElement[] => [...el.children] as HTMLElement[];
const memberRows = (root: ParentNode): HTMLElement[] => rowsOf(region(root, "Members")).slice(1);
const coverRows = (root: ParentNode): HTMLElement[] => rowsOf(region(root, "Approval coverage"));
const countText = (root: ParentNode): boolean => strings(root).has(COPY.count);
const people = (root: ParentNode): string => [...strings(region(root, "Members"))].join("|");

/** The value next to a fact key ("SIGNS OFF") in the open details block, or null when no such key. */
function fact(root: ParentNode, key: string): string | null {
  const hits = [...root.querySelectorAll("*")].filter((e) => ownText(e) === key);
  const k = hits[hits.length - 1]; // HELPED TILO is also a column header: the fact comes later
  return k ? text(k.nextElementSibling) : null;
}
const openMore = (root: ParentNode, name: string) =>
  clickAndSettle(buttonNamed(root, `Show details for ${name}`));
const linkNamed = (root: ParentNode, name: string): HTMLAnchorElement => {
  const a = [...root.querySelectorAll("a")].find((e) => text(e) === name);
  if (!a) throw new Error(`no link ${name}`);
  return a;
};

/** W10: a role, backup or removal here is this page's only: the team is a sample and nothing is stored. */
const NOT_SAVED = "This is a sample team, so nothing was saved.";
const NEW = "new.hire@northwind.co";
async function invite(root: ParentNode, value: string): Promise<void> {
  await typeInto(inputNamed(root, "Invite by email"), value);
  await clickAndSettle(buttonNamed(root, COPY.invite));
}

describe("WEB_10_team_invite: email, validation, pending row", () => {
  it.each(["", "   ", "name", "a@b", "@x.co"])(
    "WEB_10_team_invite_with_%j_toasts_the_prompt_and_adds_nobody",
    async (value) => {
      const app = makeApp();
      const { root } = await renderTeam(app);
      // FR-TEAM-01: the button is disabled while invalid, so the prompt comes from the Enter key.
      const field = inputNamed(root, "Invite by email");
      await typeInto(field, value);
      expect(buttonNamed(root, COPY.invite).disabled).toBe(true);
      await act(async () => press(field, "Enter"));
      await settle();
      expect(app.toast).toHaveBeenCalledTimes(1);
      expect(app.toast).toHaveBeenCalledWith("Enter a work email to invite");
      expect(memberRows(root)).toHaveLength(PEOPLE.length);
      expect(countText(root)).toBe(true);
    },
  );

  it("WEB_10_team_invite_valid_email_adds_a_pending_member_and_clears_the_field", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    await invite(root, `  ${NEW} `);
    expect(app.toast).toHaveBeenCalledTimes(1);
    expect(app.toast).toHaveBeenCalledWith(
      `This is a sample team, so no invite was sent to ${NEW}.`,
    );
    expect(inputNamed(root, "Invite by email").value).toBe("");
    expect(strings(root).has("6 people")).toBe(true);
    const rows = memberRows(root);
    expect(rows, "appended after the five").toHaveLength(6);
    const [who, role, limit, helped, active] = kids(rows[5] as Element) as HTMLElement[];
    expect(strings(who as Element)).toEqual(new Set(["?", NEW, "Sample invite · not sent"]));
    const select = selectOf(role as HTMLElement);
    expect(select.getAttribute("aria-label")).toBe(`Role for ${NEW}`);
    expect(select.value, "invited as Member").toBe("Member");
    expect(select.disabled).toBe(false);
    expect(text(limit)).toBe("—");
    expect(ownText((helped as HTMLElement).firstElementChild as Element)).toBe("0");
    expect(text(active)).toBe("Pending");
  });

  it("WEB_10_team_invite_enter_key_sends_like_the_button", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    const field = inputNamed(root, "Invite by email");
    await typeInto(field, NEW);
    await act(async () => press(field, "Enter"));
    await settle();
    expect(app.toast).toHaveBeenCalledWith(
      `This is a sample team, so no invite was sent to ${NEW}.`,
    );
    expect(memberRows(root)).toHaveLength(6);
  });

  it("HR_W23_team_pending_member_details_never_claim_an_invite_was_sent", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    await invite(root, NEW);
    await openMore(root, NEW);
    expect(fact(root, "INVITED AS")).toBe("Member");
    expect(fact(root, "SENT")).toBe("Not sent · sample invitation");
    expect(() => buttonNamed(root, "Remove from team")).toThrow();
    await clickAndSettle(buttonNamed(root, "Resend invite"));
    expect(app.toast).toHaveBeenLastCalledWith(
      `This is a sample team, so no invite was sent again to ${NEW}.`,
    );
    await choose(selectNamed(root, `Role for ${NEW}`), "Approver");
    expect(app.toast).toHaveBeenLastCalledWith(
      `${NEW} is now an Approver on this page. ${NOT_SAVED}`,
    );
    expect(fact(root, "INVITED AS")).toBe("Approver");
    await clickAndSettle(buttonNamed(root, "Cancel invite"));
    expect(app.toast).toHaveBeenLastCalledWith(`Invite cancelled on this page. ${NOT_SAVED}`);
    expect(memberRows(root)).toHaveLength(PEOPLE.length);
    expect(countText(root)).toBe(true);
  });
});

describe("WEB_10_team_roles: change a role", () => {
  it.each([
    ["Tom Reyes", "Approver", "an Approver", "£1,000"],
    ["Tom Reyes", "Owner", "an Owner", "No limit"],
    ["Tom Reyes", "Viewer", "a Viewer", "—"],
    ["Priya Shah", "Member", "a Member", "£250"],
  ])(
    "WEB_10_team_role_of_%s_to_%s_toasts_and_resets_the_limit",
    async (name, role, phrase, limit) => {
      const app = makeApp();
      const { root } = await renderTeam(app);
      await choose(selectNamed(root, `Role for ${name}`), role);
      expect(app.toast).toHaveBeenCalledTimes(1);
      expect(app.toast).toHaveBeenCalledWith(`${name} is now ${phrase} on this page. ${NOT_SAVED}`);
      const i = PEOPLE.findIndex((p) => p.name === name);
      expect(text(kids(memberRows(root)[i] as Element)[2])).toBe(limit);
    },
  );

  it("WEB_10_team_your_own_role_select_is_locked_to_owner", async () => {
    const { root } = await renderTeam(makeApp());
    const select = selectNamed(root, "Role for Alex Morgan");
    expect(select.disabled).toBe(true);
    expect(select.value).toBe("Owner");
  });

  it("WEB_10_team_property_any_role_sequence_keeps_limits_toasts_and_backup_options_right", async () => {
    // Invariants: the limit column is the design's table for the new role (an approver is reset to £1,000);
    // the toast names person and role with the right article; a one-approver row offers exactly the people
    // who are not you, not pending, not a Viewer and not already covering it, in team order.
    await fc.assert(
      fc.asyncProperty(
        fc.array(fc.tuple(fc.constantFrom("ps", "jp", "tr", "so"), fc.constantFrom(...ROLES)), {
          minLength: 1,
          maxLength: 5,
        }),
        async (steps) => {
          cleanup();
          const app = makeApp();
          const { root } = await renderTeam(app);
          const role = new Map<string, string>(PEOPLE.map((p) => [p.id, p.role]));
          for (const [id, next] of steps) {
            const i = PEOPLE.findIndex((p) => p.id === id);
            const who = PEOPLE[i]?.name ?? "";
            const select = selectNamed(root, `Role for ${who}`);
            if (select.value === next) continue;
            await choose(select, next);
            role.set(id, next);
            const article = next === "Approver" || next === "Owner" ? "an" : "a";
            expect(app.toast).toHaveBeenLastCalledWith(
              `${who} is now ${article} ${next} on this page. ${NOT_SAVED}`,
            );
            expect(text(kids(memberRows(root)[i] as Element)[2])).toBe(LIMIT_BY_ROLE[next]);
          }
          COVERAGE.forEach((c, i) => {
            const covering = c.who.map((n) => PEOPLE.find((p) => p.name === n)?.id);
            if (covering.length > 1) return;
            const want = PEOPLE.filter(
              (p) => p.id !== "am" && role.get(p.id) !== "Viewer" && !covering.includes(p.id),
            ).map((p) => p.name);
            const action = kids(coverRows(root)[i] as Element)[3] as HTMLElement;
            expect(optionNames(selectOf(action)), c.what).toEqual(want);
          });
        },
      ),
      { numRuns: 12 },
    );
  });
});

describe("WEB_10_team_details: the more button", () => {
  it("WEB_10_team_details_open_one_at_a_time_and_toggle_closed", async () => {
    const { root } = await renderTeam(makeApp());
    const btn = (n: string) => buttonNamed(root, n);
    await openMore(root, "Priya Shah");
    expect(btn("Hide details for Priya Shah").getAttribute("aria-expanded")).toBe("true");
    expect([...root.querySelectorAll("*")].filter((e) => ownText(e) === "SIGNS OFF")).toHaveLength(
      1,
    );
    await openMore(root, "Jin Park");
    expect(btn("Show details for Priya Shah").getAttribute("aria-expanded")).toBe("false");
    expect(btn("Hide details for Jin Park").getAttribute("aria-expanded")).toBe("true");
    expect([...root.querySelectorAll("*")].filter((e) => ownText(e) === "SIGNS OFF")).toHaveLength(
      1,
    );
    await clickAndSettle(btn("Hide details for Jin Park"));
    expect(fact(root, "SIGNS OFF")).toBeNull();
  });

  it("WEB_10_team_details_facts_for_an_approver", async () => {
    const { root } = await renderTeam(makeApp());
    await openMore(root, "Priya Shah");
    expect(fact(root, "SIGNS OFF")).toBe("Spend up to £1,000, Spend up to £2,500");
    expect(fact(root, "OWNS SKILLS")).toBe("Match invoices to purchase orders");
    expect(fact(root, "OWNS WORLDS")).toBe("Q3 audit prep, Invoice match");
    expect(fact(root, "HELPED TILO")).toBe("14 answers · invoice matching right 99% of runs");
    expect(buttonNamed(root, "Remove from team")).toBeDefined();
    expect(() => buttonNamed(root, "Resend invite")).toThrow();
  });

  it("WEB_10_team_details_facts_for_the_owner_include_worlds_started_this_session", async () => {
    const added = [fx.makeWorld("quick", "Sort the mail", 1)];
    const { root } = await renderTeam(makeApp({ added }));
    await openMore(root, "Alex Morgan");
    expect(fact(root, "SIGNS OFF")).toBe("Everything, as owner");
    expect(fact(root, "OWNS SKILLS")).toBe(
      "Triage the Accounts inbox, Set up a new starter, Log new supplier invoices",
    );
    const worlds = fx
      .worlds({}, added)
      .filter((w) => w.owner === "Alex Morgan")
      .map((w) => w.short)
      .join(", ");
    expect(worlds).toContain(added[0]?.short);
    expect(fact(root, "OWNS WORLDS")).toBe(worlds);
    expect(fact(root, "HELPED TILO")).toBe("6 fixes · 22 ratings · invoice flags halved");
    expect(() => buttonNamed(root, "Remove from team"), "you cannot remove yourself").toThrow();
  });

  it("WEB_10_team_details_facts_when_there_is_nothing_to_list", async () => {
    const { root } = await renderTeam(makeApp());
    await openMore(root, "Sam Ode");
    expect(fact(root, "SIGNS OFF")).toBe("Nothing yet");
    expect(fact(root, "OWNS SKILLS")).toBe("None");
    expect(fact(root, "OWNS WORLDS")).toBe("None");
    expect(fact(root, "HELPED TILO")).toBe("No answers or fixes yet");
  });

  it("WEB_10_team_remove_member_toasts_closes_details_and_updates_coverage", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    await openMore(root, "Priya Shah");
    await clickAndSettle(buttonNamed(root, "Remove from team"));
    expect(app.toast).toHaveBeenCalledTimes(1);
    expect(app.toast).toHaveBeenCalledWith(`Priya was removed on this page. ${NOT_SAVED}`);
    expect(strings(root).has("4 people")).toBe(true);
    expect(memberRows(root)).toHaveLength(4);
    expect(people(root)).not.toContain("Priya Shah");
    expect(fact(root, "SIGNS OFF"), "details closed").toBeNull();
    const small = kids(coverRows(root)[0] as Element);
    expect(strings(small[1] as HTMLElement).has("Jin only"), "one approver left").toBe(true);
    expect(optionNames(selectOf(small[3] as HTMLElement))).toEqual(["Tom Reyes"]);
  });
});

describe("WEB_10_team_coverage: add a backup", () => {
  it("WEB_10_team_backup_for_sharing_covers_it_sets_the_pref_and_shortens_the_wait", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    await choose(selectNamed(root, "Add a backup for Sharing outside the company"), "tr");
    expect(app.toast).toHaveBeenCalledTimes(1);
    expect(app.toast).toHaveBeenCalledWith(
      `Tom Reyes is now a backup for sharing outside the company on this page. ${NOT_SAVED}`,
    );
    expect(app.setPref).toHaveBeenCalledTimes(1);
    expect(app.setPref).toHaveBeenCalledWith("backup", "tr");
    const [, who, wait, action] = kids(coverRows(root)[2] as Element);
    expect(strings(who as HTMLElement).has("Jin, Tom")).toBe(true);
    expect(
      [...(who as HTMLElement).querySelectorAll("[title]")].map((e) => e.getAttribute("title")),
    ).toEqual(["Jin Park", "Tom Reyes"]);
    expect(text(wait)).toBe("About 20 min");
    expect(text(action)).toBe(COPY.covered);
    expect(strings(memberRows(root)[3] as Element).has("Backup approver")).toBe(true);
    await openMore(root, "Tom Reyes");
    expect(fact(root, "SIGNS OFF")).toBe("Sharing outside the company");
  });

  it("WEB_10_team_backup_for_another_row_does_not_set_the_pref_or_change_its_wait", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    await choose(selectNamed(root, "Add a backup for Spend up to £2,500"), "jp");
    expect(app.toast).toHaveBeenCalledWith(
      `Jin Park is now a backup for spend up to £2,500 on this page. ${NOT_SAVED}`,
    );
    expect(app.setPref).not.toHaveBeenCalled();
    const [, who, wait, action] = kids(coverRows(root)[1] as Element);
    expect(strings(who as HTMLElement).has("Priya, Jin")).toBe(true);
    expect(text(wait)).toBe("14 min");
    expect(text(action)).toBe(COPY.covered);
  });

  it("WEB_10_team_choosing_the_placeholder_does_nothing", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    await choose(selectNamed(root, "Add a backup for Gate sign-offs"), "");
    expect(app.toast).not.toHaveBeenCalled();
    expect(app.setPref).not.toHaveBeenCalled();
  });
});

describe("WEB_10_team_rules: switches", () => {
  it("WEB_10_team_rule_switches_toggle_independently_and_toast_nothing", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    const state = (): string[] =>
      [...region(root, "Approval rules").querySelectorAll('[role="switch"]')].map(
        (s) => s.getAttribute("aria-checked") ?? "",
      );
    expect(state()).toEqual(["true", "true", "true", "true", "false"]);
    await clickAndSettle(switchNamed(root, "Routines that fall on a weekend"));
    expect(state()).toEqual(["true", "true", "true", "true", "true"]);
    // FR-TEAM-04: the three Must-ask switches are locked on, so the independent one is "tools".
    await clickAndSettle(switchNamed(root, "Giving a skill more access to a tool"));
    expect(state()).toEqual(["true", "true", "true", "false", "true"]);
    await clickAndSettle(switchNamed(root, "Giving a skill more access to a tool"));
    expect(state()).toEqual(["true", "true", "true", "true", "true"]);
    expect(app.toast).not.toHaveBeenCalled();
  });
});

describe("WEB_10_team_nav: go() only, never decide()", () => {
  it("WEB_10_team_see_wait_times_goes_to_the_ledger_without_leaving_the_page", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    const before = location.href;
    const link = linkNamed(root, COPY.waitLink);
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    await act(async () => {
      link.dispatchEvent(click);
    });
    expect(click.defaultPrevented, "the router, not the anchor, navigates").toBe(true);
    expect(app.go).toHaveBeenCalledTimes(1);
    expect(app.go.mock.calls[0]?.[0]).toBe("ledger");
    expect(app.go.mock.calls[0]?.[1] ?? {}).toEqual({});
    expect(location.href).toBe(before);
  });

  it("WEB_10_team_nothing_on_the_page_approves_or_starts_work", async () => {
    const app = makeApp();
    const { root } = await renderTeam(app);
    await invite(root, NEW);
    await choose(selectNamed(root, "Role for Tom Reyes"), "Approver");
    await openMore(root, "Jin Park");
    await clickAndSettle(switchNamed(root, "Routines that fall on a weekend"));
    await choose(selectNamed(root, "Add a backup for Gate sign-offs"), "ps");
    await clickAndSettle(buttonNamed(root, "Remove from team"));
    expect(app.decide).not.toHaveBeenCalled();
    expect(app.addWorld).not.toHaveBeenCalled();
    expect(app.go).not.toHaveBeenCalled();
    expect(app.toast.mock.calls.every((c) => c.length === 1 && typeof c[0] === "string")).toBe(
      true,
    );
  });
});

describe("WEB_10_team_focus: arriving from the Ledger", () => {
  it("WEB_10_team_focus_share_flags_the_coverage_card_for_the_amber_flash", async () => {
    const { root } = await renderTeam(makeApp({ params: { focus: "share" } }));
    expect(region(root, "Approval coverage").getAttribute("data-flash")).toBe("true");
  });

  it("WEB_10_team_no_focus_param_means_no_flash", async () => {
    const { root } = await renderTeam(makeApp());
    expect(region(root, "Approval coverage").getAttribute("data-flash")).not.toBe("true");
  });

  it("WEB_10_team_focus_arriving_after_mount_also_flashes", async () => {
    const { m, root, tree } = await renderTeam(makeApp());
    m.render(tree(makeApp({ params: { focus: "share" } })));
    await settle();
    expect(region(root, "Approval coverage").getAttribute("data-flash")).toBe("true");
  });
});
