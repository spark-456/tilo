// @vitest-environment happy-dom
// JUDGE-FIRST-RUN F5, F6 and F7 on Home: the greeting never says evening in the small hours, spend is shown in the unit
// the ledger was served in, a loading Home is not a blank page, and the size and depth choices sit behind Options.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import { mountHome, pendingApi, settle } from "../../../../test-support/park/homeHarness";
import { ledger } from "../../api/fixtures";
import type { Ledger } from "../../api/types";
import { greetingWord, money, spendOf } from "./homeData";

afterEach(cleanup);

describe("JUDGE_FIRST_RUN_F5 greeting and money", () => {
  it("greets by the person's hour and never says evening between midnight and five", () => {
    expect(greetingWord(1)).toBe("Hello");
    expect(greetingWord(4)).toBe("Hello");
    expect(greetingWord(5)).toBe("Good morning");
    expect(greetingWord(12)).toBe("Good afternoon");
    expect(greetingWord(17)).toBe("Good afternoon");
    expect(greetingWord(18)).toBe("Good evening");
    expect(greetingWord(23)).toBe("Good evening");
  });

  it("shows spend in the unit the ledger was served in, never assuming pounds", () => {
    expect(money(2412)).toBe("£2,412");
    expect(money(2412, "USD")).toBe("$2,412");
    const usd: Ledger = { ...ledger, currency: "USD" };
    const spend = spendOf(usd);
    expect(spend.spent.startsWith("$")).toBe(true);
    expect(spend.of.startsWith("of $")).toBe(true);
    expect(spend.forecast).not.toContain("£");
    expect(spendOf(ledger).spent.startsWith("£")).toBe(true); // the recorded sample ledger stays pounds
  });
});

describe("JUDGE_FIRST_RUN_F6 loading", () => {
  it("draws still shapes with a status while the first reads are out, then nothing of them", async () => {
    const rig = await mountHome({ api: pendingApi() });
    const status = rig.el.querySelector('[role="status"][aria-label="Loading Home"]');
    expect(status).not.toBeNull();
    expect(status?.querySelectorAll(".park-home-skeleton").length).toBeGreaterThan(0);
    expect(rig.el.textContent).not.toMatch(/\d/); // no number, no progress: nothing claims work is happening
    cleanup();
    const loaded = await mountHome();
    await settle();
    expect(loaded.el.querySelector('[aria-label="Loading Home"]')).toBeNull();
  });
});

describe("JUDGE_FIRST_RUN_F7 composer options", () => {
  it("folds Size of job and Depth behind Options, closed on the defaults, and says what they mean", async () => {
    const { el } = await mountHome();
    const options = el.querySelector<HTMLDetailsElement>("details.park-home-options");
    expect(options).not.toBeNull();
    expect(options?.open).toBe(false);
    const summary = options?.querySelector("summary");
    expect(summary?.textContent).toContain("Options");
    expect(summary?.textContent).toContain("Quick task · Thinking");
    const body = options?.textContent ?? "";
    expect(body).toContain("Size of job: how big the work is");
    expect(body).toContain("Depth: Quick answers straight away");
    expect(options?.querySelector('[aria-label="Size of job"]')).not.toBeNull();
    expect(options?.querySelector('[aria-label="Depth"]')).not.toBeNull();
    // the hint a new person needs stays outside the fold
    expect(el.querySelector(".park-home-hint")?.textContent).toContain(
      "You see the plan and the cost",
    );
  });

  it("opens by itself once a choice is not the default, so a changed choice is never hidden", async () => {
    const { el } = await mountHome();
    const routine = [
      ...el.querySelectorAll<HTMLElement>('[aria-label="Size of job"] [role="radio"]'),
    ].find((b) => b.textContent === "Routine");
    expect(routine).toBeTruthy();
    click(routine as HTMLElement);
    await settle();
    const options = el.querySelector<HTMLDetailsElement>("details.park-home-options");
    expect(options?.open).toBe(true);
    expect(options?.querySelector("summary")?.textContent).toContain("Routine · Thinking");
  });
});
