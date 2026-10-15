// STUDIO-4: the Skills gallery (design/studio-v2 "Tilo S Skills" view gallery): the Teach Tilo banner, search and
// status filters, every skill as a card, and "Learning now". Every number is the Api's; a skill the Api serves no
// count for says so. Pictures are the kit's still agents (no motion).
import { useState } from "react";
import type { Skill } from "../../api/types";
import { Button } from "../../components";
import { cx } from "../../components/cx";
import { statusOf } from "./SkillDrawer";
import { WIZARD_STEPS } from "./TeachWizard";
import { SkillIcon } from "./skillIcon";
import { agent, icon } from "./skillsKit";

type Filter = "all" | "builtin" | "yours" | "learning" | "trusted";
const FILTERS: readonly { key: Filter; label: string; test: (s: Skill) => boolean }[] = [
  { key: "all", label: "All", test: () => true },
  { key: "builtin", label: "Built-in", test: (s) => s.builtin === true },
  { key: "yours", label: "Taught", test: (s) => !s.builtin },
  { key: "learning", label: "Learning", test: (s) => !s.builtin && s.st === "learning" },
  { key: "trusted", label: "Trusted", test: (s) => !s.builtin && s.st === "trusted" },
];

const WAYS = [
  "Write it in plain words",
  "What goes in, what comes out",
  "Choose where Tilo asks first",
] as const;

export function TeachBanner({ night, onStart }: { night: boolean; onStart: () => void }) {
  return (
    <section aria-label="Teach Tilo a skill" className="park-skills-banner">
      <div className="park-skills-banner__art" aria-hidden="true">
        {agent({ role: "research", rank: "lead", expr: "talking" }, 120, night)}
      </div>
      <div className="park-skills-banner__text">
        <span className="park-skills-eyebrow">TEACH TILO A SKILL</span>
        <h2 className="park-skills-banner__h2">Show Tilo how you like it done, once.</h2>
        <ol className="park-skills-banner__ways">
          {WIZARD_STEPS.map((s, i) => (
            <li key={s.label} className="park-skills-banner__way">
              <span className="park-skills-banner__n">{i + 1}</span>
              <span>
                <strong>{s.label}</strong>
                <span className="park-skills-banner__sub">{WAYS[i]}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
      <Button variant="secondary" onClick={onStart}>
        Start teaching →
      </Button>
    </section>
  );
}

function sub(s: Skill): string {
  if (s.builtin) return s.description ?? "";
  if (s.steps.length)
    return `${s.steps.length} ${s.steps.length === 1 ? "step" : "steps"}: ${s.steps[0]}`;
  return "No steps yet.";
}

export function SkillGrid({
  skills,
  paused,
  onOpen,
}: {
  skills: readonly Skill[];
  paused: Readonly<Record<string, boolean>>;
  night: boolean;
  onOpen: (id: string) => void;
}) {
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const test = FILTERS.find((f) => f.key === filter)?.test ?? (() => true);
  const needle = q.trim().toLowerCase();
  const shown = skills.filter(
    (s) =>
      test(s) &&
      (!needle ||
        s.name.toLowerCase().includes(needle) ||
        (s.description ?? "").toLowerCase().includes(needle)),
  );
  return (
    <section aria-label="All skills" className="park-skills-gallery">
      <div className="park-skills-search">
        {icon("search", 20)}
        <input
          aria-label="Search skills"
          placeholder="Search skills, like “compare” or “invoice”"
          className="park-skills-search__input"
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
        />
      </div>
      <fieldset className="park-skills-filters">
        <legend className="park-sr-only">Show</legend>
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            className={cx("park-skills-filter", filter === f.key && "park-skills-filter--on")}
            onClick={() => setFilter(f.key)}
          >
            {f.label}
          </button>
        ))}
      </fieldset>
      <div className="park-skills-gallery__head">
        <h2 className="park-skills-h2">Your skills</h2>
        <span className="park-skills-gallery__count">
          {shown.length === skills.length
            ? `${skills.length} skills`
            : `${shown.length} of ${skills.length}`}
        </span>
      </div>
      {shown.length ? (
        <ul className="park-skills-cards">
          {shown.map((s) => {
            const st = statusOf(s, Boolean(paused[s.id]));
            return (
              <li key={s.id}>
                <button type="button" className="park-skills-card2" onClick={() => onOpen(s.id)}>
                  <span className="park-skills-card2__top">
                    <span className="park-skills-card2__art" aria-hidden="true">
                      <SkillIcon skill={s} />
                    </span>
                    <span className={`park-skill-chip park-skill-chip--${st.tone}`}>
                      {st.label}
                    </span>
                  </span>
                  <span className="park-skills-card2__name">{s.name}</span>
                  <span className="park-skills-card2__what">{sub(s)}</span>
                  <span className="park-skills-card2__foot">
                    <span>
                      {s.builtin
                        ? `Version ${s.from}`
                        : s.runs == null
                          ? "No runs recorded"
                          : `Run ${s.runs} ${s.runs === 1 ? "time" : "times"}`}
                    </span>
                    <span>{s.team}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="park-skills-gallery__none">No skills match. Try another word or show all.</p>
      )}
    </section>
  );
}

export function LearningNow({
  skills,
  onOpen,
  onPause,
  pauseOff,
}: {
  skills: readonly Skill[];
  night: boolean;
  onOpen: (id: string) => void;
  onPause: ((s: Skill) => void) | null;
  pauseOff: string;
}) {
  const learning = skills.filter((s) => !s.builtin && s.st === "learning" && !s.paused);
  return (
    <section aria-label="Learning now" className="park-skills-learning">
      <div className="park-skills-gallery__head">
        <h2 className="park-skills-h2">Learning now</h2>
        <span className="park-skills-gallery__count">
          Tilo checks with you before a skill is trusted
        </span>
      </div>
      {learning.length === 0 ? (
        <p className="park-skills-gallery__none">
          Nothing is learning right now. A skill you teach starts here.
        </p>
      ) : (
        <ul className="park-skills-learning__list">
          {learning.map((s) => (
            <li key={s.id} className="park-skills-learning__card">
              <div className="park-skills-learning__top">
                <span className="park-skills-card2__art" aria-hidden="true">
                  <SkillIcon skill={s} />
                </span>
                <span className="park-skills-learning__titles">
                  <span className="park-skills-card2__name">{s.name}</span>
                  <span className="park-skills-card2__what">
                    {s.from || s.owner ? `Learning from ${s.from || s.owner}` : "Learning"}
                  </span>
                </span>
                <span className="park-skill-chip park-skill-chip--lilac">Learning</span>
              </div>
              <p className="park-skills-learning__last">
                <strong>So far:</strong>{" "}
                {s.runs == null || s.runs === 0
                  ? "No practice runs recorded yet."
                  : `${s.runs} ${s.runs === 1 ? "run" : "runs"}${s.rate != null ? `, ${s.rate}% went right` : ""}.`}
              </p>
              <div className="park-skills-learning__actions">
                <Button variant="secondary" size="sm" onClick={() => onOpen(s.id)}>
                  Check its steps
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={onPause === null}
                  title={onPause === null ? pauseOff : undefined}
                  onClick={() => onPause?.(s)}
                >
                  Pause
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
