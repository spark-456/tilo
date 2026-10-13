// FR-ACC-02: each skill's level for each tool it uses. A level above the team's is not offered; the choice is
// kept on the page only (sample data, no endpoint) and can only lower the level.
import { useState } from "react";
import type { Learn, Skill } from "../../api/types";
import { LEVELS, allowedLevels, shownLevel, toolRows } from "./skillAccess";

export function ToolAccess({ skills, tools }: { skills: Skill[]; tools: Learn["tools"] }) {
  const [picked, setPicked] = useState<Record<string, number>>({});
  const rows = toolRows(skills, tools);
  if (rows.length === 0) return null;
  return (
    <section className="park-skills-access" aria-label="Tool access per skill">
      <h2 className="park-skills-access-h">Tool access per skill</h2>
      <p className="park-skills-access-sub">
        A skill can use a tool at a lower level than your team’s. It can never use a higher one.
      </p>
      <ul className="park-skills-access-list">
        {rows.map((r) => {
          const key = `${r.skillId}:${r.tool}`;
          const allowed = allowedLevels(r.team);
          return (
            <li key={key} className="park-skills-access-row">
              <span className="park-skills-access-name">
                {r.skill} · {r.tool}
              </span>
              <select
                className="park-skills-access-select"
                aria-label={`${r.skill}: ${r.tool} access`}
                data-skill-tool={key}
                data-team-level={r.team}
                value={shownLevel(r.team, picked[key] ?? r.level)}
                onChange={(e) => setPicked({ ...picked, [key]: Number(e.currentTarget.value) })}
              >
                {LEVELS.map((label, i) => (
                  <option key={label} value={i} disabled={!allowed.includes(i)}>
                    {label}
                  </option>
                ))}
              </select>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
