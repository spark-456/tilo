// "Learned skills" library section of the Skills page (design: Tilo App Skills.dc.html lines 302-365):
// - Searchable list of skills (including newly saved skills from FR-SKL-04, which start as Learning)
// - Detail pane with stats, cost-per-run bar, numbered steps, per-skill tool access, and Pause / Resume (FR-SKL-06)
// - A paused skill never starts when "Test run" / "Try run" is pressed (FR-SKL-06)
import { useState } from "react";
import type { Skill } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { type CurrencyCode, runMoney } from "../../app/ledgerKpis";
import { cx } from "../../components/cx";
import { agent, icon } from "./skillsKit";

type ShownStatus = Skill["st"] | "paused";

const STATUS_META: Record<ShownStatus, { label: string; tone: string }> = {
  trusted: { label: "Trusted", tone: "ok" },
  learning: { label: "Learning", tone: "hero" },
  review: { label: "Needs an answer", tone: "amber" },
  paused: { label: "Paused", tone: "chip" },
  draft: { label: "Draft", tone: "chip" },
};

const LEVELS = ["Off", "Read", "Draft", "Act"] as const;

const money = (v: number | undefined, currency: CurrencyCode = "GBP"): string =>
  v == null ? "—" : runMoney(v, currency);

export interface LibraryProps {
  app: AppCtx;
  skills: readonly Skill[];
  selectedId: string;
  paused: Readonly<Record<string, boolean>>;
  currency?: CurrencyCode;
  onSelect: (id: string) => void;
  onTogglePause: (skill: Skill) => void;
  onTryDraft: () => void;
}

export function LibrarySection({
  app,
  skills,
  selectedId,
  paused,
  currency = "GBP",
  onSelect,
  onTogglePause,
  onTryDraft,
}: LibraryProps) {
  const [q, setQ] = useState("");
  const [acc, setAcc] = useState<Record<string, Record<string, number>>>({});

  const cur = skills.find((s) => s.id === selectedId) ?? skills[0];
  if (!cur) return null;

  const shownOf = (s: Skill): ShownStatus => (paused[s.id] ? "paused" : s.st);
  const curShown = shownOf(cur);
  const isPaused = Boolean(paused[cur.id]);
  const filtered = skills.filter(
    (s) => !q || s.name.toLowerCase().includes(q.trim().toLowerCase()),
  );

  const pct =
    cur.first != null && cur.now != null && cur.first > 0
      ? Math.round((1 - cur.now / cur.first) * 100)
      : 0;
  const barWidth =
    cur.first != null && cur.now != null && cur.first > 0
      ? `${Math.max(6, Math.round((cur.now / cur.first) * 100))}%`
      : "0%";

  const stats = [
    { k: "Runs", v: String(cur.runs) },
    { k: "Success", v: cur.rate != null ? `${cur.rate}%` : "—" },
    { k: "Last run", v: cur.last },
    { k: "Improved", v: cur.improved },
  ];

  const handleTestRun = () => {
    if (isPaused) return;
    if (cur.st === "draft") {
      onTryDraft();
      return;
    }
    app.toast("Test run started on yesterday’s data. Results in about a minute");
  };

  return (
    <section aria-label="Learned skills" className="park-skills-section">
      <div>
        <h2 className="park-skills-h2">Learned skills</h2>
        <div className="park-skills-section-sub">
          Pick one to see its steps, cost per run and tool access.
        </div>
      </div>
      <div className="park-skills-lib-grid">
        <div className="park-skills-lib-list">
          <div className="park-skills-lib-search-wrap">
            <div className="park-skills-lib-search">
              {icon("search", 15)}
              <input
                aria-label="Search skills"
                placeholder="Search skills"
                className="park-skills-lib-search-input"
                value={q}
                onChange={(e) => setQ(e.currentTarget.value)}
              />
            </div>
          </div>
          {filtered.map((s) => {
            const on = s.id === cur.id;
            const stShown = shownOf(s);
            const meta = STATUS_META[stShown];
            const sub = `${s.team} · ${
              s.used.length
                ? `used in ${s.used.length} ${s.used.length === 1 ? "world" : "worlds"}`
                : "not used yet"
            }`;
            const expr =
              stShown === "paused"
                ? "sleepy"
                : stShown === "review"
                  ? "needs"
                  : stShown === "trusted"
                    ? "delighted"
                    : "neutral";
            return (
              <button
                key={s.id}
                type="button"
                aria-pressed={on}
                className={cx("park-skills-lib-row", on && "park-skills-lib-row--on")}
                onClick={() => onSelect(s.id)}
              >
                <span className="park-skills-lib-row-tile">
                  {agent({ role: s.role, expr }, 38, app.night)}
                </span>
                <span className="park-skills-lib-row-main">
                  <span className="park-skills-lib-row-name">{s.name}</span>
                  <span className="park-skills-lib-row-sub">{sub}</span>
                </span>
                <span className="park-skills-lib-row-right">
                  <span className={`park-skills-lib-chip park-skills-lib-chip--${meta.tone}`}>
                    {meta.label}
                  </span>
                  <span className="park-skills-lib-row-cost">
                    {s.now != null ? `${money(s.now, currency)} a run` : "Not run yet"}
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        <div className="park-skills-lib-detail">
          <div className="park-skills-lib-head">
            <div className="park-skills-lib-title-row">
              <div className="park-skills-lib-avatar">
                {agent({ role: cur.role, expr: "focused" }, 52, app.night)}
              </div>
              <div className="park-skills-lib-title-col">
                <div className="park-skills-lib-eyebrow">
                  {`${cur.team} · ${STATUS_META[curShown].label}`.toUpperCase()}
                </div>
                <h3 className="park-skills-lib-h3">{cur.name}</h3>
                <div className="park-skills-lib-owner">
                  {`Owned by ${cur.owner} · learned from ${cur.from || "—"}`}
                </div>
              </div>
            </div>
            <div className="park-skills-lib-actions">
              <button
                type="button"
                disabled={isPaused}
                className="park-skills-lib-test"
                onClick={handleTestRun}
              >
                {icon("play", 13)}
                {cur.st === "draft" ? "Try run" : "Test run"}
              </button>
              <button
                type="button"
                className="park-skills-lib-secondary"
                onClick={() => onTogglePause(cur)}
              >
                {isPaused ? "Resume" : "Pause"}
              </button>
              <button
                type="button"
                className="park-skills-lib-secondary"
                onClick={() => app.toast("Step editor opens here. Changes are versioned")}
              >
                Edit steps
              </button>
            </div>
          </div>

          <div className="park-skills-lib-stats">
            {stats.map((m) => (
              <div key={m.k} className="park-skills-lib-stat">
                <span className="park-skills-lib-stat-k">{m.k}</span>
                <span className="park-skills-lib-stat-v">{m.v}</span>
              </div>
            ))}
          </div>

          {cur.first != null ? (
            <div className="park-skills-lib-cost">
              <div className="park-skills-lib-cost-top">
                <span>Cost per run</span>
                <span className="park-skills-lib-cost-drop">
                  {pct > 0 ? `${pct}% cheaper than the first run` : "Same as the first run"}
                </span>
              </div>
              <div className="park-skills-lib-cost-track">
                <div className="park-skills-lib-cost-fill" style={{ width: barWidth }} />
              </div>
              <div className="park-skills-lib-cost-sub">
                <span>{`First run ${money(cur.first, currency)}`}</span>
                <span>{`Now ${money(cur.now, currency)}`}</span>
              </div>
            </div>
          ) : null}

          <div className="park-skills-lib-steps-sec">
            <h4 className="park-skills-h4">Steps</h4>
            <ol className="park-skills-lib-steps">
              {cur.steps.map((step, i) => (
                <li key={`${i + 1}-${step}`} className="park-skills-lib-step">
                  <span className="park-skills-lib-step-n">{i + 1}</span>
                  {step}
                </li>
              ))}
            </ol>
          </div>

          <div className="park-skills-lib-access-sec">
            <div className="park-skills-lib-access-head">
              <h4 className="park-skills-h4">Tool access for this skill</h4>
              <button
                type="button"
                className="park-skills-lib-link"
                onClick={() => app.go("connectors")}
              >
                Manage connectors
              </button>
            </div>
            {cur.tools.map(([toolName, defaultLv]) => {
              const lv = acc[cur.id]?.[toolName] ?? defaultLv;
              return (
                <div key={toolName} className="park-skills-lib-access-row">
                  <span className="park-skills-lib-access-mono">{toolName[0]}</span>
                  <span className="park-skills-lib-access-name">{toolName}</span>
                  <fieldset aria-label={`${toolName} access`} className="park-skills-lib-seg">
                    {LEVELS.map((label, i) => {
                      const on = lv === i;
                      return (
                        <button
                          key={label}
                          type="button"
                          aria-pressed={on}
                          className={cx(
                            "park-skills-lib-seg-btn",
                            on && "park-skills-lib-seg-btn--on",
                          )}
                          onClick={() => {
                            setAcc((prev) => ({
                              ...prev,
                              [cur.id]: { ...(prev[cur.id] ?? {}), [toolName]: i },
                            }));
                            app.toast(
                              `${toolName} access set to ${label}${i === 3 ? ". Team rules still apply" : ""}`,
                            );
                          }}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </fieldset>
                </div>
              );
            })}
          </div>

          <div className="park-skills-lib-used-sec">
            <h4 className="park-skills-h4">Used in</h4>
            <div className="park-skills-lib-used-list">
              {cur.used.map((worldId) => (
                <button
                  key={worldId}
                  type="button"
                  className="park-skills-lib-used-btn"
                  onClick={() => app.go("world", { id: worldId })}
                >
                  {worldId}
                  {icon("chevR", 12)}
                </button>
              ))}
              {cur.used.length === 0 ? (
                <span className="park-skills-lib-unused">Not used in any world yet.</span>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
