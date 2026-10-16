import { useEffect, useState } from "react";
import type { HttpClient } from "../../api/http";
import { type CatalogSkill, catalogOf, mentionQuery } from "../../api/skillRoute";
import "./SkillMention.css";

const GROUPS = ["mine", "team", "library"] as const;
const LABELS = { mine: "Mine", team: "Team", library: "Library" };

export function SkillMention({
  text,
  selected,
  client,
  onChoose,
  onClear,
}: {
  text: string;
  selected: CatalogSkill | null;
  client: HttpClient | null;
  onChoose: (skill: CatalogSkill) => void;
  onClear: () => void;
}) {
  const query = selected ? null : mentionQuery(text);
  const open = query !== null;
  const [skills, setSkills] = useState<CatalogSkill[]>([]);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "failed">("idle");
  useEffect(() => {
    if (!open || !client) return;
    let active = true;
    setState("loading");
    client.getJson("/v1/skills/catalog").then(
      (body) => {
        if (!active) return;
        setSkills(catalogOf(body));
        setState("ready");
      },
      () => {
        if (active) setState("failed");
      },
    );
    return () => {
      active = false;
    };
  }, [client, open]);

  if (selected)
    return (
      <div className="park-skill-mention__selected">
        <output>Skill selected: {selected.name}. Tilo will use it with your task.</output>
        <button type="button" onClick={onClear} aria-label={`Remove ${selected.name} skill`}>
          Remove
        </button>
      </div>
    );
  if (query === null) return null;
  if (!client)
    return <p className="park-skill-mention__note">Skill picker needs a connected session.</p>;
  if (state === "loading" || state === "idle")
    return <p className="park-skill-mention__note">Reading skills…</p>;
  if (state === "failed")
    return <p className="park-skill-mention__note">Skills could not be loaded.</p>;
  const filtered = skills.filter((s) =>
    s.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  return (
    <section className="park-skill-mention" aria-label="Mention a skill">
      {GROUPS.map((group) => {
        const rows = filtered.filter((s) => s.scope === group);
        return rows.length ? (
          <div key={group} className="park-skill-mention__group">
            <strong>{LABELS[group]}</strong>
            {rows.map((skill) => (
              <button type="button" key={skill.id} onClick={() => onChoose(skill)}>
                <span>{skill.name}</span>
                <small>{skill.purpose}</small>
              </button>
            ))}
          </div>
        ) : null;
      })}
      {filtered.length === 0 ? <p>No matching skills.</p> : null}
    </section>
  );
}
