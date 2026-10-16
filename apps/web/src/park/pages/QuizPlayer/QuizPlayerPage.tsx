// LW-14 AppSpec Quiz Player at route /world/:id/app/:artifactId (ADR-0029 decision 9, AS-01..AS-04).
// Renders a declarative quiz AppSpec using fixed web code only: every spec string is shown as plain text, never
// HTML or Markdown. Countdown timer uses the Park provider's useSchedule() and auto-submits at 0. Attempts are
// saved in localStorage (try/catch) in phase 1.
import {
  type ChangeEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { type QuizView, readQuizApp } from "../../api/quizApps";
import type { AppCtx } from "../../app/AppCtx";
import {
  type AppSpecOptionId,
  QUIZ_FIXTURE_PUBLISHERS,
  QUIZ_FIXTURE_SPEC,
  filterQuestionsByTopic,
  formatPublisherLine,
  formatTimerMmSs,
  listTopics,
  optionEntries,
  readQuizAttempts,
  saveQuizAttempt,
  scoreQuizAttempt,
  validateAppSpec,
} from "../../app/appspec.draft";
import { useApp, useExpectsSample, useParkApi, useSchedule } from "../../app/context";
import { Button, PageSheet } from "../../components";
import { EmptyState, ErrorState } from "../../../design/tilo-t";
import "./QuizPlayer.css";

export interface QuizPlayerPageProps {
  readonly app?: AppCtx | undefined;
  readonly worldId?: string | undefined;
  readonly artifactId?: string | undefined;
  readonly spec?: unknown;
  readonly publishers?: Readonly<Record<string, string>> | undefined;
}

export function QuizPlayerPage({
  app: appProp,
  worldId: worldIdProp,
  artifactId: artifactIdProp,
  spec: rawSpecProp,
  publishers: publishersProp,
}: QuizPlayerPageProps) {
  const ctxApp = useApp();
  const app = appProp ?? ctxApp;
  const schedule = useSchedule();
  const worldId = worldIdProp ?? app.params.id ?? "world";
  const artifactId = artifactIdProp ?? app.params.artifactId ?? "quiz";

  // The fictional sample quiz is shown only where the shell shows its Sample chip (the fixture Api). Under a live
  // Api the page reads only the owner route; an unavailable spec stays unavailable (HR-1..HR-7).
  const sample = useExpectsSample();
  const api = useParkApi();
  const key = `${worldId}/${artifactId}`;
  const [loaded, setLoaded] = useState<{ key: string; view: QuizView } | undefined>();
  useEffect(() => {
    if (sample || rawSpecProp !== undefined) return;
    let active = true;
    void readQuizApp(api, worldId, artifactId)
      .then((view) => {
        if (active) setLoaded({ key, view });
      })
      .catch(() => {
        if (active) setLoaded(undefined);
      });
    return () => {
      active = false;
    };
  }, [api, key, worldId, artifactId, sample, rawSpecProp]);
  const liveView = loaded?.key === key ? loaded.view : undefined;
  const publishers =
    publishersProp ?? (sample ? QUIZ_FIXTURE_PUBLISHERS : (liveView?.publishers ?? {}));
  const raw = rawSpecProp !== undefined ? rawSpecProp : sample ? QUIZ_FIXTURE_SPEC : liveView?.spec;
  const validation = useMemo(
    () => (raw === undefined ? { ok: false as const, reason: "" } : validateAppSpec(raw)),
    [raw],
  );
  const unavailable = raw === undefined;
  const showSample = rawSpecProp === undefined && sample;

  const initialSeconds = validation.ok ? validation.spec.timer.seconds : 60;
  const [topic, setTopic] = useState<string>("all");
  const [index, setIndex] = useState<number>(0);
  const [answers, setAnswers] = useState<Record<string, AppSpecOptionId>>({});
  const [remaining, setRemaining] = useState<number>(initialSeconds);
  const [paused, setPaused] = useState<boolean>(false);
  const [submitted, setSubmitted] = useState<"manual" | "time_up" | null>(null);
  const [attemptCount, setAttemptCount] = useState<number>(
    () => readQuizAttempts(worldId, artifactId).length,
  );
  const optionRefs = useRef<Partial<Record<AppSpecOptionId, HTMLButtonElement | null>>>({});
  const remainingRef = useRef(remaining);
  remainingRef.current = remaining;
  const answersRef = useRef(answers);
  answersRef.current = answers;

  useEffect(() => {
    if (!validation.ok) return;
    setTopic("all");
    setIndex(0);
    setAnswers({});
    answersRef.current = {};
    setRemaining(validation.spec.timer.seconds);
    remainingRef.current = validation.spec.timer.seconds;
    setPaused(false);
    setSubmitted(null);
    setAttemptCount(readQuizAttempts(worldId, artifactId).length);
  }, [validation, worldId, artifactId]);

  const questions = useMemo(
    () => (validation.ok ? filterQuestionsByTopic(validation.spec.questions, topic) : []),
    [validation, topic],
  );

  const finalizeSubmit = useCallback(
    (reason: "manual" | "time_up", currentAnswers: Readonly<Record<string, AppSpecOptionId>>) => {
      if (!validation.ok) return;
      const activeQuestions = filterQuestionsByTopic(validation.spec.questions, topic);
      const scored = scoreQuizAttempt(activeQuestions, currentAnswers);
      const saved = saveQuizAttempt(worldId, artifactId, {
        worldId,
        artifactId,
        topic,
        correct: scored.correct,
        total: scored.total,
        unanswered: scored.unanswered,
        reason,
        answers: currentAnswers,
      });
      setAttemptCount(saved.length);
      setSubmitted(reason);
    },
    [validation, topic, worldId, artifactId],
  );

  // Personal countdown timer: ticks once per second through useSchedule() while active and unpaused.
  useEffect(() => {
    if (!validation.ok || submitted !== null || paused) return;
    if (remainingRef.current <= 0) {
      finalizeSubmit("time_up", answersRef.current);
      return;
    }
    let active = true;
    let cancelCurrent: (() => void) | null = null;
    const tick = () => {
      if (!active) return;
      const next = remainingRef.current - 1;
      if (next <= 0) {
        remainingRef.current = 0;
        setRemaining(0);
        finalizeSubmit("time_up", answersRef.current);
        return;
      }
      remainingRef.current = next;
      setRemaining(next);
      cancelCurrent = schedule(tick, 1000);
    };
    cancelCurrent = schedule(tick, 1000);
    return () => {
      active = false;
      cancelCurrent?.();
    };
  }, [validation, submitted, paused, schedule, finalizeSubmit]);

  if (unavailable) {
    return (
      <div
        className="park-quiz-root"
        data-testid="park-page-quiz"
        data-world-id={worldId}
        data-artifact-id={artifactId}
        data-motion={app.motion}
      >
        <PageSheet>
          <div className="park-quiz-crumb">
            <button
              type="button"
              className="park-quiz-back"
              onClick={() => app.go("world", { id: worldId })}
            >
              Back to world
            </button>
          </div>
          <div data-testid="quiz-unavailable" className="park-quiz-error">
            <EmptyState
              title="This quiz is not available yet"
              body="Quizzes are not connected to your workspace yet."
            />
          </div>
        </PageSheet>
      </div>
    );
  }

  if (!validation.ok) {
    return (
      <div
        className="park-quiz-root"
        data-testid="park-page-quiz"
        data-world-id={worldId}
        data-artifact-id={artifactId}
        data-motion={app.motion}
      >
        <PageSheet>
          <div className="park-quiz-crumb">
            <button
              type="button"
              className="park-quiz-back"
              onClick={() => app.go("world", { id: worldId })}
            >
              Back to world
            </button>
          </div>
          <div data-testid="quiz-error" className="park-quiz-error">
            <ErrorState title="Quiz specification is invalid" body={validation.reason} />
          </div>
        </PageSheet>
      </div>
    );
  }

  const { spec } = validation;
  const topics = listTopics(spec.questions);
  const safeIndex = Math.min(index, Math.max(0, questions.length - 1));
  const currentQuestion = questions[safeIndex];
  const entries = currentQuestion ? optionEntries(currentQuestion.options) : [];
  const selectedOption = currentQuestion ? (answers[currentQuestion.id] ?? null) : null;
  const score = submitted !== null ? scoreQuizAttempt(questions, answers) : null;
  const answeredCount = questions.filter((q) => answers[q.id] !== undefined).length;

  const selectOption = (optId: AppSpecOptionId) => {
    if (!currentQuestion || submitted !== null) return;
    setAnswers((prev) => {
      const next = { ...prev, [currentQuestion.id]: optId };
      answersRef.current = next;
      return next;
    });
  };

  const handleOptionKeyDown = (
    e: ReactKeyboardEvent<HTMLButtonElement>,
    currentOptId: AppSpecOptionId,
  ) => {
    if (!currentQuestion || entries.length === 0) return;
    const idx = entries.findIndex(([id]) => id === currentOptId);
    if (idx < 0) return;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      e.preventDefault();
      const next = entries[(idx + 1) % entries.length];
      if (next) {
        selectOption(next[0]);
        optionRefs.current[next[0]]?.focus();
      }
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      e.preventDefault();
      const prev = entries[(idx - 1 + entries.length) % entries.length];
      if (prev) {
        selectOption(prev[0]);
        optionRefs.current[prev[0]]?.focus();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      selectOption(currentOptId);
      if (safeIndex + 1 < questions.length) {
        setIndex(safeIndex + 1);
      } else {
        finalizeSubmit("manual", { ...answers, [currentQuestion.id]: currentOptId });
      }
    }
  };

  const handleTopicChange = (e: ChangeEvent<HTMLSelectElement>) => {
    setTopic(e.target.value);
    setIndex(0);
  };

  const restartQuiz = () => {
    setAnswers({});
    answersRef.current = {};
    setIndex(0);
    setRemaining(spec.timer.seconds);
    remainingRef.current = spec.timer.seconds;
    setPaused(false);
    setSubmitted(null);
  };

  return (
    <div
      className="park-quiz-root"
      data-testid="park-page-quiz"
      data-world-id={worldId}
      data-artifact-id={artifactId}
      data-motion={app.motion}
    >
      <PageSheet>
        <nav aria-label="Breadcrumb" className="park-quiz-crumb">
          <button
            type="button"
            className="park-quiz-back"
            onClick={() => app.go("world", { id: worldId })}
          >
            Back to world
          </button>
          <span>/</span>
          <span>{spec.title}</span>
        </nav>

        <div className="park-quiz-head">
          <div className="park-quiz-titles">
            <div className="park-quiz-eyebrowrow">
              <span className="park-quiz-eyebrow">{`APPSPEC · ${spec.theme.toUpperCase()}`}</span>
              <span className="park-quiz-badge">
                {showSample ? "Sample · Practice quiz" : "Practice quiz"}
              </span>
            </div>
            <h1 className="park-quiz-h1" tabIndex={-1}>
              {spec.title}
            </h1>
          </div>

          <div className="park-quiz-controls">
            <label className="park-quiz-filter">
              <span>Topic</span>
              <select
                aria-label="Filter by topic"
                className="park-quiz-select"
                value={topic}
                disabled={submitted !== null}
                onChange={handleTopicChange}
              >
                <option value="all">All topics</option>
                {topics.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>

            <div className="park-quiz-timerbox">
              <span
                className="park-quiz-timer"
                data-testid="quiz-timer"
                aria-label="Time remaining"
              >
                {formatTimerMmSs(remaining)}
              </span>
              {submitted === null ? (
                <Button
                  variant="secondary"
                  size="sm"
                  data-testid="quiz-timer-toggle"
                  aria-pressed={paused}
                  onClick={() => setPaused((p) => !p)}
                >
                  {paused ? "Resume timer" : "Pause timer"}
                </Button>
              ) : null}
            </div>
          </div>
        </div>

        {submitted === null && currentQuestion ? (
          <section aria-label="Current question" className="park-quiz-card">
            <div className="park-quiz-meta">
              <span data-testid="quiz-progress">
                {`Question ${safeIndex + 1} of ${questions.length} · ${answeredCount} answered`}
              </span>
              {currentQuestion.topic ? (
                <span className="park-quiz-topicchip">{currentQuestion.topic}</span>
              ) : null}
            </div>

            <p className="park-quiz-stem" data-testid="quiz-stem">
              {currentQuestion.stem}
            </p>

            <fieldset
              aria-label={`Options for question ${safeIndex + 1}`}
              className="park-quiz-options"
            >
              {entries.map(([optId, optText]) => {
                const checked = selectedOption === optId;
                return (
                  <button
                    key={optId}
                    ref={(el) => {
                      optionRefs.current[optId] = el;
                    }}
                    type="button"
                    aria-pressed={checked}
                    data-option-id={optId}
                    className="park-quiz-option"
                    onClick={() => selectOption(optId)}
                    onKeyDown={(e) => handleOptionKeyDown(e, optId)}
                  >
                    <span className="park-quiz-optkey">{optId}</span>
                    <span>{optText}</span>
                  </button>
                );
              })}
            </fieldset>

            <div className="park-quiz-source" data-testid="quiz-source">
              {formatPublisherLine(currentQuestion.source, publishers)}
            </div>

            <div className="park-quiz-nav">
              <div className="park-quiz-navleft">
                <Button
                  variant="secondary"
                  size="sm"
                  data-testid="quiz-prev"
                  disabled={safeIndex === 0}
                  onClick={() => setIndex(Math.max(0, safeIndex - 1))}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  data-testid="quiz-next"
                  disabled={safeIndex + 1 >= questions.length}
                  onClick={() => setIndex(Math.min(questions.length - 1, safeIndex + 1))}
                >
                  Next
                </Button>
              </div>
              <Button
                variant="primary"
                size="sm"
                data-testid="quiz-submit"
                onClick={() => finalizeSubmit("manual", answers)}
              >
                Submit quiz
              </Button>
            </div>
          </section>
        ) : null}

        {score ? (
          <section aria-label="Quiz results" className="park-quiz-card" data-testid="quiz-review">
            <div className="park-quiz-scorehead" data-testid="quiz-score-summary">
              <div>
                <div className="park-quiz-scorenum">
                  {`Score: ${score.correct} / ${score.total}`}
                </div>
                <div className="park-quiz-scoresub">
                  {submitted === "time_up"
                    ? `Time is up (00:00). ${score.unanswered} unanswered · ${attemptCount} saved attempts on this device`
                    : `${score.unanswered} unanswered · ${attemptCount} saved attempts on this device`}
                </div>
              </div>
              <Button variant="secondary" size="sm" onClick={restartQuiz}>
                Try again
              </Button>
            </div>

            <div className="park-quiz-reviewlist">
              {score.items.map((item, idx) => {
                const chosenText = item.chosen ? (item.options[item.chosen] ?? "") : "No answer";
                const correctText = item.options[item.correctAnswer] ?? "";
                const statusLabel =
                  item.status === "correct"
                    ? "Correct"
                    : item.status === "incorrect"
                      ? "Incorrect"
                      : "Unanswered";
                return (
                  <div
                    key={item.id}
                    className="park-quiz-reviewitem"
                    data-testid="quiz-review-item"
                  >
                    <div className="park-quiz-reviewtop">
                      <strong>{`Q${idx + 1}. ${item.stem}`}</strong>
                      <span className={`park-quiz-status park-quiz-status--${item.status}`}>
                        {statusLabel}
                      </span>
                    </div>
                    <div className="park-quiz-scoresub">
                      {item.chosen
                        ? `Your answer: ${item.chosen.toUpperCase()} (${chosenText}) · Correct answer: ${item.correctAnswer.toUpperCase()} (${correctText})`
                        : `Your answer: No answer · Correct answer: ${item.correctAnswer.toUpperCase()} (${correctText})`}
                    </div>
                    <div className="park-quiz-source">
                      {formatPublisherLine(item.source, publishers)}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        ) : null}
      </PageSheet>
    </div>
  );
}
