// @vitest-environment happy-dom
// ADR-0041 BYOK-5 (BQ-BYOK-WEB-1), SECURITY-FLAGGED: the owner's "Organisation model key" control. A fake http layer
// scripts what `byok_routes.py` answers; the real flow (`api/modelKey.ts`) and the real component run on top of it.
// The key text must be in exactly one place after submit: the one PUT body.
import { readFileSync } from "node:fs";
import path from "node:path";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  click,
  countPrimary,
  mount,
  q,
  qa,
} from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { createModelKeyFlow } from "../../../api/modelKey";
import { ModelKeyControl } from "./ModelKey";

// Assembled at runtime (root CLAUDE.md: no secret-looking literal in a fixture).
const KEY = ["byok", "Zq81XyN0pQ3rT7vW9aB2cD4eF6gH"].join("_");
const settle = () => act(async () => undefined);
const refuse = (status: number, word: string | null, retryable = false) =>
  new TiloApiError(`server said: ${KEY}`, status, retryable, true, word, false, word);

type Call = { method: string; path: string; body?: unknown };
type Answer = unknown;
function fake(script: { get: Answer[]; put?: Answer[]; del?: Answer[] }) {
  const calls: Call[] = [];
  const next = async (list: Answer[] | undefined, call: Call): Promise<unknown> => {
    calls.push(call);
    const a = list && (list.length > 1 ? list.shift() : list[0]);
    if (typeof a === "function") return (a as () => Promise<unknown>)();
    if (a instanceof Error) throw a;
    return a;
  };
  const http = {
    getJson: (path: string) => next(script.get, { method: "GET", path }),
    putJson: (path: string, body: unknown) => next(script.put, { method: "PUT", path, body }),
    deleteJson: (path: string) => next(script.del, { method: "DELETE", path }),
  };
  return { flow: createModelKeyFlow(http), calls };
}

const NONE = { active: false, label: null, state: "none", consent_version: 1 };
const ACTIVE = {
  active: true,
  label: "Example endpoint",
  state: "active",
  bundle_id: "ex",
  secret_version: 3,
  set_at: "2026-10-13T08:00:00Z",
  day_cap_credits: 500,
  consent_version: 1,
};
const text = (root: HTMLElement) => root.textContent ?? "";
const button = (root: ParentNode, label: string) =>
  qa<HTMLButtonElement>(root, "button").find((b) => b.textContent === label) as HTMLButtonElement;
function type(el: HTMLInputElement, value: string) {
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
function fillAndAgree(root: HTMLElement) {
  const inputs = qa<HTMLInputElement>(root, "input");
  const by = (t: string) =>
    inputs.find((i) => i.closest("label")?.textContent?.startsWith(t)) as HTMLInputElement;
  type(by("Bundle id"), "ex");
  type(by("API key"), KEY);
  type(by("Daily limit"), "500");
  click(by("I have read"));
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ADR-0041 BQ-BYOK-WEB-1 states", () => {
  it("BYOK_WEB_ADR_0041_off_in_this_build_is_a_calm_line_with_a_disabled_form_and_no_write", async () => {
    const { flow, calls } = fake({ get: [refuse(503, "not_configured", true)] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    expect(text(m.container)).toContain("Off in this build");
    expect(q(m.container, "fieldset").hasAttribute("disabled")).toBe(true);
    expect(button(m.container, "Save key").disabled).toBe(true);
    expect(m.container.querySelector('[role="alert"]')).toBeNull();
    click(button(m.container, "Save key"));
    await settle();
    expect(calls).toEqual([{ method: "GET", path: "/v1/org/model-key" }]);
    expect(text(m.container)).not.toContain("Key saved");
  });

  it("BYOK_WEB_ADR_0041_loading_then_failure_with_a_retry", async () => {
    let release: (v: unknown) => void = () => undefined;
    const slow = () =>
      new Promise<unknown>((r) => {
        release = r;
      });
    const a = fake({ get: [slow] });
    const m = mount(<ModelKeyControl flow={a.flow} demo={false} />);
    await settle();
    expect(text(m.container)).toContain("Loading");
    release(NONE);
    await settle();
    expect(text(m.container)).toContain("No key is set");
    cleanup();

    const b = fake({ get: [refuse(503, "unavailable", true), NONE] });
    const n = mount(<ModelKeyControl flow={b.flow} demo={false} />);
    await settle();
    expect(q(n.container, '[role="alert"]').textContent).toContain("could not read");
    expect(text(n.container)).not.toContain(KEY);
    click(button(n.container, "Try again"));
    await settle();
    expect(text(n.container)).toContain("No key is set");
    expect(b.calls.map((c) => c.method)).toEqual(["GET", "GET"]);
  });

  it("BYOK_WEB_ADR_0041_signed_out_not_the_owner_and_demo_have_their_own_words_and_no_form", async () => {
    const cases: [number, string | null, string][] = [
      [401, null, "Sign in to see or change"],
      [403, "owner_only", "Only this organisation's owner"],
    ];
    for (const [status, word, expected] of cases) {
      const { flow } = fake({ get: [refuse(status, word)] });
      const m = mount(<ModelKeyControl flow={flow} demo={false} />);
      await settle();
      expect(text(m.container)).toContain(expected);
      expect(m.container.querySelector("form")).toBeNull();
      cleanup();
    }
    const asked: string[] = [];
    const idle = async () => {
      asked.push("called");
      return { ok: false as const, problem: "unavailable" as const };
    };
    const demo = mount(<ModelKeyControl flow={{ read: idle, save: idle, remove: idle }} demo />);
    await settle();
    expect(text(demo.container)).toContain("Sign in with your own account");
    expect(demo.container.querySelector("form")).toBeNull();
    expect(asked).toEqual([]);
    cleanup();
    const bare = mount(<ModelKeyControl flow={null} demo={false} />);
    await settle();
    expect(bare.container.textContent).toBe("");
  });

  it("BYOK_WEB_ADR_0041_a_member_reads_only_where_work_goes_and_has_no_controls", async () => {
    const { flow } = fake({ get: [{ active: true, label: "Example endpoint" }] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    expect(text(m.container)).toContain("uses its own model key (Example endpoint)");
    expect(m.container.querySelector("form, input, button")).toBeNull();
    cleanup();
    const none = fake({ get: [{ active: false, label: null }] });
    const n = mount(<ModelKeyControl flow={none.flow} demo={false} />);
    await settle();
    expect(text(n.container)).toContain("uses Tilo's own model key");
    expect(n.container.querySelector("input, button")).toBeNull();
  });
});

describe("ADR-0041 BQ-BYOK-WEB-1 the key never lingers", () => {
  it("BYOK_WEB_ADR_0041_the_field_is_a_password_field_with_autocomplete_off_and_save_needs_consent", async () => {
    const { flow } = fake({ get: [NONE] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    const field = qa<HTMLInputElement>(m.container, "input").find(
      (i) => i.type === "password",
    ) as HTMLInputElement;
    expect(field.getAttribute("autocomplete")).toBe("off");
    expect(m.container.querySelector("form")?.getAttribute("autocomplete")).toBe("off");
    expect(text(m.container)).toContain("will be sent to the provider you name");
    type(field, KEY);
    expect(button(m.container, "Save key").disabled).toBe(true); // no consent, no bundle, no limit yet
    expect(countPrimary(m.container)).toBe(0);
  });

  it("BYOK_WEB_ADR_0041_save_sends_one_put_then_rereads_and_the_key_is_nowhere_afterwards", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const spies = (["log", "info", "warn", "error", "debug"] as const).map((k) =>
      vi.spyOn(console, k),
    );
    const { flow, calls } = fake({
      get: [NONE, ACTIVE],
      put: [{ state: "active", secret_version: 3, validated: true }],
    });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    fillAndAgree(m.container);
    click(button(m.container, "Save key"));
    expect(text(m.container)).not.toContain("saved"); // nothing is "saved" before the live answer
    await settle();
    await settle();
    expect(calls.map((c) => c.method)).toEqual(["GET", "PUT", "GET"]); // answer, then the re-read
    expect(calls[1]?.body).toEqual({
      confirm: true,
      consent_version: 1,
      bundle_id: "ex",
      day_cap_credits: 500,
      fallback_to_tilo: false,
      key: KEY,
    });
    expect(JSON.stringify(calls.filter((c) => c.method !== "PUT"))).not.toContain(KEY);
    expect(calls.every((c) => c.path === "/v1/org/model-key")).toBe(true); // no query, no key in a URL
    expect(text(m.container)).toContain("Key saved and confirmed");
    expect(text(m.container)).toContain("Active");
    expect(m.container.innerHTML).not.toContain(KEY);
    expect(qa<HTMLInputElement>(m.container, "input").every((i) => !i.value.includes(KEY))).toBe(
      true,
    );
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
    expect(spies.every((s) => s.mock.calls.length === 0)).toBe(true);
  });

  it("BYOK_WEB_ADR_0041_a_refused_key_clears_the_field_and_no_message_echoes_it", async () => {
    const cases: [number, string, string][] = [
      [422, "key_refused", "was refused"],
      [422, "confirm_required", "consent wording has changed"],
      [422, "invalid_body", "was not accepted"],
      [429, "rate_limited", "Too many key changes"],
      [401, "reauth_required", "sign-in from the last 10 minutes"],
      [403, "owner_only", "Only this organisation's owner"],
      [503, "unavailable", "could not confirm"],
    ];
    for (const [status, word, expected] of cases) {
      const { flow, calls } = fake({ get: [NONE], put: [refuse(status, word, status >= 500)] });
      const m = mount(<ModelKeyControl flow={flow} demo={false} />);
      await settle();
      fillAndAgree(m.container);
      click(button(m.container, "Save key"));
      await settle();
      await settle();
      expect(text(m.container), word).toContain(expected);
      expect(text(m.container)).not.toMatch(/Key saved/);
      expect(m.container.innerHTML).not.toContain(KEY);
      expect(qa<HTMLInputElement>(m.container, "input").every((i) => i.value !== KEY)).toBe(true);
      expect(calls.filter((c) => c.method === "PUT")).toHaveLength(1);
      expect(calls.filter((c) => c.method === "GET")).toHaveLength(1); // a refused write does not re-read
      cleanup();
    }
  });

  it("BYOK_WEB_ADR_0041_a_write_the_reread_cannot_confirm_is_not_called_saved", async () => {
    const { flow } = fake({
      get: [NONE, refuse(503, "unavailable", true)],
      put: [{ state: "active", secret_version: 1, validated: true }],
    });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    fillAndAgree(m.container);
    click(button(m.container, "Save key"));
    await settle();
    await settle();
    expect(text(m.container)).toContain("could not read the change back");
    expect(text(m.container)).not.toContain("Key saved");
  });
});

describe("ADR-0041 BQ-BYOK-WEB-1 source", () => {
  it("BYOK_WEB_ADR_0041_no_storage_console_url_or_timer_in_the_key_code", () => {
    const here = import.meta.dirname;
    const files = ["ModelKey.tsx", "../../../api/modelKey.ts", "../../../api/modelKeyEnv.ts"];
    for (const f of files) {
      const src = readFileSync(path.join(here, f), "utf8").replace(/\/\/.*$/gm, "");
      expect(src, f).not.toMatch(
        /\b(localStorage|sessionStorage|indexedDB|console\.|location\.|history\.|setTimeout|document\.cookie|URLSearchParams)\b/,
      );
    }
  });
});

describe("ADR-0041 BQ-BYOK-WEB-1 remove", () => {
  it("BYOK_WEB_ADR_0041_remove_asks_first_and_only_a_confirmed_removal_is_shown_as_removed", async () => {
    const { flow, calls } = fake({ get: [ACTIVE, NONE], del: [{ removed: true }] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    expect(text(m.container)).toContain("Active");
    expect(text(m.container)).toContain("version 3");
    click(button(m.container, "Remove key"));
    await settle();
    expect(q(m.container, '[role="alertdialog"]').textContent).toContain(
      "Revoke the key at the provider",
    );
    click(button(m.container, "Cancel"));
    await settle();
    expect(calls.map((c) => c.method)).toEqual(["GET"]); // Cancel sends nothing
    click(button(m.container, "Remove key"));
    click(button(m.container, "Remove the key"));
    await settle();
    await settle();
    expect(calls.map((c) => c.method)).toEqual(["GET", "DELETE", "GET"]);
    expect(text(m.container)).toContain("Key removed");
    expect(text(m.container)).toContain("No key is set");
    expect(button(m.container, "Remove key")).toBeUndefined(); // nothing left to remove
  });

  it("BYOK_WEB_ADR_0041_a_failed_remove_keeps_the_key_on_screen_and_says_so", async () => {
    const { flow } = fake({ get: [ACTIVE], del: [refuse(503, "unavailable", true)] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    click(button(m.container, "Remove key"));
    click(button(m.container, "Remove the key"));
    await settle();
    await settle();
    expect(text(m.container)).toContain("could not confirm");
    expect(text(m.container)).toContain("Active");
    expect(text(m.container)).not.toContain("Key removed");
  });
});
