// TEAM-WEB (FR-ACC-01): the Connectors page on a live Api. The connector catalogue has no route, so this shows
// what the server does know: each tool's team access level (off, read, draft, act) from GET /v1/team, changed
// with PUT /v1/team/tools/{connector} by the Owner only. Optimistic, rolled back on failure (useLiveTeam).
// A saved level for each skill (FR-ACC-02) needs a contract change and stays not built.
import { TOOL_LEVELS, type TeamView } from "../../api/live/teamLive";
import { type LiveTeam, READ_ONLY } from "../../app/useLiveTeam";

const LABEL: Record<string, string> = { off: "Off", read: "Read", draft: "Draft", act: "Act" };
const WORDS: Record<string, string> = {
  off: "Agent runs cannot use this tool. Email Autopilot and calendar sync do not check this yet.",
  read: "Agents can read from this tool.",
  draft: "Agents can prepare drafts, never send.",
  act: "Agents can act, within policy.",
};

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
          <span className="park-connectors-sectitle">Tool access</span>
          <span className="park-connectors-count">{view.tools.length} tools</span>
        </div>
        {view.tools.map((t) => (
          <div key={t.connector} className="park-connectors-usedrow">
            <span className="park-connectors-usedname">{t.connector}</span>
            <select
              className="park-team-select"
              aria-label={`Access level for ${t.connector}`}
              value={t.level}
              disabled={off}
              onChange={(e) =>
                void live
                  .send({ kind: "tool", connector: t.connector, level: e.target.value })
                  .then((ok) => ok && toast(`${t.connector}: ${WORDS[e.target.value] ?? "saved"}`))
              }
            >
              {TOOL_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {LABEL[l]}
                </option>
              ))}
            </select>
            <span className="park-connectors-lvsub">{WORDS[t.level] ?? ""}</span>
          </div>
        ))}
        <div className="park-connectors-note">A saved level for each skill is not built yet.</div>
      </section>
    </>
  );
}
