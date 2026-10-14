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
import { CONSENT_VERSION, ModelKeyControl } from "./ModelKey";

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
  it("R34_4_ADR_0041_refused_Vertex_IAM_is_not_offered_by_the_form", async () => {
    for (const answer of [NONE, refuse(503, "not_configured", true)]) {
      const { flow, calls } = fake({ get: [answer] });
      const m = mount(<ModelKeyControl flow={flow} demo={false} />);
      await settle();
      expect(text(m.container)).not.toMatch(/Vertex|project id/i);
      expect(qa<HTMLInputElement>(m.container, 'input[type="text"]')).toHaveLength(2);
      expect(calls).toEqual([{ method: "GET", path: "/v1/org/model-key" }]);
      cleanup();
    }
  });

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

  it("BYOK_WEB_ADR_0041_B7_a_vanished_bundle_is_shown_as_not_in_use_not_as_active", async () => {
    // SEC-REVIEW-29 B7: the API says state "active" but `active: false, last_error: "not_configured"` (the bundle left
    // config). The page must follow `active`, not claim "uses its own key" and show a green chip.
    const gone = { ...ACTIVE, active: false, last_error: "not_configured" };
    const a = fake({ get: [gone] });
    const m = mount(<ModelKeyControl flow={a.flow} demo={false} />);
    await settle();
    const shown = text(m.container);
    expect(shown).not.toContain("uses its own key");
    expect(shown).not.toMatch(/Active\./);
    expect(shown).toContain("Not in use");
    expect(shown).toContain("no longer configured");
    expect(m.container.querySelector(".park-chip--ok")).toBeNull();
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
  it("BYOK_WEB_ADR_0041_B5_the_key_field_is_a_masked_text_field_never_a_password_field", async () => {
    // SEC-REVIEW-29 B5, PRD 16.1 rule 1 (no password fields anywhere in Tilo): a password-typed field in a form is
    // what a browser's password manager offers to save, and `autocomplete="off"` is commonly ignored there.
    const { flow } = fake({ get: [NONE] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    expect(m.container.querySelector('input[type="password"]')).toBeNull();
    expect(m.container.querySelector('[autocomplete*="password"]')).toBeNull();
    const field = qa<HTMLInputElement>(m.container, "input").find((i) =>
      i.closest("label")?.textContent?.startsWith("API key"),
    ) as HTMLInputElement;
    expect(field.type).toBe("text");
    expect(field.getAttribute("autocomplete")).toBe("off");
    expect(field.getAttribute("autocapitalize")).toBe("off");
    expect(field.getAttribute("spellcheck")).toBe("false");
    expect(field.hasAttribute("data-1p-ignore")).toBe(true);
    expect(field.getAttribute("data-lpignore")).toBe("true");
    expect(field.getAttribute("data-bwignore")).toBe("true");
    expect(field.getAttribute("data-form-type")).toBe("other");
    expect(`${field.name} ${field.id}`.toLowerCase()).not.toMatch(/pass|pwd|secret/);
    expect(field.className).toContain("park-profile-secret"); // the CSS mask (Profile.css), asserted below
    expect(m.container.querySelector("form")?.getAttribute("autocomplete")).toBe("off");
    expect(text(m.container)).toContain("will be sent to the provider you name");
    type(field, KEY);
    expect(button(m.container, "Save key").disabled).toBe(true); // no consent, no bundle, no limit yet
    expect(countPrimary(m.container)).toBe(0);
  });

  it("BYOK_WEB_ADR_0041_B5_the_mask_is_in_the_stylesheet_and_the_field_is_cleared_after_submit", async () => {
    const css = readFileSync(path.join(import.meta.dirname, "Profile.css"), "utf8");
    const rule = /\[data-park\] \.park-profile-secret\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rule).toMatch(/-webkit-text-security:\s*disc/);
    const { flow } = fake({
      get: [NONE, ACTIVE],
      put: [{ state: "active", secret_version: 3, validated: true }],
    });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    fillAndAgree(m.container);
    const field = qa<HTMLInputElement>(m.container, "input").find((i) =>
      i.closest("label")?.textContent?.startsWith("API key"),
    ) as HTMLInputElement;
    expect(field.value).toBe(KEY);
    click(button(m.container, "Save key"));
    expect(field.value).toBe(""); // cleared at the click, before any answer
    await settle();
    await settle();
    expect(field.value).toBe("");
    expect(m.container.innerHTML).not.toContain(KEY);
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

describe("ADR-0041 BK-06 SEC-REVIEW-29 B6: the consent version is the page's, never the server's echo", () => {
  it("BYOK_WEB_ADR_0041_B6_the_page_sends_the_version_of_the_text_it_rendered", async () => {
    // The server's number is 0 (older than this page's text): an echo would send 0 and the server could never see a
    // stale page. The body must carry the page's own CONSENT_VERSION.
    const { flow, calls } = fake({
      get: [{ ...NONE, consent_version: 0 }, ACTIVE],
      put: [{ state: "active", secret_version: 1, validated: true }],
    });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    fillAndAgree(m.container);
    click(button(m.container, "Save key"));
    await settle();
    await settle();
    const put = calls.find((c) => c.method === "PUT");
    expect((put?.body as { consent_version?: number }).consent_version).toBe(CONSENT_VERSION);
    expect(CONSENT_VERSION).toBe(1);
  });

  it("BYOK_WEB_ADR_0041_B6_a_server_version_newer_than_the_page_text_says_reload_and_sends_nothing", async () => {
    const { flow, calls } = fake({ get: [{ ...NONE, consent_version: 2 }] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    expect(q(m.container, '[role="alert"]').textContent).toContain("Reload this page");
    expect(button(m.container, "Save key").disabled).toBe(true);
    fillAndAgree(m.container);
    expect(button(m.container, "Save key").disabled).toBe(true);
    click(button(m.container, "Save key"));
    await settle();
    expect(calls.map((c) => c.method)).toEqual(["GET"]); // nothing was sent
  });

  it("BYOK_WEB_ADR_0041_B6_an_older_confirmation_on_a_held_key_does_not_lock_a_rotation", async () => {
    // A number older than the page's text (an API that has not caught up) never locks the page.
    const { flow, calls } = fake({
      get: [{ ...ACTIVE, consent_version: 0 }, ACTIVE],
      put: [{ state: "active", secret_version: 4, validated: true }],
    });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    expect(m.container.querySelector('[role="alert"]')).toBeNull();
    fillAndAgree(m.container);
    click(button(m.container, "Save key"));
    await settle();
    await settle();
    expect(calls.map((c) => c.method)).toEqual(["GET", "PUT", "GET"]);
  });

  it("BYOK_6_a_held_key_whose_config_moved_to_a_newer_consent_version_says_reload_and_sends_nothing", async () => {
    // org_model_key.owner_view: `consent_version` is the config's current one, not the stored one, so a held key
    // shows the bump (the API used to echo the stored number, which went stale).
    const { flow, calls } = fake({ get: [{ ...ACTIVE, consent_version: CONSENT_VERSION + 1 }] });
    const m = mount(<ModelKeyControl flow={flow} demo={false} />);
    await settle();
    expect(q(m.container, '[role="alert"]').textContent).toContain("Reload this page");
    fillAndAgree(m.container);
    expect(button(m.container, "Save key").disabled).toBe(true);
    click(button(m.container, "Save key"));
    await settle();
    expect(calls.map((c) => c.method)).toEqual(["GET"]);
  });

  it("BYOK_WEB_ADR_0041_B6_the_version_constant_sits_next_to_the_consent_text", () => {
    const src = readFileSync(path.join(import.meta.dirname, "ModelKey.tsx"), "utf8");
    const at = (needle: string) => src.indexOf(needle);
    expect(at("export const CONSENT_VERSION")).toBeGreaterThan(-1);
    expect(
      Math.abs(at("export const CONSENT_VERSION") - at("const CONSENT =")),
      "adjacent",
    ).toBeLessThan(400);
    expect(src).not.toMatch(/consentVersion:\s*view\.consentVersion/);
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
