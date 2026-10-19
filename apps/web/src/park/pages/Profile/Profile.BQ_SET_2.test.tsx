// @vitest-environment happy-dom
// BQ-SET-2 (docs/open-questions.md, DECIDED 8 Oct, user approved): the honest copy of FR-SET-01 ("kept on this device
// only") and FR-SET-02 ("never hidden by quiet hours") is VISIBLE text on the Profile and Notifications tabs, in the
// design's small muted helper style, as well as the aria-description and title it already had. The exact strings are
// pinned in test-support/park/profileExpect.ts (PROFILE_COPY.saveNote, NOTIF_COPY.quietNote); the "no extra string"
// check in Profile.render.test.tsx now includes them and nothing else.
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { NOTIF_COPY, PROFILE_COPY } from "../../../../test-support/park/profileExpect";
import { buttonNamed, cleanup, openTab, renderProfile, switchNamed } from "./testApp";

afterEach(cleanup);

/** The elements whose own text is exactly `s`, so a tooltip or description never counts as visible. */
const visible = (root: ParentNode, s: string): Element[] =>
  [...root.querySelectorAll("*")].filter(
    (e) =>
      e.tagName !== "STYLE" &&
      [...e.childNodes].some((n) => n.nodeType === 3 && (n.textContent ?? "").trim() === s),
  );

describe("BQ_SET_2 profile: the save line is visible text", () => {
  it("BQ_SET_2 profile: 'Kept on this device only' is one visible paragraph in the Profile card, above the Cancel and Save footer", async () => {
    const { root } = await renderProfile(makeApp());
    const hits = visible(root, PROFILE_COPY.saveNote);
    expect(hits, "exactly one visible element").toHaveLength(1);
    const note = hits[0] as HTMLElement;
    expect(note.tagName).toBe("P");
    expect(note.closest('section[aria-label="Profile"]')).not.toBeNull();
    expect(note.closest("button"), "not inside a control").toBeNull();
    const foot = buttonNamed(root, "Save changes").parentElement as HTMLElement;
    expect(
      note.compareDocumentPosition(foot) & Node.DOCUMENT_POSITION_FOLLOWING,
      "the line comes before the footer",
    ).toBeTruthy();
    expect(foot.contains(note), "the line is not between Cancel and Save").toBe(false);
  });

  it("BQ_SET_2 profile: the Save button keeps its aria-description and title, word for word the visible line", async () => {
    const { root } = await renderProfile(makeApp());
    const save = buttonNamed(root, "Save changes");
    expect(save.getAttribute("aria-description")).toBe(PROFILE_COPY.saveNote);
    expect(save.getAttribute("title")).toBe(PROFILE_COPY.saveNote);
    expect(save.textContent?.trim(), "the button's name is unchanged").toBe("Save changes");
  });

  it("BQ_SET_2 profile: the line is on the Profile tab only", async () => {
    const { root } = await renderProfile(makeApp());
    for (const label of ["Notifications", "Appearance", "Security", "Plan and billing"]) {
      await openTab(root, label);
      expect(visible(root, PROFILE_COPY.saveNote), label).toHaveLength(0);
    }
  });

  it("BQ_SET_2 profile: the line is in the design's helper style (a class of the page stylesheet), and sets no inline style", async () => {
    const { root } = await renderProfile(makeApp());
    const note = visible(root, PROFILE_COPY.saveNote)[0] as HTMLElement;
    expect(note.className).toBe("park-profile-note");
    expect(note.getAttribute("style")).toBeNull();
    const css = fs.readFileSync(path.join(__dirname, "Profile.css"), "utf8");
    const body = /\.park-profile-note\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(body).toMatch(/font-size:\s*12\.5px/);
    expect(body).toMatch(/font-weight:\s*600/);
    expect(body).toMatch(/color:\s*var\(--ink3\)/);
    expect(body, "static text: no positioning that could shift the layout").not.toMatch(
      /position:\s*(?:absolute|fixed)|transform|animation|transition/,
    );
  });
});

describe("BQ_SET_2 notifications: the quiet hours line is visible text", () => {
  it("BQ_SET_2 notifications: 'a decision that needs you is never hidden by quiet hours' is one visible paragraph under the Quiet hours row", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    const hits = visible(root, NOTIF_COPY.quietNote);
    expect(hits, "exactly one visible element").toHaveLength(1);
    const note = hits[0] as HTMLElement;
    expect(note.tagName).toBe("P");
    expect(note.className).toBe("park-profile-note");
    expect(note.closest('section[aria-label="Notifications"]')).not.toBeNull();
    const row = switchNamed(root, NOTIF_COPY.quietLabel).parentElement as HTMLElement;
    expect(row.contains(note), "outside the row, so the row keeps its two lines").toBe(false);
    expect(row.nextElementSibling, "directly after the row").toBe(note);
  });

  it("BQ_SET_2 notifications: the Quiet hours switch keeps its aria-description, word for word the visible line", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    expect(switchNamed(root, NOTIF_COPY.quietLabel).getAttribute("aria-description")).toBe(
      NOTIF_COPY.quietNote,
    );
  });

  it("BQ_SET_2 notifications: the line is on the Notifications tab only", async () => {
    const { root } = await renderProfile(makeApp());
    for (const label of ["Profile", "Appearance", "Security", "Plan and billing"]) {
      await openTab(root, label);
      expect(visible(root, NOTIF_COPY.quietNote), label).toHaveLength(0);
    }
  });
});
