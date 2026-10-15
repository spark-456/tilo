// TEAM-WEB (FR-ACC-01): the Connectors page on a live Api. The connector catalogue has no route, so this shows
// what the server does know: each tool's team access level (off, read, draft, act) from GET /v1/team, changed
// with PUT /v1/team/tools/{connector} by the Owner only. Optimistic, rolled back on failure (useLiveTeam).
// A saved level for each skill (FR-ACC-02) needs a contract change and stays not built.
// UI-STUDIO-5 (design/studio-v2 "Tilo S Connectors"): "What Tilo may do" in plain words, one choice per app:
// Always (act, within policy), Ask me (draft only: you send), Read only, Never (off). The same four server levels.
import type { TeamView, ToolLevelName } from "../../api/live/teamLive";
import { type LiveTeam, READ_ONLY } from "../../app/useLiveTeam";

/** The design's order, most to least: each label is the server level it saves. */
const CHOICES: readonly (readonly [ToolLevelName, string])[] = [
  ["act", "Always"],
  ["draft", "Ask me"],
  ["read", "Read only"],
  ["off", "Never"],
];
/** A level in the design's words (what the person sees beside each app). */
export const levelLabel = (level: string): string =>
  CHOICES.find(([value]) => value === level)?.[1] ?? level;
const WORDS: Record<string, string> = {
  off: "Agent runs cannot use this tool. Email Autopilot and calendar sync do not check this yet.",
  read: "Agents can read from this tool.",
  draft: "Agents can prepare drafts, never send.",
  act: "Agents can act, within policy.",
};

/** One app's level as a row of radio choices (a real radio group: arrow keys move, a disabled set says so). */
function LevelPicker({
  connector,
  level,
  disabled,
  onPick,
}: {
  connector: string;
  level: string;
  disabled: boolean;
  onPick: (next: string) => void;
}) {
  return (
    <fieldset
      className="park-connectors-choices"
      aria-label={`Access level for ${connector}`}
      disabled={disabled}
    >
      {CHOICES.map(([value, label]) => (
        <label
          key={value}
          className={
            level === value
              ? "park-connectors-choice park-connectors-choice--on"
              : "park-connectors-choice"
          }
        >
          <input
            type="radio"
            className="park-connectors-choiceinput"
            name={`level-${connector}`}
            value={value}
            checked={level === value}
            onChange={() => onPick(value)}
          />
          {label}
        </label>
      ))}
    </fieldset>
  );
}

export function ToolAccess({
  live,
  view,
  toast,
}: { live: LiveTeam; view: TeamView; toast: (m: string) => void }) {
  const off = !live.isOwner || live.busy;
  const note =
    live.note === READ_ONLY
      ? "Only an Owner can change tool access. You can look at it."
      : live.note;
  return (
    <>
      <output
        className="park-connectors-sub"
        style={{ display: "block", minHeight: 20, margin: 0 }}
      >
        {note}
      </output>
      <section className="park-connectors-section" aria-label="Tool access">
        <div className="park-connectors-sechead">
          <span className="park-connectors-sectitle">What Tilo may do</span>
          <span className="park-connectors-count">{view.tools.length} tools</span>
        </div>
        {view.tools.map((t) => (
          <div key={t.connector} className="park-connectors-usedrow park-connectors-choicerow">
            <span className="park-connectors-usedname">{t.connector}</span>
            <LevelPicker
              connector={t.connector}
              level={t.level}
              disabled={off}
              onPick={(next) =>
                void live
                  .send({ kind: "tool", connector: t.connector, level: next })
                  .then((ok) => ok && toast(`${t.connector}: ${WORDS[next] ?? "saved"}`))
              }
            />
            <span className="park-connectors-lvsub">{WORDS[t.level] ?? ""}</span>
          </div>
        ))}
        <div className="park-connectors-note">
          Payments, sharing outside the team and anything that can’t be undone still ask a person.
        </div>
        <div className="park-connectors-note">A saved level for each skill is not built yet.</div>
      </section>
    </>
  );
}
