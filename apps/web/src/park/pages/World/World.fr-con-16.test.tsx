// @vitest-environment happy-dom
// FR-CON-16 (Must): Lovable link card on the World page. When a run has a build-handoff artifact,
// the World page shows a "Build this in Lovable" card with the exact prompt text, the files that
// would leave Tilo, and an "Open in Lovable" control that stays disabled until the person approves
// the card through app.decide(key); once approved, it links to `https://lovable.dev/#prompt=...`
// in a new tab (target="_blank" rel="noopener noreferrer"). Nothing is sent by Tilo itself.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q } from "../../../../test-support/park/componentsHarness";
import {
  climb,
  control,
  decideCalls,
  elWithText,
  hasControl,
  mountWorld,
  pageText,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { createFixtureApi } from "../../api/fixtureApi";
import * as fx from "../../api/fixtures";
import type { Api } from "../../api/index";
import { NotBuilt, createLiveApi } from "../../api/liveApi";
import type { BuildHandoff } from "../../api/types";
import {
  LOVABLE_LINK_PREFIX,
  MAX_LOVABLE_PROMPT_CHARS,
  MAX_LOVABLE_URL_LENGTH,
  buildLovableUrl,
} from "./lovableHandoff";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const lovableCard = (root: HTMLElement): HTMLElement =>
  climb(elWithText(root, "Build this in Lovable"), (n) =>
    n.classList.contains("park-world-lovable"),
  );

describe("FR_CON_16: Build this in Lovable card on the World page", () => {
  it("FR_CON_16_world_page_shows_Build_this_in_Lovable_card_with_exact_prompt_and_files_leaving_Tilo", async () => {
    const handoff = fx.buildHandoffs[0] as BuildHandoff;
    expect(handoff).toBeDefined();

    const { el } = await mountWorld({ id: handoff.world });
    const card = lovableCard(el);
    expect(textOf(card)).toContain("Build this in Lovable");

    // Exact prompt text must be rendered verbatim inside a <pre> block (never truncated or paraphrased).
    const pre = q(card, "pre");
    expect(pre.textContent).toBe(handoff.prompt);

    // Every granted file that would leave Tilo is listed on the card.
    for (const file of handoff.files) {
      expect(textOf(card), file.path).toContain(file.path);
      expect(textOf(card), file.summary).toContain(file.summary);
    }
    expect(textOf(card)).toContain("Nothing is sent by Tilo itself");

    // A world without a build-handoff artifact does not render the card.
    cleanup();
    const other = await mountWorld({ id: "hires" });
    expect(pageText(other.el)).not.toContain("Build this in Lovable");
  });

  it("FR_CON_16_Open_in_Lovable_button_is_disabled_until_approved_through_decide_then_opens_new_tab_with_noopener_noreferrer", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no network"));
    const handoff = fx.buildHandoffs[0] as BuildHandoff;

    const rig = await mountWorld({ id: handoff.world, dec: {} });
    const cardBefore = lovableCard(rig.el);

    // Before approval, "Open in Lovable" is disabled and has no href.
    const openBefore = control(cardBefore, "Open in Lovable");
    expect(
      openBefore.hasAttribute("disabled") || openBefore.getAttribute("aria-disabled") === "true",
    ).toBe(true);
    expect(openBefore.getAttribute("href")).toBeNull();

    // Clicking the card's approval button calls app.decide(handoff.decisionKey) and sends nothing over the network.
    const approveBtn = control(cardBefore, handoff.approveLabel);
    click(approveBtn);
    expect(decideCalls(rig.app)).toEqual([[handoff.decisionKey]]);
    expect(fetchSpy).not.toHaveBeenCalled();

    // Once approved in app.dec, the approval button is replaced by the done line and "Open in Lovable" becomes an active link.
    await rig.setDec({ [handoff.decisionKey]: true });
    const cardAfter = lovableCard(rig.el);
    expect(hasControl(cardAfter, handoff.approveLabel)).toBe(false);
    expect(textOf(cardAfter)).toContain(handoff.doneLabel);

    const openAfter = control(cardAfter, "Open in Lovable");
    expect(openAfter.tagName).toBe("A");
    expect(openAfter.hasAttribute("disabled")).toBe(false);
    expect(openAfter.getAttribute("aria-disabled")).toBeNull();
    expect(openAfter.getAttribute("href")).toBe(
      `${LOVABLE_LINK_PREFIX}${encodeURIComponent(handoff.prompt)}`,
    );
    expect(openAfter.getAttribute("target")).toBe("_blank");
    expect(openAfter.getAttribute("rel")).toBe("noopener noreferrer");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("FR_CON_16_Lovable_URL_is_built_with_encodeURIComponent_and_capped_at_contract_size_limits", async () => {
    expect(LOVABLE_LINK_PREFIX).toBe("https://lovable.dev/#prompt=");
    expect(MAX_LOVABLE_PROMPT_CHARS).toBe(50_000);
    expect(MAX_LOVABLE_URL_LENGTH).toBe(32_000);

    // Special characters (#, &, ?, =, spaces, £) are percent-encoded with encodeURIComponent.
    const specialPrompt = "Build portal: #1 priority & budget <= £3,420? Yes/No = true";
    const built = buildLovableUrl(specialPrompt);
    expect(built).toBe(`https://lovable.dev/#prompt=${encodeURIComponent(specialPrompt)}`);

    // Empty prompt is refused.
    expect(buildLovableUrl("")).toBeNull();

    // Prompt at exact URL cap (32,000 - 28 = 31,972 ASCII chars) succeeds; 1 char over is refused (never truncated).
    const maxAsciiPromptChars = MAX_LOVABLE_URL_LENGTH - LOVABLE_LINK_PREFIX.length;
    const exactCapUrl = buildLovableUrl("a".repeat(maxAsciiPromptChars));
    expect(exactCapUrl).toHaveLength(MAX_LOVABLE_URL_LENGTH);
    expect(buildLovableUrl("a".repeat(maxAsciiPromptChars + 1))).toBeNull();

    // Prompt exceeding MAX_LOVABLE_PROMPT_CHARS (even with a larger custom URL cap) is refused.
    expect(
      buildLovableUrl("a".repeat(MAX_LOVABLE_PROMPT_CHARS + 1), {
        maxPromptChars: MAX_LOVABLE_PROMPT_CHARS,
        maxUrlLength: 100_000,
      }),
    ).toBeNull();

    // In the UI, if a build handoff exceeds the contract's URL length limit, "Open in Lovable" stays disabled even when approved.
    const base = createFixtureApi();
    const oversizedPrompt = "x".repeat(maxAsciiPromptChars + 10);
    const api: Api = {
      ...base,
      getBuildHandoff: async () => {
        const r = await base.getBuildHandoff();
        const first = r.data[0] as BuildHandoff;
        return {
          ...r,
          data: [{ ...first, prompt: oversizedPrompt }],
        };
      },
    };
    const handoff = fx.buildHandoffs[0] as BuildHandoff;
    const { el } = await mountWorld({
      id: handoff.world,
      api,
      dec: { [handoff.decisionKey]: true },
    });
    const card = lovableCard(el);
    const openCtrl = control(card, "Open in Lovable");
    expect(
      openCtrl.hasAttribute("disabled") || openCtrl.getAttribute("aria-disabled") === "true",
    ).toBe(true);
    expect(openCtrl.getAttribute("href")).toBeNull();
  });

  it("FR_CON_16_fixture_and_live_Api_getBuildHandoff_contract", async () => {
    const fixtureApi = createFixtureApi();
    const res = await fixtureApi.getBuildHandoff();
    expect(res.source).toBe("fixture");
    expect(res.data).toEqual(fx.buildHandoffs);
    expect(res.data).not.toBe(fx.buildHandoffs);

    const liveApi = createLiveApi();
    const outcome = await liveApi.getBuildHandoff().then(
      (v) => ({ resolved: v }),
      (e: unknown) => ({ rejected: e }),
    );
    expect(outcome).not.toHaveProperty("resolved");
    const { rejected } = outcome as { rejected: NotBuilt };
    expect(rejected).toBeInstanceOf(NotBuilt);
    expect(rejected.code).toBe("not_built");
  });
});
