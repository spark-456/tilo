// @vitest-environment happy-dom
// LW-14 acceptance tests for the AppSpec quiz player at /world/:id/app/:artifactId (ADR-0029 decision 9,
// contracts/appspec.schema.json, contracts/appspec.rules.md AS-01..AS-04):
// - score is computed correctly, per-question review is shown, and attempts are stored in localStorage (try/catch)
// - countdown timer supports pause/resume and submits automatically when reaching 0
// - topic filter narrows the question set to one topic tag at a time
// - keyboard navigation: arrow keys move between options and Enter confirms
// - every spec string (title, stem, options, source publisher) is rendered as plain text, never innerHTML
// - a malformed spec (schema violation or duplicate question id AS-01) shows an honest error screen
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { ParkApp } from "../../app/ParkApp";
import {
  QUIZ_FIXTURE_PUBLISHERS,
  QUIZ_FIXTURE_SPEC,
  readQuizAttempts,
  scoreQuizAttempt,
  validateAppSpec,
} from "../../app/appspec.draft";
import { ParkProvider } from "../../app/context";
import { QuizPlayerPage } from "./QuizPlayerPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  try {
    window.localStorage.clear();
  } catch {
    // ignore storage errors in cleanup
  }
  window.history.pushState({}, "", "/");
});

function must<T>(val: T | null | undefined, label = "element"): T {
  if (val === null || val === undefined) throw new Error(`missing ${label}`);
  return val;
}

function pressKey(target: Element, key: string): boolean {
  let prevented = false;
  act(() => {
    const ev = new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
    });
    target.dispatchEvent(ev);
    prevented = ev.defaultPrevented;
  });
  return prevented;
}

function setSelectValue(el: HTMLSelectElement, value: string): void {
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
    set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

describe("LW_14 Quiz player for AppSpec", () => {
  it("test_LW_14_score_is_computed_correctly_and_attempt_saved_to_localStorage", async () => {
    expect(QUIZ_FIXTURE_SPEC.questions).toHaveLength(10);

    const firstThreeCorrect = {
      q1: QUIZ_FIXTURE_SPEC.questions[0]?.answer ?? "a",
      q2: QUIZ_FIXTURE_SPEC.questions[1]?.answer ?? "a",
      q3: QUIZ_FIXTURE_SPEC.questions[2]?.answer ?? "a",
      q4: QUIZ_FIXTURE_SPEC.questions[3]?.answer === "a" ? ("b" as const) : ("a" as const),
    };
    const score = scoreQuizAttempt(QUIZ_FIXTURE_SPEC.questions, firstThreeCorrect);
    expect(score.total).toBe(10);
    expect(score.correct).toBe(3);
    expect(score.unanswered).toBe(6);

    // Mount via the owner-only route /world/:id/app/:artifactId inside ParkApp
    window.history.pushState({}, "", "/world/w_gate_prep/app/art_quiz_1");
    const m = mount(<ParkApp />);
    await act(async () => {
      await vi.dynamicImportSettled();
    });
    await act(async () => undefined);

    const root = q(m.container, '[data-testid="park-page-quiz"]');
    expect(root.textContent ?? "").toContain(QUIZ_FIXTURE_SPEC.title);
    expect(q(root, '[data-testid="quiz-source"]').textContent ?? "").toMatch(/^from\s+\S+/);

    // Answer Q1 correctly, move to Q2 and answer Q2 wrongly, then submit
    const q1Correct = QUIZ_FIXTURE_SPEC.questions[0].answer;
    click(q(root, `[data-option-id="${q1Correct}"]`));
    click(q(root, '[data-testid="quiz-next"]'));

    const q2Wrong = QUIZ_FIXTURE_SPEC.questions[1]?.answer === "a" ? "b" : "a";
    click(q(root, `[data-option-id="${q2Wrong}"]`));
    click(q(root, '[data-testid="quiz-submit"]'));

    const summary = q(root, '[data-testid="quiz-score-summary"]');
    expect(summary.textContent ?? "").toContain("1 / 10");

    const reviewRows = qa(root, '[data-testid="quiz-review-item"]');
    expect(reviewRows).toHaveLength(10);
    expect(reviewRows[0]?.textContent ?? "").toContain("Correct");
    expect(reviewRows[1]?.textContent ?? "").toContain("Incorrect");
    expect(reviewRows[2]?.textContent ?? "").toContain("Unanswered");

    const saved = readQuizAttempts("w_gate_prep", "art_quiz_1");
    expect(saved).toHaveLength(1);
    expect(saved[0]?.correct).toBe(1);
    expect(saved[0]?.total).toBe(10);
  });

  it("test_LW_14_timer_reaching_zero_submits_automatically_and_pause_resume_holds_clock", () => {
    vi.useFakeTimers();
    const shortSpec = {
      ...QUIZ_FIXTURE_SPEC,
      timer: { seconds: 60 },
    };

    const m = mount(
      <ParkProvider>
        <QuizPlayerPage
          worldId="w_gate_prep"
          artifactId="art_timer_test"
          spec={shortSpec}
          publishers={QUIZ_FIXTURE_PUBLISHERS}
        />
      </ParkProvider>,
    );

    const root = q(m.container, '[data-testid="park-page-quiz"]');
    expect(q(root, '[data-testid="quiz-timer"]').textContent).toContain("01:00");

    // Select an answer on Q1
    click(q(root, `[data-option-id="${shortSpec.questions[0].answer}"]`));

    // Advance 20 seconds -> 00:40
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(q(root, '[data-testid="quiz-timer"]').textContent).toContain("00:40");

    // Pause the timer and advance 30 seconds -> still 00:40
    const pauseBtn = q(root, '[data-testid="quiz-timer-toggle"]');
    click(pauseBtn);
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(q(root, '[data-testid="quiz-timer"]').textContent).toContain("00:40");

    // Resume and advance the remaining 40 seconds -> reaches 00:00 and auto-submits
    click(pauseBtn);
    act(() => {
      vi.advanceTimersByTime(40_000);
    });

    const summary = q(root, '[data-testid="quiz-score-summary"]');
    expect(summary.textContent ?? "").toContain("1 / 10");
    expect(root.textContent ?? "").toMatch(/time.+up|00:00/i);
  });

  it("test_LW_14_topic_filter_narrows_questions_and_keyboard_arrows_and_enter_work", () => {
    const m = mount(
      <ParkProvider>
        <QuizPlayerPage
          worldId="w_gate_prep"
          artifactId="art_topic_test"
          spec={QUIZ_FIXTURE_SPEC}
          publishers={QUIZ_FIXTURE_PUBLISHERS}
        />
      </ParkProvider>,
    );

    const root = q(m.container, '[data-testid="park-page-quiz"]');
    const topicSelect = q<HTMLSelectElement>(root, 'select[aria-label="Filter by topic"]');
    const topicOptions = qa<HTMLOptionElement>(topicSelect, "option").map((o) => o.value);
    expect(topicOptions).toContain("all");
    expect(topicOptions).toContain("digital_logic");

    const digitalLogicQuestions = QUIZ_FIXTURE_SPEC.questions.filter(
      (qItem) => qItem.topic === "digital_logic",
    );
    expect(digitalLogicQuestions.length).toBeGreaterThanOrEqual(2);

    setSelectValue(topicSelect, "digital_logic");
    expect(q(root, '[data-testid="quiz-progress"]').textContent).toContain(
      `Question 1 of ${digitalLogicQuestions.length}`,
    );
    expect(q(root, '[data-testid="quiz-stem"]').textContent).toBe(digitalLogicQuestions[0]?.stem);

    // Keyboard navigation: ArrowDown moves from option a to option b, Enter confirms and advances
    const optA = q<HTMLButtonElement>(root, '[data-option-id="a"]');
    optA.focus();
    click(optA);
    expect(optA.getAttribute("aria-pressed")).toBe("true");

    pressKey(optA, "ArrowDown");
    const optB = q<HTMLButtonElement>(root, '[data-option-id="b"]');
    expect(optB.getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(optB);

    pressKey(optB, "Enter");
    expect(q(root, '[data-testid="quiz-progress"]').textContent).toContain(
      `Question 2 of ${digitalLogicQuestions.length}`,
    );
  });

  it("test_LW_14_spec_text_is_rendered_as_plain_text_never_innerHTML", () => {
    const xssSpec = {
      ...QUIZ_FIXTURE_SPEC,
      title: "<script>window.__quizTitleXss = 1</script><b>Gate Practice</b>",
      questions: [
        {
          id: "q1",
          stem: '<img src="x" onerror="window.__quizStemXss=1"><script>alert(1)</script>What is 2 + 2?',
          options: {
            a: "<script>window.__optA=1</script>3",
            b: "<a href='https://evil.example'>4</a>",
            c: "<b>5</b>",
            d: "<i>6</i>",
          },
          answer: "b" as const,
          topic: "digital_logic",
          source: {
            artifact: {
              artifact_id: "art_xss_doc",
              version: 1,
            },
            page: 1,
          },
        },
      ],
    };

    const m = mount(
      <ParkProvider>
        <QuizPlayerPage
          worldId="w_gate_prep"
          artifactId="art_xss_test"
          spec={xssSpec}
          publishers={{ art_xss_doc: "<script>window.__pubXss=1</script>gate.example.edu" }}
        />
      </ParkProvider>,
    );

    const root = q(m.container, '[data-testid="park-page-quiz"]');
    expect(root.querySelector("script")).toBeNull();
    expect(root.querySelector('img[src="x"]')).toBeNull();
    expect(root.querySelector('a[href="https://evil.example"]')).toBeNull();
    expect(root.textContent ?? "").toContain("<script>window.__quizTitleXss = 1</script>");
    expect(q(root, '[data-testid="quiz-stem"]').textContent ?? "").toContain(
      '<img src="x" onerror="window.__quizStemXss=1">',
    );
    expect(q(root, '[data-option-id="b"]').textContent ?? "").toContain(
      "<a href='https://evil.example'>4</a>",
    );
    expect(q(root, '[data-testid="quiz-source"]').textContent ?? "").toContain(
      "from <script>window.__pubXss=1</script>gate.example.edu",
    );
  });

  it("test_LW_14_malformed_spec_shows_honest_error_and_refuses_duplicate_question_ids", () => {
    // 1. Duplicate question id (AS-01)
    const dupSpec = {
      ...QUIZ_FIXTURE_SPEC,
      questions: [
        QUIZ_FIXTURE_SPEC.questions[0],
        { ...QUIZ_FIXTURE_SPEC.questions[1], id: QUIZ_FIXTURE_SPEC.questions[0].id },
      ],
    };
    expect(validateAppSpec(dupSpec).ok).toBe(false);

    // 2. Answer not in options
    const badAnswerSpec = {
      ...QUIZ_FIXTURE_SPEC,
      questions: [
        {
          ...QUIZ_FIXTURE_SPEC.questions[0],
          answer: "e",
        },
      ],
    };
    expect(validateAppSpec(badAnswerSpec).ok).toBe(false);

    // 3. Script field or URL in source (forbidden by appspec.schema.json)
    const scriptFieldSpec = {
      ...QUIZ_FIXTURE_SPEC,
      script: "alert(1)",
    };
    expect(validateAppSpec(scriptFieldSpec).ok).toBe(false);

    const m = mount(
      <ParkProvider>
        <QuizPlayerPage
          worldId="w_gate_prep"
          artifactId="art_malformed"
          spec={dupSpec}
          publishers={QUIZ_FIXTURE_PUBLISHERS}
        />
      </ParkProvider>,
    );

    const errBox = must(
      m.container.querySelector('[data-testid="quiz-error"] [role="alert"]'),
      "quiz-error alert",
    );
    expect(errBox.getAttribute("role")).toBe("alert");
    expect(errBox.textContent ?? "").toMatch(/invalid|duplicate|question/i);
    expect(m.container.querySelector('[data-testid="quiz-stem"]')).toBeNull();
  });
});
