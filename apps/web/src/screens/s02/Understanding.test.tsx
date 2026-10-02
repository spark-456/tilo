// @vitest-environment happy-dom
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../../api/ClientProvider";
import type { IntakeResult, TiloClient } from "../../api/client";
import { FixtureClient } from "../../api/fixtureClient";
import { BRIEF_SUPPLIER_COMPARISON } from "../../api/fixtures/brief";
import { FIXTURE_QUESTIONS } from "../../api/fixtures/derived";
import { FlowShell } from "../FlowShell";
import { PRESS_MS } from "../remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// biome-ignore format: compact field list
const BRIEF_FIELDS = ["goal", "deliverables", "audience", "deadline", "constraints", "sources", "sensitivity"] as const;

let container: HTMLElement;
let root: Root;
const q = <T extends Element = HTMLElement>(s: string) => container.querySelector<T>(s);
const qa = (s: string) => [...container.querySelectorAll(s)];
const settle = (ms = PRESS_MS + 25) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));

function setInputValue(input: HTMLInputElement, value: string): void {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

async function openUnderstanding(overrides: Partial<IntakeResult> = {}) {
  const answerQuestions = vi.fn(async () => ({ brief: BRIEF_SUPPLIER_COMPARISON }));
  const intake: IntakeResult = {
    task_id: "t1",
    brief: BRIEF_SUPPLIER_COMPARISON,
    files: [{ name: "quote_a.pdf", status: "ok", safety_flagged: false, reason: null }],
    questions: FIXTURE_QUESTIONS,
    ...overrides,
  };
  const client: TiloClient = Object.assign(new FixtureClient(), {
    submitIntake: async () => intake,
    answerQuestions,
  });
  window.history.pushState({}, "", "/");
  await act(async () => {
    root.render(
      <ClientProvider client={client}>
        <FlowShell />
      </ClientProvider>,
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await act(async () => q("button.primary")?.click());
  await settle();
  return { answerQuestions };
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

describe("AGW-03 S-02 Understanding", () => {
  it("FR-INT-04 S-02: shows the questions in the given order and never more than 3", async () => {
    await openUnderstanding({
      questions: [
        { field: "goal", text: "First question?", suggested_answers: ["A1"] },
        { field: "audience", text: "Second question?", suggested_answers: ["A2"] },
        { field: "deadline", text: "Third question?", suggested_answers: ["A3"] },
        { field: "constraints", text: "Fourth question?", suggested_answers: ["A4"] },
      ],
    });
    const legends = qa('[data-testid="question-item"] legend').map((el) => el.textContent);
    expect(legends).toEqual(["First question?", "Second question?", "Third question?"]);
  });

  it('FR-INT-04 S-02: skipping shows "Assumed: <first suggestion>" and sends answer null', async () => {
    const { answerQuestions } = await openUnderstanding();
    const skipBtn = q('[data-testid="skip-question-0"]');
    expect(skipBtn).not.toBeNull();
    await act(async () => skipBtn?.click());
    expect(q('[data-testid="assumed-note"]')?.textContent).toBe(
      "Assumed: Shipping is included in each total",
    );
    const primary = q("button.primary");
    expect(primary?.textContent).toBe("Continue");
    await act(async () => primary?.click());
    await settle();
    expect(answerQuestions).toHaveBeenCalledWith(
      "t1",
      [{ field: "assumptions", answer: null }],
      {},
    );
    expect(window.location.pathname).toBe("/task/t1/approaches");
  });

  it("FR-INT-03 S-02: every brief field has an editable chip, and an edit is sent with the answers", async () => {
    const { answerQuestions } = await openUnderstanding();
    for (const f of BRIEF_FIELDS) {
      expect(q(`[data-testid="brief-chip-${f}"] input`), `missing ${f}`).not.toBeNull();
    }
    const audience = q<HTMLInputElement>('[data-testid="brief-chip-audience"] input');
    await act(async () => void (audience && setInputValue(audience, "Executive board")));
    await act(async () => q('[data-testid="question-item"] button.suggestion-btn')?.click());
    await act(async () => q("button.primary")?.click());
    await settle();
    expect(answerQuestions).toHaveBeenCalledWith(
      "t1",
      [{ field: "assumptions", answer: "Shipping is included in each total" }],
      { audience: "Executive board" },
    );
  });

  it("FR-INT-01 S-02: each file shows its status; a failed or flagged file shows the API's reason", async () => {
    await openUnderstanding({
      files: [
        { name: "quote_a.pdf", status: "ok", safety_flagged: false, reason: null },
        { name: "broken.xlsx", status: "failed", safety_flagged: false, reason: "Corrupt archive" },
        { name: "bad.docx", status: "ok", safety_flagged: true, reason: "Hidden instruction" },
      ],
    });
    const rows = qa('[data-testid="intake-file"]').map((el) => el.textContent?.trim());
    expect(rows).toEqual([
      "quote_a.pdf: ok",
      "broken.xlsx: Couldn't read: Corrupt archive",
      "bad.docx: Flagged: Hidden instruction",
    ]);
  });

  it("FR-INT-05 S-02: an applied preference shows with its citation", async () => {
    await openUnderstanding();
    const pref = q('[data-testid="applied-preference"]')?.textContent;
    expect(pref).toContain("Using your preference: PDF output");
    expect(pref).toContain("mem_output_format");
  });

  it("FR-INT-04 S-02: 0 questions shows no question block", async () => {
    await openUnderstanding({ questions: [] });
    expect(q('[data-testid="brief-chips"]')).not.toBeNull();
    expect(q('[data-testid="questions-block"]')).toBeNull();
  });
});
