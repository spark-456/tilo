// STUDIO-4: the Needs you page (design/studio-v2 "Tilo S Needs", Canvas section 07), "made clearer": one decision at a
// time. Each is a plain question with what happens if yes, what happens if no, the cost and exactly what will be sent;
// every button says what it does. Data only through the Api: `getDecisions` (live: the cross-world `GET /cards` feed),
// answered with `app.decide` (live: one POST .../answer, decided only once the server recorded it, HR-1). A question
// takes a chosen option or a typed answer (OWN-ANSWER), a `provide` card its fields form (ADR-0035 L6d), a gate its
// "Show me" item read. Sample and demo rules stay the store's: a demo session's answer is never simulated.
import { type RefObject, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { isItemApi } from "../../../api/item";
import { EmptyState, ErrorState, LoadingState } from "../../../design/tilo-t";
import type { Decision, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { DecisionFields } from "../../app/DecisionFields";
import { QuestionAnswer } from "../../app/QuestionAnswer";
import { useParkApi } from "../../app/context";
import { useFieldsFor } from "../../app/fieldsContext";
import { Button } from "../../components";
import { SampleBadge } from "../../sample/SampleBadge";
import { SAMPLE_WORLD_ID } from "../../sample/sampleChoice";
import "./Needs.css";
import { ShowMe } from "./ShowMe";
import { currentOf, dueLabel, needView, splitQueue } from "./needsModel";

type Loaded = { decisions: Decision[]; names: Record<string, string> } | "failed" | null;

const typing = (t: EventTarget | null): boolean =>
  t instanceof HTMLElement &&
  (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

export function NeedsPage({ app }: { app: AppCtx }) {
  const api = useParkApi();
  const [data, setData] = useState<Loaded>(null);
  const [attempt, setAttempt] = useState(0);
  const [chosen, setChosen] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const read = useRef({ dec: app.dec, added: app.added });
  read.current = { dec: app.dec, added: app.added };

  useEffect(() => {
    void attempt;
    let live = true;
    setData(null);
    const names = api
      .getWorlds(read.current.dec, read.current.added)
      .then((r) => r.data)
      .catch(() => [] as World[]);
    Promise.all([api.getDecisions(), names]).then(
      ([d, worlds]) => {
        if (!live) return;
        setData({
          decisions: d.data,
          names: Object.fromEntries(worlds.map((w) => [w.id, w.name])),
        });
      },
      () => {
        if (live) setData("failed");
      },
    );
    return () => {
      live = false;
    };
  }, [api, attempt]);

  const all = data && data !== "failed" ? data.decisions : [];
  const { open, done } = useMemo(() => splitQueue(all, app.dec), [all, app.dec]);
  const current = currentOf(open, chosen);
  const at = current ? open.indexOf(current) : -1;

  const move = useCallback(
    (step: number) => {
      if (open.length === 0) return;
      const i = Math.min(open.length - 1, Math.max(0, at + step));
      setChosen(open[i]?.k ?? null);
    },
    [open, at],
  );

  // J and K move between decisions (never while typing an answer).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey || typing(e.target)) return;
      if (e.key === "j" || e.key === "J") move(1);
      else if (e.key === "k" || e.key === "K") move(-1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [move]);

  // Once the shown decision is answered the next one takes its place: the reader is taken to its question.
  const shownKey = current?.k ?? null;
  const lastShown = useRef(shownKey);
  useEffect(() => {
    if (
      lastShown.current !== null &&
      shownKey !== lastShown.current &&
      chosen === lastShown.current
    )
      heading.current?.focus();
    lastShown.current = shownKey;
  }, [shownKey, chosen]);

  const worldName = (id: string) =>
    (data && data !== "failed" ? data.names[id] : undefined) ??
    (id === SAMPLE_WORLD_ID ? "Sample project" : id);

  return (
    <div className="park-needs" data-testid="park-page-needs">
      <div className="park-needs__head">
        <div className="park-needs__titles">
          <div className="park-needs__titlerow">
            <h1 className="park-needs__h1" tabIndex={-1}>
              Needs you
            </h1>
            {data && data !== "failed" && open.length > 0 ? (
              <span className="park-needs__count">{`${open.length} waiting`}</span>
            ) : null}
          </div>
          <p className="park-needs__lede">
            Tilo has paused these until you decide. Read what will happen, then answer.
          </p>
        </div>
        {open.length > 1 ? (
          <p className="park-needs__keys" aria-hidden="true">
            <kbd>J</kbd>
            <kbd>K</kbd>
            to move
          </p>
        ) : null}
      </div>

      {data === null ? (
        <LoadingState layout="split" caption="Loading what needs you" />
      ) : data === "failed" ? (
        <ErrorState
          title="Needs you could not load"
          body="Nothing was answered. Try again in a moment."
          action={
            <Button variant="primary" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </Button>
          }
        />
      ) : current === null ? (
        <>
          <EmptyState
            title="Nothing needs you"
            body="Tilo will ask here when a decision is yours to make."
            action={
              <Button variant="primary" onClick={() => app.go("worlds")}>
                See your worlds
              </Button>
            }
          />
          <Decided done={done} />
        </>
      ) : (
        <div className="park-needs__grid">
          <OneDecision
            key={current.k}
            app={app}
            d={current}
            position={`${at + 1} of ${open.length}`}
            worldName={worldName(current.world)}
            heading={heading}
            onPrev={at > 0 ? () => move(-1) : null}
            onNext={at < open.length - 1 ? () => move(1) : null}
          />
          <div className="park-needs__side">
            <nav aria-label="Waiting on you" className="park-needs__queue">
              <div className="park-needs__queuehead">
                <h2 className="park-needs__h3">Waiting on you</h2>
                <span className="park-needs__hint">In the order asked</span>
              </div>
              <ol className="park-needs__list">
                {open.map((d) => {
                  const v = needView(d);
                  const on = d.k === current.k;
                  return (
                    <li key={d.k}>
                      <button
                        type="button"
                        className={`park-needs__row${on ? " park-needs__row--on" : ""}`}
                        aria-current={on ? "true" : undefined}
                        onClick={() => setChosen(d.k)}
                      >
                        <span className="park-needs__rowtitle">{v.question}</span>
                        <span className="park-needs__rowworld">{worldName(d.world)}</span>
                        <span className="park-needs__rowtags">
                          <span className={`park-needs__tag park-needs__tag--${v.kind}`}>
                            {v.tag}
                          </span>
                          {v.due ? (
                            <span className="park-needs__due">{`By ${dueLabel(v.due)}`}</span>
                          ) : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            </nav>
            <Decided done={done} />
          </div>
        </div>
      )}
    </div>
  );
}

function Decided({ done }: { done: readonly Decision[] }) {
  if (done.length === 0) return null;
  return (
    <section aria-label="Answered here" className="park-needs__done">
      <h2 className="park-needs__h3">Recently decided</h2>
      <ul className="park-needs__donelist">
        {done.map((d) => (
          <li key={d.k} className="park-needs__doneitem">
            <span className="park-needs__donemark" aria-hidden="true">
              ✓
            </span>
            <span>{d.title}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function OneDecision({
  app,
  d,
  position,
  worldName,
  heading,
  onPrev,
  onNext,
}: {
  app: AppCtx;
  d: Decision;
  position: string;
  worldName: string;
  heading: RefObject<HTMLHeadingElement>;
  onPrev: (() => void) | null;
  onNext: (() => void) | null;
}) {
  const v = needView(d);
  const fieldsFor = useFieldsFor();
  const item = useMemo(() => {
    const a = fieldsFor?.(d.world) ?? null;
    return a && isItemApi(a) ? a : null;
  }, [fieldsFor, d.world]);
  const tapAnswer = v.kind === "gate" || v.kind === "consent" || v.kind === "plain";
  const gateAlternatives =
    d.card?.kind === "gate" ? d.card.options.filter((option) => option.id !== "approve") : [];
  const says = `need-says-${d.k}`.replace(/[^A-Za-z0-9_-]/g, "_");
  return (
    <article className="park-needs__card" aria-labelledby={`${says}-q`}>
      <div className="park-needs__bar">
        <span className="park-needs__world">
          {worldName}
          {d.world === SAMPLE_WORLD_ID ? <SampleBadge /> : null}
        </span>
        <span className="park-needs__spacer" />
        <span className="park-needs__pos">{position}</span>
        <button
          type="button"
          className="park-needs__nav"
          aria-label="Previous decision"
          disabled={onPrev === null}
          onClick={onPrev ?? undefined}
        >
          ‹
        </button>
        <button
          type="button"
          className="park-needs__nav"
          aria-label="Next decision"
          disabled={onNext === null}
          onClick={onNext ?? undefined}
        >
          ›
        </button>
      </div>
      <div className="park-needs__body">
        <div className="park-needs__ask">
          <span className={`park-needs__tag park-needs__tag--${v.kind}`}>
            {v.tag}
            {v.due ? ` · answer by ${dueLabel(v.due)}` : ""}
          </span>
          <h2 id={`${says}-q`} ref={heading} tabIndex={-1} className="park-needs__q">
            {v.question}
          </h2>
          {v.context ? <p className="park-needs__context">{v.context}</p> : null}
          {v.risk ? (
            <p className={`park-needs__risk park-needs__risk--${v.risk.tone}`} aria-label="Risk">
              <strong>{v.risk.label}:</strong> {v.risk.detail}
            </p>
          ) : null}
        </div>

        <div className="park-needs__what">
          <section
            className="park-needs__box park-needs__box--yes"
            aria-label={v.kind === "question" ? "Your choices" : "If you say yes"}
          >
            <h3 className="park-needs__boxh">
              {v.kind === "question" ? "Your choices" : "If you say yes"}
            </h3>
            <ul className="park-needs__lines">
              {v.yes.map((line) => (
                <li key={line}>
                  <span aria-hidden="true">✓</span>
                  {line}
                </li>
              ))}
            </ul>
          </section>
          <section
            className="park-needs__box park-needs__box--no"
            aria-label={
              v.kind === "question" || v.kind === "provide"
                ? "If you don’t answer"
                : "If you say no"
            }
          >
            <h3 className="park-needs__boxh">
              {v.kind === "question" || v.kind === "provide"
                ? "If you don’t answer"
                : "If you say no"}
            </h3>
            <ul className="park-needs__lines">
              {v.no.map((line) => (
                <li key={line}>
                  <span aria-hidden="true">–</span>
                  {line}
                </li>
              ))}
            </ul>
          </section>
          <section className="park-needs__box park-needs__box--cost" aria-label="Cost">
            <h3 className="park-needs__boxh">Cost</h3>
            {v.cost ? (
              <span className="park-needs__money">{v.cost}</span>
            ) : (
              <span className="park-needs__nocost">Not reported for this decision</span>
            )}
          </section>
        </div>

        {v.sent ? (
          <section className="park-needs__sent" aria-label="Exactly what will be sent">
            <h3 className="park-needs__boxh">Exactly what will be sent</h3>
            <div className="park-needs__sentbox">
              {v.sent.to.length ? (
                <div className="park-needs__sentrow">
                  <span className="park-needs__sentk">To</span>
                  <span className="park-needs__people">
                    {v.sent.to.map((p) => (
                      <span key={p} className="park-needs__person">
                        {p}
                      </span>
                    ))}
                  </span>
                </div>
              ) : null}
              {v.sent.item ? (
                <div className="park-needs__sentrow">
                  <span className="park-needs__sentk">Item</span>
                  <span>{v.sent.item}</span>
                </div>
              ) : null}
              <p className="park-needs__exact">{v.sent.exact}</p>
            </div>
            {d.card?.showMe && item ? <ShowMe api={item} cardId={d.card.id} /> : null}
          </section>
        ) : null}

        {v.why ? (
          <p className="park-needs__why">
            <strong>Why you’re seeing this:</strong> {v.why}
          </p>
        ) : null}
      </div>

      <div className="park-needs__actions">
        {d.provide ? <DecisionFields d={d} /> : null}
        {v.kind === "question" ? <QuestionAnswer d={d} onDecide={app.decide} /> : null}
        {tapAnswer && v.yesLabel ? (
          <>
            <Button
              variant="primary"
              aria-describedby={v.yesSays ? says : undefined}
              onClick={() => app.decide(d.k)}
            >
              {v.yesLabel}
            </Button>
            {gateAlternatives.map((option) => (
              <Button
                key={option.id}
                variant="secondary"
                onClick={() => app.decide(d.k, undefined, option.id)}
              >
                {option.label}
              </Button>
            ))}
            <Button
              variant="secondary"
              onClick={onNext ?? (() => app.go("world", { id: d.world }))}
            >
              {onNext ? "Decide later: next decision" : "Decide later: open the world"}
            </Button>
          </>
        ) : null}
        {!tapAnswer || !v.yesLabel ? (
          <Button variant="secondary" onClick={() => app.go("world", { id: d.world })}>
            Open in world
          </Button>
        ) : null}
        {v.yesSays && tapAnswer ? (
          <p id={says} className="park-needs__says">
            {v.yesSays} Deciding later sends nothing.
          </p>
        ) : null}
      </div>
    </article>
  );
}
