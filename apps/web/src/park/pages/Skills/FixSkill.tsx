import { useState } from "react";
import type { Api } from "../../api";
import { fixSkill } from "../../api/skillFixes";
import type { Skill } from "../../api/types";

export function FixSkill({
  api,
  skill,
  saved,
}: { api: Api; skill: Skill; saved: (s: Skill) => void }) {
  const [step, setStep] = useState(0);
  const [text, setText] = useState(skill.steps[0] ?? "");
  const [ask, setAsk] = useState(skill.fix?.asks[0] ?? true);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const fix = skill.fix;
  if (!fix || skill.st === "draft") return null;
  const locked = fix.locked[step] !== false;
  return (
    <form
      aria-label="Fix a skill step"
      onSubmit={async (e) => {
        e.preventDefault();
        if (pending) return;
        setPending(true);
        setMessage("");
        try {
          const next = await fixSkill(api, skill.id, {
            from_version: fix.version,
            step: step + 1,
            text,
            ask_first: locked || ask,
          });
          saved(next);
        } catch {
          setMessage("Could not save the fix. Reload to check the current version.");
        } finally {
          setPending(false);
        }
      }}
    >
      <h3 className="park-skills-h3">Fix a skill step</h3>
      <p>Only the owner can fix this skill. Running taught skills is not available yet.</p>
      <fieldset disabled={pending}>
        <label>
          Step{" "}
          <select
            className="park-skills-save-name"
            value={step}
            onChange={(e) => {
              const n = Number(e.target.value);
              setStep(n);
              setText(skill.steps[n] ?? "");
              setAsk(fix.asks[n] ?? true);
            }}
          >
            {skill.steps.map((s, i) => (
              <option key={`${i}:${s}`} value={i}>
                {i + 1}. {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Instruction{" "}
          <input
            className="park-skills-save-name"
            value={text}
            maxLength={280}
            required
            onChange={(e) => setText(e.target.value)}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={locked || ask}
            disabled={locked}
            onChange={(e) => setAsk(e.target.checked)}
          />
          Ask me first
        </label>
        <button type="submit" className="park-btn park-btn--secondary park-btn--md">
          {pending ? "Saving…" : "Save step fix"}
        </button>
      </fieldset>
      <output>{message}</output>
    </form>
  );
}
