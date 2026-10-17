import { type KeyboardEvent, type ReactNode, useEffect, useId, useState } from "react";
import type { HttpClient } from "../../api/http";
import { type CatalogSkill, catalogOf, mentionQuery } from "../../api/skillRoute";
import { SkillIcon } from "../pages/Skills/skillIcon";
import "./SkillMention.css";

const GROUPS = ["mine", "team", "library"] as const;
const LABELS = { mine: "Mine", team: "Team", library: "Library" };

export interface MentionInputProps {
  onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => void;
  role: "combobox";
  "aria-autocomplete": "list";
  "aria-expanded": boolean;
  "aria-controls"?: string;
  "aria-activedescendant"?: string;
}

export function SkillMention({
  text,
  selected,
  client,
  onChoose,
  onClear,
  renderInput,
}: {
  text: string;
  selected: CatalogSkill | null;
  client: HttpClient | null;
  onChoose: (skill: CatalogSkill) => void;
  onClear: () => void;
  renderInput?: (props: MentionInputProps) => ReactNode;
}) {
  const query = selected ? null : mentionQuery(text);
  const [active, setActive] = useState({ query, index: 0, dismissed: false });
  const current = active.query === query ? active : { query, index: 0, dismissed: false };
  const open = query !== null && !current.dismissed;
  const listId = useId();
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

  const filtered =
    query === null
      ? []
      : skills.filter((s) => s.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const options = GROUPS.flatMap((group) => filtered.filter((skill) => skill.scope === group));
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (selected && text === "" && event.key === "Backspace") {
      event.preventDefault();
      onClear();
      return;
    }
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      setActive({ query, index: current.index, dismissed: true });
    } else if (event.key === "ArrowDown" && options.length) {
      event.preventDefault();
      setActive({
        query,
        index: Math.min(current.index + 1, options.length - 1),
        dismissed: false,
      });
    } else if (event.key === "ArrowUp" && options.length) {
      event.preventDefault();
      setActive({ query, index: Math.max(current.index - 1, 0), dismissed: false });
    } else if (event.key === "Enter") {
      const option = options[current.index];
      if (!option) return;
      event.preventDefault();
      onChoose(option);
    }
  };
  const inputProps: MentionInputProps = {
    onKeyDown,
    role: "combobox",
    "aria-autocomplete": "list",
    "aria-expanded": open,
    ...(open ? { "aria-controls": listId } : {}),
    ...(open && options[current.index]
      ? { "aria-activedescendant": `${listId}-option-${current.index}` }
      : {}),
  };
  return (
    <>
      {renderInput?.(inputProps)}
      {selected ? (
        // biome-ignore lint/a11y/useSemanticElements: this removable selection chip is a labelled control group.
        <div className="park-skill-mention__selected" role="group" aria-label="Selected skill">
          <SkillIcon skill={selected} decorative />
          <span data-testid="selected-skill-chip">{selected.name}</span>
          <button type="button" onClick={onClear} aria-label={`Remove ${selected.name} skill`}>
            Remove
          </button>
        </div>
      ) : null}
      {open && !client ? (
        <p className="park-skill-mention__note">Skill picker needs a connected session.</p>
      ) : null}
      {open && client && (state === "loading" || state === "idle") ? (
        <p className="park-skill-mention__note">Reading skills…</p>
      ) : null}
      {open && state === "failed" ? (
        <p className="park-skill-mention__note">Skills could not be loaded.</p>
      ) : null}
      {open && client && state === "ready" ? (
        <section className="park-skill-mention" aria-label="Mention a skill">
          <div
            className="park-skill-mention__list"
            id={listId}
            // biome-ignore lint/a11y/useSemanticElements: listbox options contain icons and descriptions, unlike a select.
            role="listbox"
            aria-label="Skills"
            tabIndex={-1}
          >
            {GROUPS.map((group) => {
              const rows = filtered.filter((skill) => skill.scope === group);
              return rows.length ? (
                <fieldset key={group} className="park-skill-mention__group">
                  <legend>{LABELS[group]}</legend>
                  {rows.map((skill) => {
                    const index = options.indexOf(skill);
                    return (
                      <button
                        type="button"
                        // biome-ignore lint/a11y/useSemanticElements: option buttons need listbox selection state.
                        role="option"
                        aria-selected={index === current.index}
                        id={`${listId}-option-${index}`}
                        key={skill.id}
                        onMouseEnter={() => setActive({ query, index, dismissed: false })}
                        onClick={() => onChoose(skill)}
                      >
                        <SkillIcon skill={skill} decorative />
                        <span>{skill.name}</span>
                        <small>{skill.purpose}</small>
                      </button>
                    );
                  })}
                </fieldset>
              ) : null;
            })}
          </div>
          {filtered.length === 0 ? <output>No matching skills.</output> : null}
        </section>
      ) : null}
    </>
  );
}
