import fs from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";
import { declsFor, parseRules } from "../../../test-support/park/componentsCss";

const sheets = [
  "components/park.components.css",
  "pages/Worlds/Worlds.css",
  "pages/Agenda/Agenda.css",
  "pages/Team/Team.css",
];
const rules = parseRules(
  sheets.map((file) => fs.readFileSync(path.join(__dirname, "..", file), "utf8")).join("\n"),
).rules;

// The existing CSS reader includes responsive rules. Browser enumeration in W19-phone-targets
// checks the resulting boxes; this guards the lower bounds while that run is queued on heavy.lock.
it.each([
  ["park-worlds-search__input", "", 24],
  ["park-team-input", "", 24],
  ["park-team-link", "", 24],
  ["park-agenda-addinput", "", 24],
  ["park-agenda-event", "", 24],
  ["park-worlds-new", "", 44],
  ["park-worlds-dec__yes", "", 44],
  ["park-btn park-btn--primary park-btn--md", "park-agenda-actions", 44],
  ["park-agenda-accept park-agenda-accept--soft", "", 44],
  ["park-agenda-pinit", "", 44],
])("UI_10_W19 phone target %s in %s is at least %i px tall", (classes, ancestor, minimum) => {
  const declarations = declsFor(rules, classes.split(" "), "", ancestor ? [ancestor] : []);
  // `height: auto` (a phone rule that lets long labels wrap) is not a number: only min-height holds the target then.
  const px = (name: string) => Number.parseFloat(declarations.get(name) ?? "0") || 0;
  const height = Math.max(px("height"), px("min-height"));
  expect(height).toBeGreaterThanOrEqual(minimum);
});

it("UI_10_W19 phone Invite primary action is at least 44 px", () => {
  const invite = rules.find((rule) => rule.selector === "[data-park] .park-team-invite button");
  expect(Number.parseFloat(invite?.decls.get("min-height") ?? "0")).toBeGreaterThanOrEqual(44);
  expect(Number.parseFloat(invite?.decls.get("min-width") ?? "0")).toBeGreaterThanOrEqual(44);
});
