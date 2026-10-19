// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import type { RunEvent } from "../../park/pages/World/useRunEvents";
import { ResultTab } from "./ResultTab";

afterEach(cleanup);

const delivered = (seq: number, id: string, label: string): RunEvent => ({
  seq,
  type: "artifact.delivered",
  ts: `2026-10-18T10:0${seq}:00.000Z`,
  credits: 0,
  summary: `${label} is ready.`,
  data: { artifact: { artifact_id: id, label }, format: "md" },
});

const press = (root: HTMLElement, label: string) => {
  const found = [...root.querySelectorAll("button")].find((button) => button.textContent === label);
  if (!found) throw new Error(`${label} button missing`);
  click(found);
};

describe("R-RESULT result delivery", () => {
  it("P0_AGENT_CHAT_offers_a_grounded_question_and_a_real_change_direction_run", async () => {
    const ask = vi.fn();
    const change = vi.fn(async () => undefined);
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_result"
          events={[delivered(1, "art_main", "Decision brief.md")]}
          onAskQuestion={ask}
          onChangeDirection={change}
        />
      </div>,
    );

    press(m.container, "Ask a question");
    expect(ask).toHaveBeenCalledOnce();
    press(m.container, "Change direction");
    const box = m.container.querySelector<HTMLTextAreaElement>(
      '[aria-label="What should the team change?"]',
    );
    expect(box).not.toBeNull();
    act(() => {
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      set?.call(box, "Keep the research and compare the safest option.");
      box?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    press(m.container, "Start new run");
    await act(async () => Promise.resolve());
    expect(change).toHaveBeenCalledWith("Keep the research and compare the safest option.");
  });

  it("R-RESULT shows one real main card, unique named working files, and readable maths", async () => {
    const events = [
      delivered(1, "art_main", "Decision brief.md"),
      delivered(2, "art_notes", "Research notes.md"),
      delivered(3, "art_notes_copy", "Research notes.md"),
    ];
    const blob = new Blob(["# Decision brief\nMove $\\to$ option B when score is $< 13$."], {
      type: "text/markdown",
    });
    const m = mount(
      <div data-park="">
        <ResultTab
          worldId="w_result"
          events={events}
          shared={{
            view: {
              status: "text",
              blob,
              text: "# Decision brief\nMove $\\to$ option B when score is $< 13$.",
              kind: "markdown",
              cut: false,
            },
            retry: () => undefined,
          }}
        />
      </div>,
    );
    await act(async () => Promise.resolve());

    expect(m.container.querySelectorAll('[data-testid="run-result"]')).toHaveLength(1);
    expect(m.container.textContent).not.toContain("Delivered file");
    expect(m.container.textContent).not.toContain("Kickoff deck");
    expect(m.container.textContent).not.toContain("$\\to$");
    expect(m.container.textContent).not.toContain("$< 13$");
    expect(m.container.textContent).toContain("Move → option B when score is < 13.");
    const files = m.container.querySelector('[data-testid="working-files"]');
    expect(files?.querySelectorAll("li")).toHaveLength(1);
    expect(files?.textContent).toContain("Research notes.md");
    expect(files?.querySelectorAll('button[aria-label^="Open "]')).toHaveLength(1);
    expect(files?.querySelectorAll('button[aria-label^="Download "]')).toHaveLength(1);
  });
});
