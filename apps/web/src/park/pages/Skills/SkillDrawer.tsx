// STUDIO-4: one skill's detail as a side sheet (a bottom sheet on a phone), design/studio-v2 "Tilo S Skills" view
// drawer: what it does, the steps it follows, its numbers (a dash where the Api serves none), tool access, the worlds
// it was used in, and its actions. Pause and Resume post `POST /v1/skills/{id}/state` on a live page and show the
// server's answer; "Test run" has no route yet and says so. Escape, the close button or the scrim close it.
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import type { Skill } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { type CurrencyCode, runMoney } from "../../app/ledgerKpis";
import { Button } from "../../components";
import { cx } from "../../components/cx";
import { agent, icon } from "./skillsKit";

export type Shown = Skill["st"] | "paused";

export const STATUS: Record<Shown, { label: string; tone: string }> = {
  trusted: { label: "Trusted", tone: "ok" },
  learning: { label: "Learning", tone: "lilac" },
  review: { label: "Needs an answer", tone: "amber" },
  paused: { label: "Paused", tone: "chip" },
  draft: { label: "Draft", tone: "chip" },
};

export const statusOf = (s: Skill, paused: boolean): { label: string; tone: string } =>
  s.builtin ? { label: "Built-in", tone: "chip" } : STATUS[paused || s.paused ? "paused" : s.st];

/** A practice or test run has no route yet (STUDIO-4): the button says so, never pretends. */
export const RUN_OFF = "Test runs are not available yet. Nothing was started.";

const LEVELS = ["Off", "Read", "Draft", "Act"] as const;
const money = (v: number | undefined, currency: CurrencyCode): string =>
  v == null ? "—" : runMoney(v, currency);

export interface DrawerProps {
  app: AppCtx;
  skill: Skill;
  paused: boolean;
  currency: CurrencyCode;
  /** Pause or resume: a promise that settles once the change is recorded (or refused). Null when it cannot be done here. */
  onPause: ((skill: Skill, pause: boolean) => Promise<void> | undefined) | null;
  /** Why pausing cannot be done from here, shown beside the disabled button. */
  pauseOff: string;
  onTeach: () => void;
  onClose: () => void;
  /** The step-fix form (a live owned skill), placed under the steps. */
  fix?: ReactNode;
}

export function SkillDrawer({
  app,
  skill,
  paused,
  currency,
  onPause,
  pauseOff,
  onTeach,
  onClose,
  fix,
}: DrawerProps) {
  const title = useId();
  const close = useRef<HTMLButtonElement>(null);
  const [acc, setAcc] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const st = statusOf(skill, paused);
  const isPaused = paused || skill.paused === true;

  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const stats = [
    { k: "Runs", v: skill.runs == null ? "—" : String(skill.runs) },
    { k: "Success", v: skill.rate != null ? `${skill.rate}%` : "—" },
    { k: "Last run", v: skill.last || "—" },
    { k: "Cost a run", v: money(skill.now, currency) },
  ];
  const meta = [
    skill.builtin
      ? `Shipped with Tilo · version ${skill.from}`
      : skill.owner
        ? `Owned by ${skill.owner}`
        : "",
    skill.team,
    skill.used.length
      ? `used in ${skill.used.length} ${skill.used.length === 1 ? "world" : "worlds"}`
      : "",
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: a click-away layer; Escape is the keyboard way out (above)
    <div
      className="park-skill-scrim"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* biome-ignore lint/a11y/useSemanticElements: a side sheet over its own scrim; Escape and focus are handled here */}
      <aside role="dialog" aria-modal="true" aria-labelledby={title} className="park-skill-drawer">
        <div className="park-skill-drawer__head">
          <span className="park-skill-drawer__art" aria-hidden="true">
            {agent({ role: skill.role, expr: isPaused ? "sleepy" : "focused" }, 56, app.night)}
          </span>
          <div className="park-skill-drawer__titles">
            <div className="park-skill-drawer__titlerow">
              <h2 id={title} className="park-skill-drawer__h2">
                {skill.name}
              </h2>
              <span className={`park-skill-chip park-skill-chip--${st.tone}`}>{st.label}</span>
            </div>
            {meta ? <div className="park-skill-drawer__meta">{meta}</div> : null}
          </div>
          <button
            ref={close}
            type="button"
            aria-label="Close"
            className="park-skill-drawer__close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className="park-skill-drawer__body">
          {skill.description ? (
            <section className="park-skill-drawer__sec">
              <h3 className="park-skill-drawer__h3">What it does</h3>
              <p className="park-skill-drawer__p">{skill.description}</p>
            </section>
          ) : null}
          {skill.steps.length ? (
            <section className="park-skill-drawer__sec">
              <h3 className="park-skill-drawer__h3">Steps it follows</h3>
              <ol className="park-skill-drawer__steps">
                {skill.steps.map((s, i) => (
                  <li key={`${i + 1}-${s}`} className="park-skill-drawer__step">
                    <span className="park-skill-drawer__n">{i + 1}</span>
                    <span>{s}</span>
                    {skill.fix?.asks[i] ? (
                      <span className="park-skill-chip park-skill-chip--amber">Asks you first</span>
                    ) : null}
                  </li>
                ))}
              </ol>
            </section>
          ) : null}
          {fix}
          {skill.builtin ? null : (
            <dl className="park-skill-drawer__stats">
              {stats.map((m) => (
                <div key={m.k} className="park-skill-drawer__stat">
                  <dt>{m.k}</dt>
                  <dd>{m.v}</dd>
                </div>
              ))}
            </dl>
          )}
          {skill.first != null && skill.now != null && skill.first > 0 ? (
            <p className="park-skill-drawer__cost">
              <strong>
                {skill.now < skill.first
                  ? `${Math.round((1 - skill.now / skill.first) * 100)}% cheaper than the first run`
                  : "Same as the first run"}
              </strong>
              <span>{`First run ${money(skill.first, currency)} · Now ${money(skill.now, currency)}`}</span>
            </p>
          ) : null}
          {skill.tools.length ? (
            <section className="park-skill-drawer__sec">
              <div className="park-skill-drawer__row">
                <h3 className="park-skill-drawer__h3">Tool access for this skill</h3>
                <button
                  type="button"
                  className="park-skill-link"
                  onClick={() => app.go("connectors")}
                >
                  Manage connectors
                </button>
              </div>
              {skill.tools.map(([tool, level]) => {
                const lv = acc[tool] ?? level;
                return (
                  <div key={tool} className="park-skill-drawer__tool">
                    <span className="park-skill-drawer__toolname">{tool}</span>
                    <fieldset aria-label={`${tool} access`} className="park-skill-seg">
                      {LEVELS.map((label, i) => (
                        <button
                          key={label}
                          type="button"
                          aria-pressed={lv === i}
                          className={cx(
                            "park-skill-seg__btn",
                            lv === i && "park-skill-seg__btn--on",
                          )}
                          onClick={() => {
                            setAcc((p) => ({ ...p, [tool]: i }));
                            app.toast(
                              `${tool} access set to ${label} on this page only. Team rules still apply`,
                            );
                          }}
                        >
                          {label}
                        </button>
                      ))}
                    </fieldset>
                  </div>
                );
              })}
            </section>
          ) : null}
          {skill.builtin ? null : (
            <section className="park-skill-drawer__sec">
              <h3 className="park-skill-drawer__h3">Used in</h3>
              {skill.used.length ? (
                <div className="park-skill-drawer__used">
                  {skill.used.map((w) => (
                    <button
                      key={w}
                      type="button"
                      className="park-skill-link"
                      onClick={() => app.go("world", { id: w })}
                    >
                      {w}
                      {icon("chevR", 12)}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="park-skill-drawer__p">Not used in any world yet.</p>
              )}
            </section>
          )}
        </div>
        <div className="park-skill-drawer__foot">
          <Button variant="primary" onClick={onTeach}>
            Teach a new version
          </Button>
          {skill.builtin ? null : (
            <>
              <Button variant="secondary" disabled title={RUN_OFF}>
                {skill.st === "draft" ? "Try run" : "Test run"}
              </Button>
              <Button
                variant="secondary"
                disabled={onPause === null || busy}
                title={onPause === null ? pauseOff : undefined}
                onClick={() => {
                  if (!onPause) return;
                  const sent = onPause(skill, !isPaused); // a sample-data pause is this page's only: no wait
                  if (sent) {
                    setBusy(true);
                    sent.finally(() => setBusy(false));
                  }
                }}
              >
                {isPaused ? "Resume" : "Pause"}
              </Button>
            </>
          )}
          <p className="park-skill-drawer__note">
            {skill.builtin
              ? "Built-in skills are picked by agents during a run."
              : `${RUN_OFF.replace(" Nothing was started.", "")}${onPause === null ? ` ${pauseOff}` : ""}`}
          </p>
        </div>
      </aside>
    </div>
  );
}
