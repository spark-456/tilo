// @vitest-environment happy-dom
// FR-TEAM-01 / 03 / 05 / 06 (design Shoulds) on the Team page. Fixture data, labelled sample: no invite is sent.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, makeApp, renderTeam } from "../../../../test-support/park/teamHarness";
import { team } from "../../api/fixtures";
import type { World } from "../../api/types";
import { isValidEmail, reassignWorlds } from "./teamModel";
import {
  buttonNamed,
  clickAndSettle,
  inputNamed,
  ownText,
  region,
  strings,
  typeInto,
} from "./testApp";

afterEach(cleanup);
const text = (el: Element | null | undefined): string => (el?.textContent ?? "").trim();
function fact(root: ParentNode, key: string): string | null {
  const hits = [...root.querySelectorAll("*")].filter((e) => ownText(e) === key);
  const k = hits[hits.length - 1];
  return k ? text(k.nextElementSibling) : null;
}

describe("FR-TEAM-01 invites", () => {
  it("FR-TEAM-01 isValidEmail rejects empty, spaces, missing @ or domain, control chars, over 254", () => {
    for (const bad of [
      "",
      " ",
      "a b@c.co",
      "ab.co",
      "a@",
      "@c.co",
      "a@b",
      "a@@b.co",
      "a@b.c",
      "a\u0000@b.co",
      "a@b.co\n",
      `${"a".repeat(250)}@b.co`,
    ]) {
      expect(isValidEmail(bad), JSON.stringify(bad)).toBe(false);
    }
    for (const ok of ["new.hire@northwind.co", "a+b@sub.example.org", "  x@y.io "]) {
      expect(isValidEmail(ok), ok).toBe(true);
    }
  });

  it("FR-TEAM-01 isValidEmail refuses Unicode control and format characters", () => {
    for (const c of ["", "​", "‮", "⁦", "﻿", "­"]) {
      expect(isValidEmail(`a${c}b@c.co`), c.charCodeAt(0).toString(16)).toBe(false);
      expect(isValidEmail(`ab@c${c}.co`), c.charCodeAt(0).toString(16)).toBe(false);
    }
  });

  it("FR-TEAM-01 the Invite button is disabled until the email is valid", async () => {
    const { root } = await renderTeam(makeApp());
    const btn = buttonNamed(root, "Invite");
    expect(btn.disabled).toBe(true);
    await typeInto(inputNamed(root, "Invite by email"), "a@b");
    expect(btn.disabled).toBe(true);
    await typeInto(inputNamed(root, "Invite by email"), "a@b.co");
    expect(btn.disabled).toBe(false);
  });

  it("FR-TEAM-01 reassignWorlds moves every world of the removed person to the Owner and no other", () => {
    const ws = [
      { id: "1", owner: "Priya Shah" },
      { id: "2", owner: "Jin Park" },
      { id: "3", owner: "Priya Shah" },
    ] as unknown as World[];
    const out = reassignWorlds(ws, "Priya Shah", "Alex Morgan");
    expect(out.map((w) => w.owner)).toEqual(["Alex Morgan", "Jin Park", "Alex Morgan"]);
    expect(ws[0]?.owner).toBe("Priya Shah");
  });

  it("FR-TEAM-01 removing a person on the page gives their worlds to the Owner", async () => {
    const { root } = await renderTeam(makeApp());
    await clickAndSettle(buttonNamed(root, "Show details for Priya Shah"));
    const hers = (fact(root, "OWNS WORLDS") ?? "").split(", ");
    expect(hers).not.toContain("None");
    await clickAndSettle(buttonNamed(root, "Remove from team"));
    await clickAndSettle(buttonNamed(root, "Show details for Alex Morgan"));
    const mine = fact(root, "OWNS WORLDS") ?? "";
    for (const w of hers) expect(mine).toContain(w);
  });
});

describe("FR-TEAM-03 who signs off", () => {
  it("FR-TEAM-03 the card lists each approval type with its approvers, average wait and a backup picker", async () => {
    const { root } = await renderTeam(makeApp());
    const card = region(root, "Approval coverage");
    const s = strings(card);
    for (const c of team.coverage) {
      expect(s.has(c.what), c.what).toBe(true);
      expect(s.has(c.wait), c.wait).toBe(true);
    }
    expect(card.querySelectorAll('select[aria-label^="Add a backup for"]').length).toBeGreaterThan(
      0,
    );
  });

  it("FR-TEAM-03 arriving from the Ledger highlights the card and scrolls to it", async () => {
    const calls: string[] = [];
    const proto = HTMLElement.prototype as unknown as { scrollIntoView?: () => void };
    const prev = proto.scrollIntoView;
    proto.scrollIntoView = function (this: HTMLElement) {
      calls.push(this.getAttribute("aria-label") ?? "");
    };
    try {
      const { root } = await renderTeam(makeApp({ params: { focus: "share" } }));
      expect(region(root, "Approval coverage").getAttribute("data-flash")).toBe("true");
      expect(calls).toContain("Approval coverage");
    } finally {
      if (prev) proto.scrollIntoView = prev;
      else Reflect.deleteProperty(proto, "scrollIntoView");
    }
  });
});

describe("FR-TEAM-05 what each role can do", () => {
  const yaml = readFileSync(resolve(__dirname, "../../../../../../config/team_rules.yaml"), "utf8");
  const ROLES = ["Owner", "Approver", "Member", "Viewer"];
  const engine = [...yaml.matchAll(/\{key: \w+, label: "([^"]+)", roles: \[([^\]]*)\]\}/g)].map(
    (m) => {
      const roles = (m[2] ?? "").split(",").map((r) => r.trim());
      return [
        m[1] ?? "",
        ROLES.reduce((n, r, i) => n + (roles.includes(r) ? 1 << i : 0), 0),
      ] as const;
    },
  );

  it("FR-TEAM-05 the fixture matrix equals the engine's role rules in config/team_rules.yaml", () => {
    expect(team.roles).toEqual(ROLES);
    expect(engine).toHaveLength(8);
    expect(team.matrix.map(([l, b]) => [l, b])).toEqual(engine.map(([l, b]) => [l, b]));
  });

  it("FR-TEAM-05 the displayed cells are the engine's cells, 8 x 4", async () => {
    const { root } = await renderTeam(makeApp());
    const rows = [...region(root, "What each role can do").querySelectorAll("tbody tr")];
    expect(rows).toHaveLength(8);
    rows.forEach((tr, i) => {
      const cells = [...tr.querySelectorAll("[data-granted]")].map(
        (c) => c.getAttribute("data-granted") === "true",
      );
      const bits = engine[i]?.[1] ?? -1;
      expect(cells).toEqual(ROLES.map((_, k) => (bits & (1 << k)) !== 0));
      expect(text(tr.querySelector("th"))).toBe(engine[i]?.[0]);
    });
  });
});

describe("FR-TEAM-06 helped Tilo is counts only", () => {
  it("FR-TEAM-06 each person shows one number and a bar; nothing else about helping", async () => {
    const { root } = await renderTeam(makeApp());
    const cells = [...region(root, "Members").querySelectorAll("td.park-team-helped")];
    expect(cells).toHaveLength(5);
    for (const td of cells) {
      expect(td.querySelectorAll(".park-team-fill")).toHaveLength(1);
      expect(text(td)).toMatch(/^\d+$/);
    }
  });

  it("FR-TEAM-06 rows keep the team's own order; the page imposes no ranking by count", async () => {
    const { root } = await renderTeam(makeApp());
    const members = region(root, "Members");
    const names = [...members.querySelectorAll(".park-team-name > span:first-child")].map(text);
    expect(names).toEqual(team.people.map((p) => p.name));
  });

  it("FR-TEAM-06 the helper type carries a count and display text only (no time, sentiment or speed fields)", () => {
    const src = readFileSync(resolve(__dirname, "../../api/types.ts"), "utf8");
    const block = /helpers: \{([^}]*)\}\[\]/.exec(src)?.[1] ?? "";
    const fields = [...block.matchAll(/(\w+)\??:/g)].map((m) => m[1]);
    expect([...fields].sort()).toEqual(["c", "id", "impact", "init", "n", "name", "you"]);
  });
});
