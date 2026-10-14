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
// biome-ignore format: compact settle helper
const settle = (ms = PRESS_MS + 25) => act(async () => void (await new Promise((r) => setTimeout(r, ms))));

// biome-ignore format: compact input helper
function setFieldValue(el: HTMLInputElement | HTMLSelectElement, value: string): void {
  const proto = el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value")?.set?.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

// biome-ignore format: compact test setup
async function openUnderstanding(overrides: Partial<IntakeResult> = {}) {
  const answerQuestions = vi.fn(async () => ({ brief: BRIEF_SUPPLIER_COMPARISON }));
  const intake: IntakeResult = {
    task_id: "t1", brief: BRIEF_SUPPLIER_COMPARISON, questions: FIXTURE_QUESTIONS,
    files: [{ name: "quote_a.pdf", status: "ok", safety_flagged: false, reason: null }], ...overrides,
  };
  const client: TiloClient = Object.assign(new FixtureClient(), { submitIntake: async () => intake, answerQuestions });
  window.history.pushState({}, "", "/");
  await act(async () => {
    root.render(<ClientProvider client={client}><FlowShell /></ClientProvider>);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  // S-01 starts only with text in the task box; its result is handed to S-02 (rememberIntake).
  const box = q<HTMLTextAreaElement>("textarea");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set?.call(box, "Compare the two supplier quotes");
    box?.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => q("button.primary")?.click());
  await settle();
  return { answerQuestions };
}

// biome-ignore format: compact hooks
beforeEach(() => { container = document.createElement("div"); document.body.append(container); root = createRoot(container); });
// biome-ignore format: compact hooks
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks(); });

// biome-ignore format: compact suite
describe("AGW-03 S-02 Understanding", () => {
  it("FR_INT_04 FR_INT_06 deliverable multi-select sends option labels and supports deselection", async () => {
    const choices = ["Director's suggested output", "Study plan", "Notes", "Question bank", "Report", "Quiz"];
    const { answerQuestions } = await openUnderstanding({ questions: [{ field: "deliverables", text: "What should Tilo produce?", suggested_answers: choices }] });
    const buttons = qa(".suggestion-btn") as HTMLButtonElement[];
    expect(buttons.map(b => b.textContent)).toEqual(choices);
    const study = buttons[1];
    const notes = buttons[2];
    const quiz = buttons[5];
    if (!study || !notes || !quiz) throw new Error("Deliverable choices missing");
    await act(async () => study.click());
    await act(async () => notes.click());
    expect(study.getAttribute("aria-pressed")).toBe("true");
    expect(notes.getAttribute("aria-pressed")).toBe("true");
    await act(async () => quiz.click());
    await act(async () => quiz.click());
    expect(quiz.getAttribute("aria-pressed")).toBe("false");
    await act(async () => q("button.primary")?.click());
    await settle();
    expect(answerQuestions).toHaveBeenCalledWith("t1", [{ field: "deliverables", answer: "Study plan; Notes" }], {});
  });
  it("HR-honesty S-02: direct URL for an unremembered task shows the empty notice and never invents a brief or quote_a.pdf", async () => {
    window.history.pushState({}, "", "/task/task_unknown_99/understanding");
    await act(async () => {
      root.render(<ClientProvider client={new FixtureClient()}><FlowShell /></ClientProvider>);
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(q('[role="alert"]')?.textContent).toContain("Tilo has no brief for this task in this session");
    expect(q('[role="alert"] a')?.getAttribute("href")).toBe("/"); // its own next step, not a retry that cannot change anything
    expect(q('[role="alert"] button')).toBeNull();
    expect(q('[data-testid="brief-chips"]')).toBeNull();
    expect(container.textContent).not.toContain("quote_a.pdf");
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
  });

  it("FR-INT-04 S-02: shows the questions in the given order and never more than 3", async () => {
    await openUnderstanding({
      questions: [
        { field: "goal", text: "First question?", suggested_answers: ["A1"] },
        { field: "audience", text: "Second question?", suggested_answers: ["A2"] },
        { field: "deadline", text: "Third question?", suggested_answers: ["A3"] },
        { field: "constraints", text: "Fourth question?", suggested_answers: ["A4"] },
      ],
    });
    expect(qa('[data-testid="question-item"] legend').map((el) => el.textContent)).toEqual(["First question?", "Second question?", "Third question?"]);
  });

  it('FR-INT-04 S-02: skipping shows "Assumed: <first suggestion>" and sends answer null', async () => {
    const { answerQuestions } = await openUnderstanding();
    await act(async () => q('[data-testid="skip-question-0"]')?.click());
    expect(q('[data-testid="assumed-note"]')?.textContent).toBe("Assumed: Shipping is included in each total");
    await act(async () => q("button.primary")?.click());
    await settle();
    expect(answerQuestions).toHaveBeenCalledWith("t1", [{ field: "assumptions", answer: null }], {});
    expect(window.location.pathname).toBe("/task/t1/approaches");
  });

  it("FR-INT-03 S-02: every brief field has an editable chip, preserves source kinds, uses a select for sensitivity, and flags invalid edits", async () => {
    const { answerQuestions } = await openUnderstanding();
    for (const f of BRIEF_FIELDS) {
      expect(q(`[data-testid="brief-chip-${f}"] input, [data-testid="brief-chip-${f}"] select`), `missing ${f}`).not.toBeNull();
    }
    const sens = q<HTMLSelectElement>('[data-testid="brief-chip-sensitivity"] select');
    expect([...(sens?.options ?? [])].map((o) => o.value)).toEqual(["personal", "business", "public"]);
    const deliv = q<HTMLInputElement>('[data-testid="brief-chip-deliverables"] input');
    await act(async () => void (deliv && setFieldValue(deliv, "")));
    expect(deliv?.getAttribute("aria-invalid")).toBe("true");
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    await act(async () => void (deliv && setFieldValue(deliv, "Final memo (docx)")));
    expect(deliv?.getAttribute("aria-invalid")).toBeNull();
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(false);
    const sources = q<HTMLInputElement>('[data-testid="brief-chip-sources"] input');
    await act(async () => void (sources && setFieldValue(sources, "Quote B, Inbox threads, battery review")));
    await act(async () => void (sens && setFieldValue(sens, "personal")));
    const audience = q<HTMLInputElement>('[data-testid="brief-chip-audience"] input');
    await act(async () => void (audience && setFieldValue(audience, "Executive board")));
    await act(async () => q('[data-testid="question-item"] button.suggestion-btn')?.click());
    await act(async () => q("button.primary")?.click());
    await settle();
    expect(answerQuestions).toHaveBeenCalledWith("t1", [{ field: "assumptions", answer: "Shipping is included in each total" }], {
      audience: "Executive board", deliverables: [{ title: "Final memo", format: "docx" }], sensitivity: "personal",
      sources: [
        { kind: "file", ref: "art_quote_a", label: "Quote B" },
        { kind: "connector", ref: "gmail", label: "Inbox threads" },
        { kind: "web", ref: "battery review" },
      ],
    });
  });

  it("FR-INT-03 S-02: constraint and source chips enforce the schema's length limits and say why Continue is off", async () => {
    await openUnderstanding();
    expect(q('[data-testid="continue-reason"]')).toBeNull();
    const cons = q<HTMLInputElement>('[data-testid="brief-chip-constraints"] input');
    await act(async () => void (cons && setFieldValue(cons, "x".repeat(301))));
    expect(cons?.getAttribute("aria-invalid")).toBe("true");
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    expect(q('[data-testid="continue-reason"]')?.textContent).toContain("Constraints: up to 20, each under 300 characters");
    await act(async () => void (cons && setFieldValue(cons, "x".repeat(300))));
    expect(cons?.getAttribute("aria-invalid")).toBeNull();
    expect(q('[data-testid="continue-reason"]')).toBeNull();
    const sources = q<HTMLInputElement>('[data-testid="brief-chip-sources"] input');
    await act(async () => void (sources && setFieldValue(sources, `Quote A, ${"y".repeat(121)}`)));
    expect(sources?.getAttribute("aria-invalid")).toBe("true");
    expect(q<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    expect(q('[data-testid="continue-reason"]')?.textContent).toContain("Sources:");
  });

  it("FR-INT-01 S-02: each file shows its status; a failed or flagged file shows the API's reason", async () => {
    await openUnderstanding({
      files: [
        { name: "quote_a.pdf", status: "ok", safety_flagged: false, reason: null },
        { name: "broken.xlsx", status: "failed", safety_flagged: false, reason: "Corrupt archive" },
        { name: "bad.docx", status: "ok", safety_flagged: true, reason: "Hidden instruction" },
      ],
    });
    expect(qa('[data-testid="intake-file"]').map((el) => el.textContent?.trim())).toEqual([
      "quote_a.pdf: ok", "broken.xlsx: Couldn't read: Corrupt archive", "bad.docx: Flagged: Hidden instruction",
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
