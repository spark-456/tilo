// @vitest-environment happy-dom
// SEC-15 (docs/prd-supplement-2026-10-05.md section 4), web half: "sign-up asks 'visitor or Google AI Builder
// Cup judge?'. Visitors see 'still under construction, not open to the public' and get no access."
// Component tests only (no E2E). The server is the enforcement (services/api/tests/API_SEC_15.md); these pin what
// the person sees. Pinned interface, all under apps/web/src/access/:
//   SignUpDeclaration.tsx  export function SignUpDeclaration(props: { onSubmit(d: "visitor" | "judge"): void | Promise<void>; busy?: boolean })
//   UnderConstruction.tsx  export function UnderConstruction()
//   AccessGate.tsx         export function AccessGate(props: { error?: unknown; onDeclare(d: "visitor" | "judge"): void | Promise<void>; children: ReactNode })
// AccessGate shows UnderConstruction for a TiloApiError with code "under_construction", SignUpDeclaration for
// code "declaration_required", and its children otherwise (no error, or any other error).
import { act } from "react";
import type { ReactNode } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HttpClient, type TiloApiError } from "../api/http";
import { AccessGate } from "./AccessGate";
import { SignUpDeclaration } from "./SignUpDeclaration";
import { UnderConstruction } from "./UnderConstruction";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
const q = <T extends Element>(sel: string) => container.querySelector<T>(sel);
const text = () => (container.textContent ?? "").replace(/\s+/g, " ").toLowerCase();

async function show(node: ReactNode) {
  await act(async () => {
    root.render(node);
  });
}

function labelOf(input: HTMLInputElement): string {
  const wrapping = input.closest("label")?.textContent;
  const forId = input.id
    ? container.querySelector(`label[for="${input.id}"]`)?.textContent
    : undefined;
  return `${wrapping ?? ""} ${forId ?? ""} ${input.getAttribute("aria-label") ?? ""}`.toLowerCase();
}

/** A real TiloApiError, made by the real client from a server answer. */
async function refusal(status: number, body: unknown): Promise<TiloApiError> {
  const client = new HttpClient({
    baseUrl: "http://api.test",
    fetch: (async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      })) as typeof fetch,
  });
  try {
    await client.submitIntake("x", []);
  } catch (error) {
    return error as TiloApiError;
  }
  throw new Error("the call should have failed");
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("SEC-15 sign-up asks 'visitor or Google AI Builder Cup judge?'", () => {
  it("SEC-15 the question names both answers and offers exactly two radio choices, none preselected", async () => {
    await show(<SignUpDeclaration onSubmit={() => {}} />);

    expect(text()).toContain("visitor");
    expect(text()).toContain("google ai builder cup judge");
    const radios = [...container.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
    expect(radios.map((r) => r.value).sort()).toEqual(["judge", "visitor"]);
    expect(radios.every((r) => !r.checked)).toBe(true); // an explicit choice, never a default
    for (const radio of radios) {
      expect(labelOf(radio)).toContain(radio.value === "judge" ? "judge" : "visitor");
    }
  });

  it("SEC-15 Tilo never handles passwords: the sign-up step has no password or secret field", async () => {
    await show(<SignUpDeclaration onSubmit={() => {}} />);

    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(container.querySelectorAll("input:not([type='radio'])").length).toBe(0);
    expect(container.querySelector("textarea")).toBeNull();
  });

  it("SEC-15 one primary button (UX-1); nothing is submitted until a choice is made", async () => {
    const onSubmit = vi.fn();
    await show(<SignUpDeclaration onSubmit={onSubmit} />);

    const primaries = container.querySelectorAll<HTMLButtonElement>("button.primary");
    expect(primaries.length).toBe(1);
    await act(async () => primaries[0]?.click());
    expect(onSubmit).not.toHaveBeenCalled();
    const disabled =
      primaries[0]?.disabled || primaries[0]?.getAttribute("aria-disabled") === "true";
    expect(disabled).toBe(true);
  });

  it.each(["judge", "visitor"] as const)(
    "SEC-15 choosing %s and continuing submits exactly that once",
    async (choice) => {
      const onSubmit = vi.fn();
      await show(<SignUpDeclaration onSubmit={onSubmit} />);

      const radio = q<HTMLInputElement>(`input[type="radio"][value="${choice}"]`);
      await act(async () => radio?.click());
      expect(radio?.checked).toBe(true);
      await act(async () => q<HTMLButtonElement>("button.primary")?.click());

      expect(onSubmit).toHaveBeenCalledTimes(1);
      expect(onSubmit).toHaveBeenCalledWith(choice);
    },
  );
});

describe("SEC-15 a visitor sees 'still under construction, not open to the public'", () => {
  it("SEC-15 UnderConstruction says so in plain words and offers no way into the product", async () => {
    await show(<UnderConstruction />);

    expect(text()).toContain("still under construction");
    expect(text()).toContain("not open to the public");
    expect(container.querySelector("textarea, input, button.primary")).toBeNull(); // no Start form, no upload
    expect(container.querySelector("h1, h2, [role='heading']")).not.toBeNull();
  });

  it("SEC-15 a visitor's 403 from the API renders UnderConstruction and never the page behind it", async () => {
    const error = await refusal(403, {
      detail: "Tilo is still under construction and not open to the public.",
      code: "under_construction",
    });

    await show(
      <AccessGate error={error} onDeclare={() => {}}>
        <p data-testid="behind-the-gate">the product</p>
      </AccessGate>,
    );

    expect(text()).toContain("still under construction");
    expect(text()).toContain("not open to the public");
    expect(q('[data-testid="behind-the-gate"]')).toBeNull();
  });

  it("SEC-15 a 403 saying no declaration yet asks the sign-up question and sends the answer on", async () => {
    const error = await refusal(403, { detail: "Say who you are.", code: "declaration_required" });
    const onDeclare = vi.fn();

    await show(
      <AccessGate error={error} onDeclare={onDeclare}>
        <p data-testid="behind-the-gate">the product</p>
      </AccessGate>,
    );

    expect(text()).toContain("google ai builder cup judge");
    expect(q('[data-testid="behind-the-gate"]')).toBeNull();
    await act(async () => q<HTMLInputElement>('input[type="radio"][value="judge"]')?.click());
    await act(async () => q<HTMLButtonElement>("button.primary")?.click());
    expect(onDeclare).toHaveBeenCalledWith("judge");
  });

  it("SEC-15 no error, or an unrelated error, leaves the product visible", async () => {
    const otherRefusal = await refusal(403, { detail: "You are not the owner." });
    for (const error of [undefined, null, otherRefusal, new Error("offline")]) {
      await show(
        <AccessGate error={error} onDeclare={() => {}}>
          <p data-testid="behind-the-gate">the product</p>
        </AccessGate>,
      );
      expect(q('[data-testid="behind-the-gate"]')).not.toBeNull();
      expect(text()).not.toContain("under construction");
    }
  });
});
