// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { clickEl, mountSkills, skillsApi } from "../../../../test-support/park/skillsHarness";
import { TiloApiError } from "../../../api/http";
import { createLiveApi } from "../../api/liveApi";
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("NFR22 Skills reads show mapped refusal, then Retry loads once without writing", async () => {
  const consoleError = vi.spyOn(console, "error");
  const api = skillsApi();
  api.getSkills.mockRejectedValueOnce(new TiloApiError("rate_limited", 429, false));
  const root = await mountSkills({ api });
  const box = root.el.querySelector<HTMLElement>("[data-api-read-state]");
  expect(box?.textContent).toContain("Too many requests. Wait a moment and try again.");
  expect(box?.style.blockSize).toBe("176px");
  const retry = box?.querySelector("button");
  if (!retry) throw new Error("Skills Retry missing");
  await act(async () => {
    clickEl(retry);
  });
  expect(api.getSkills).toHaveBeenCalledTimes(2);
  expect(api.getLearn).toHaveBeenCalledTimes(2);
  expect(api.saveSkill).not.toHaveBeenCalled();
  expect(root.el.querySelector("[role=alert]")).toBeNull();
  expect(consoleError).not.toHaveBeenCalled();
});
it("NFR22 Skills keeps honest NotBuilt separate from retryable API failure", async () => {
  const root = await mountSkills({ api: createLiveApi() });
  expect(root.el.textContent).toContain("Skills data is unavailable");
  expect(root.el.querySelector("[data-api-read-state]")).toBeNull();
});
