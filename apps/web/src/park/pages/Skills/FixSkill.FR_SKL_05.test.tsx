// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { skillFromRow } from "../../api/live/skillsFromApi";
import { installSkillFixer } from "../../api/skillFixes";
import type { Skill } from "../../api/types";
import { FixSkill } from "./FixSkill";

afterEach(cleanup);
const skill = () =>
  skillFromRow({
    id: "tsk_fix",
    name: "Read",
    scope: { kind: "just_me", team: null },
    status: "learning",
    paused: false,
    question: null,
    version: 1,
    plan: [
      { text: "Read mail", tool: "gmail", action: "read_email", ask_first: false, must_ask: true },
    ],
  });

it("FR_SKL_05_acknowledges_only_after_persistence_and_keeps_locked_ask_first", async () => {
  const api = createFixtureApi() as Api;
  let resolve!: (next: Skill) => void;
  const fix = vi.fn(
    () =>
      new Promise<Skill>((done) => {
        resolve = done;
      }),
  );
  installSkillFixer(api, fix);
  const saved = vi.fn();
  const before = skill();
  const m = mount(<FixSkill api={api} skill={before} saved={saved} />);
  const ask = m.container.querySelector<HTMLInputElement>('input[type="checkbox"]');
  expect(ask?.checked).toBe(true);
  expect(ask?.disabled).toBe(true);
  const submit = m.container.querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!submit) throw new Error("missing submit");
  click(submit);
  expect(fix).toHaveBeenCalledTimes(1);
  expect(fix).toHaveBeenCalledWith("tsk_fix", {
    from_version: 1,
    step: 1,
    text: "Read mail",
    ask_first: true,
    rating: null,
  });
  expect(m.container.querySelector("fieldset")?.disabled).toBe(true);
  click(submit);
  expect(fix).toHaveBeenCalledTimes(1);
  expect(saved).not.toHaveBeenCalled();
  const next = { ...before, fix: { version: 2, asks: [true], locked: [true] } };
  await act(async () => {
    resolve(next);
    await Promise.resolve();
  });
  expect(saved).toHaveBeenCalledTimes(1);
  expect(saved).toHaveBeenCalledWith(next);
});

it("FR_SKL_05_failed_persistence_never_acknowledges_or_retries", async () => {
  const api = createFixtureApi() as Api;
  const fix = vi.fn(async () => {
    throw new Error("refused");
  });
  installSkillFixer(api, fix);
  const saved = vi.fn();
  const m = mount(<FixSkill api={api} skill={skill()} saved={saved} />);
  const submit = m.container.querySelector('button[type="submit"]');
  if (!submit) throw new Error("missing submit");
  await act(async () => {
    click(submit);
    await Promise.resolve();
  });
  expect(fix).toHaveBeenCalledTimes(1);
  expect(saved).not.toHaveBeenCalled();
  expect(m.container.querySelector("output")?.textContent).toContain("Could not save the fix");
});

it("FR_SKL_05_drafts_have_no_fix_submission", () => {
  const api = createFixtureApi() as Api;
  const fix = vi.fn();
  installSkillFixer(api, fix);
  const m = mount(<FixSkill api={api} skill={{ ...skill(), st: "draft" }} saved={vi.fn()} />);
  expect(m.container.querySelector("form")).toBeNull();
  expect(fix).not.toHaveBeenCalled();
});
