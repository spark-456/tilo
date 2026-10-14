import { expect, it, vi } from "vitest";
import { prefetchPage } from "./prefetch";

const loaded = vi.hoisted(() => ({ ledger: vi.fn(), worlds: vi.fn(), skills: vi.fn() }));
vi.mock("../pages/Ledger/LedgerPage", () => {
  loaded.ledger();
  return {};
});
vi.mock("../pages/Worlds/WorldsPage", () => {
  loaded.worlds();
  return {};
});
vi.mock("../pages/Skills/SkillsPage", () => {
  loaded.skills();
  return {};
});

it("X-PERF-1 intent prefetch fetches only the requested page", async () => {
  prefetchPage("home");
  prefetchPage("ledger");
  await vi.waitFor(() => expect(loaded.ledger).toHaveBeenCalledOnce());
  expect(loaded.worlds).not.toHaveBeenCalled();
  expect(loaded.skills).not.toHaveBeenCalled();
});
