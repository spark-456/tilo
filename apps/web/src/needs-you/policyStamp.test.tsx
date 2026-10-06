// @vitest-environment happy-dom
// FR-WLD-09 / PRD 9.4 HR-7: a gate opened by a policy renders with the Policy stamp (round, in the
// policy colour, with the word); a gate a person approved renders without it, and both link to the
// authorisation. Uses the same fixtures as the gate sheet gallery (S-07).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import { GATE_REPLY, policyApplied, requested, resolved } from "../../test-support/needsYou";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { GateSheet } from "./GateSheet";
import { gatesOf } from "./gates";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});

async function sheet(events: Parameters<typeof gatesOf>[0]): Promise<HTMLElement> {
  const record = gatesOf(events)[0];
  if (!record) throw new Error("no gate");
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root?.render(
      <GateSheet record={record} card={GATE_REPLY} layout={LAYOUT_VILLAGE_BASIC} answer={null} />,
    ),
  );
  return container;
}

const stamps = (c: HTMLElement) => c.querySelectorAll('[data-testid="policy-stamp"]');
const authLink = (c: HTMLElement) => c.querySelector("a.pill")?.getAttribute("href") ?? "";

it("FR_WLD_09 HR-7: a policy-authorised gate renders exactly one Policy stamp and links the authorisation", async () => {
  const c = await sheet([policyApplied(5)]);
  expect(stamps(c)).toHaveLength(1);
  expect(stamps(c)[0]?.textContent).toContain("Policy");
  expect(authLink(c)).toMatch(/\/trace$/);
});

it("FR_WLD_09 HR-7: a person-authorised gate renders no Policy stamp and still links the authorisation", async () => {
  const c = await sheet([requested(1), resolved(2, "approve")]);
  expect(stamps(c)).toHaveLength(0);
  expect(authLink(c)).toMatch(/\/trace$/);
});

it("FR_WLD_09 HR-7: the stamp does not rely on colour alone and the colour is the policy token", () => {
  const css = readFileSync(join(__dirname, "../styles/app.css"), "utf8");
  const rule = /\.policy-stamp\s*\{[^}]*\}/.exec(css)?.[0] ?? "";
  expect(rule).toContain("var(--color-policy)");
  const src = readFileSync(join(__dirname, "GateSheet.tsx"), "utf8");
  expect(src).toMatch(/<svg[\s\S]*?<\/svg>\s*Policy/); // a glyph and the word, not just a tint
});
