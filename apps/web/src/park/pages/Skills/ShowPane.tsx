// Step 1, "Show it": four ways to show the task, the mock browser / description box / dropzone for the
// chosen way, and "What Tilo has picked up" with the skill's name and the way on to step 2.
import { cx } from "../../components/cx";
import { agent, icon } from "./skillsKit";
import {
  CAP,
  CAPTURED_HINT,
  CAPTURE_STEPS,
  DESCRIBE_HELP,
  DROP,
  GUIDED,
  METHODS,
  MOCK_ROWS,
  NO_STEPS_YET,
  RECORD,
} from "./teachData";
import type { PaneProps } from "./useTeach";

export function ShowPane({ t, night, user }: PaneProps) {
  const live = t.live;
  const screenish = !live && (t.method === "record" || t.method === "guided");
  const shown: readonly string[] = live ? t.steps : CAP[t.method].slice(0, t.cap);
  const done = live ? t.steps.length > 0 : t.cap >= CAPTURE_STEPS;
  const of = live ? t.steps.length : CAPTURE_STEPS;
  const domain = user.email.split("@")[1];
  const url = t.method === "guided" ? GUIDED.url : domain ? `mail.${domain}/accounts` : GUIDED.url;
  const hint = t.method === "guided" ? GUIDED.hint : RECORD.hint;
  const start = t.method === "guided" ? GUIDED.start : RECORD.start;
  const label = t.rec ? "Recording…" : done ? "Record again" : start;
  return (
    <div className="park-skills-pane park-skills-pane--show">
      {live ? null : (
        <div className="park-skills-methods">
          {METHODS.map((m) => (
            <button
              key={m.key}
              type="button"
              aria-pressed={t.method === m.key}
              className={cx("park-skills-method", t.method === m.key && "park-skills-method--on")}
              onClick={() => t.setMethod(m.key)}
            >
              <span className="park-skills-method-ic">{icon(m.icon, 18)}</span>
              <span className="park-skills-method-text">
                <span className="park-skills-method-name">{m.name}</span>
                <span className="park-skills-method-desc">{m.desc}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      <div className="park-skills-cols">
        <div className="park-skills-col">
          {screenish ? (
            <div className="park-skills-mock">
              <div className="park-skills-mock-bar">
                <span className="park-skills-light park-skills-light--red" />
                <span className="park-skills-light park-skills-light--amber" />
                <span className="park-skills-light park-skills-light--green" />
                <span className="park-skills-mock-addr">{url}</span>
              </div>
              <div className="park-skills-mock-body">
                {MOCK_ROWS.map((w, i) => (
                  <div
                    key={w}
                    className={cx(
                      "park-skills-mock-row",
                      t.rec && t.cap === i && "park-skills-mock-row--watched",
                    )}
                  >
                    <span className="park-skills-mock-dot" />
                    <span className="park-skills-mock-line" style={{ width: `${w}%` }} />
                    <span className="park-skills-grow" />
                    <span className="park-skills-mock-end" />
                  </div>
                ))}
              </div>
              <div className="park-skills-mock-foot">
                {t.rec ? (
                  <div className="park-skills-rec">
                    <span className="park-skills-rec-dot" />
                    {`REC 00:0${2 + t.cap * 2}`}
                  </div>
                ) : (
                  <div className="park-skills-mock-hint">{done ? CAPTURED_HINT : hint}</div>
                )}
                <div className="park-skills-grow" />
                <button
                  type="button"
                  className={cx(
                    "park-skills-capture",
                    t.rec && "park-skills-capture--rec",
                    !t.rec && done && "park-skills-capture--done",
                  )}
                  disabled={t.rec}
                  onClick={t.capture}
                >
                  {icon("record", 15)}
                  {label}
                </button>
              </div>
            </div>
          ) : null}
          {t.method === "describe" ? (
            <div className="park-skills-describe">
              <textarea
                aria-label="Describe the task"
                className="park-skills-task"
                value={t.desc}
                onChange={(e) => t.setDesc(e.target.value)}
              />
              {live && t.failure ? (
                <div
                  className="park-skills-describe-help"
                  role="alert"
                  data-testid="skills-teach-error"
                >
                  {t.failure}
                </div>
              ) : null}
              <div className="park-skills-describe-foot">
                <div className="park-skills-describe-help">{DESCRIBE_HELP}</div>
                <button
                  type="button"
                  className="park-skills-read"
                  disabled={live && (t.busy || !t.desc.trim())}
                  onClick={t.capture}
                >
                  Read my description
                </button>
              </div>
            </div>
          ) : null}
          {t.method === "upload" ? (
            <button
              type="button"
              className={cx("park-skills-drop", done && "park-skills-drop--done")}
              onClick={t.capture}
            >
              <span className="park-skills-drop-ic">{icon("upload", 22)}</span>
              <span className="park-skills-drop-title">{done ? DROP.doneTitle : DROP.title}</span>
              <span className="park-skills-drop-sub">{done ? DROP.doneSub : DROP.sub}</span>
            </button>
          ) : null}
        </div>
        <div className="park-skills-picked">
          <div className="park-skills-picked-head">
            <span className="park-skills-picked-title">What Tilo has picked up</span>
            {live ? null : (
              <span
                className="park-skills-pill park-skills-pill--chip"
                data-testid="skills-sample-run"
              >
                Sample run
              </span>
            )}
            <span className="park-skills-picked-count">{`${live ? shown.length : t.cap} of ${of}`}</span>
          </div>
          {shown.map((text, i) => (
            <div key={`${i}:${text}`} className="park-skills-cap-row">
              <span className="park-skills-cap-n">{i + 1}</span>
              <span className="park-skills-cap-text">{text}</span>
            </div>
          ))}
          {shown.length === 0 ? (
            <div className="park-skills-none">
              <div>
                {agent({ role: "research", expr: t.rec ? "focused" : "neutral" }, 58, night)}
              </div>
              {NO_STEPS_YET}
            </div>
          ) : null}
          <div className="park-skills-grow" />
          <input
            aria-label="Skill name"
            className="park-skills-name"
            value={t.name}
            onChange={(e) => t.setName(e.target.value)}
          />
          <button
            type="button"
            className={cx(
              "park-skills-next",
              done ? "park-skills-next--ready" : "park-skills-next--locked",
            )}
            disabled={!done || t.busy}
            onClick={t.next}
          >
            Show me Tilo’s version
          </button>
        </div>
      </div>
    </div>
  );
}
