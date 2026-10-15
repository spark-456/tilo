// UI-STUDIO-5 (design/studio-v2 "Tilo S Settings": "Spending and limits", "Ask me before Tilo…"). Both read the
// team's own rules from GET /v1/team (useLiveTeam, read when the tab opens); the Owner changes a switch with the
// existing PUT, everyone else reads it. Spend so far is the Ledger's. Nothing here is invented: a limit the server
// does not keep (a daily or per-world cap) says "Not available yet".
import type { TeamView } from "../../api/live/teamLive";
import { useParkApi } from "../../app/context";
import { type LiveTeam, useLiveTeam } from "../../app/useLiveTeam";
import { Switch } from "../../components";

const ASK_COPY: Record<string, [string, string]> = {
  spend: ["Spending money", "Always asks. This can’t be switched off."],
  share: ["Sharing anything outside the team", "Always asks. This can’t be switched off."],
  undo: ["Anything that can’t be undone", "Always asks. This can’t be switched off."],
  tools: ["Giving a skill more access to an app", "Saved; not enforced yet"],
  weekend: ["Routines that fall on a weekend", "Hold until Monday morning"],
};

/** INR minor units in words (the team's limits are kept in paise). */
const rupees = (minor: number): string => `₹${(minor / 100).toLocaleString("en-IN")}`;
const money = (n: number, currency: string): string =>
  `${currency === "USD" ? "$" : currency === "INR" ? "₹" : "£"}${n.toLocaleString("en-GB")}`;

function Status({ live }: { live: LiveTeam }) {
  const text =
    live.state.phase === "error"
      ? live.state.text
      : live.state.phase === "fixture"
        ? "Not connected yet. Sign in to see your team’s rules."
        : live.note;
  return <output className="park-profile-note park-profile-status">{text}</output>;
}

function Cap({
  title,
  value,
  sub,
  fill,
}: { title: string; value: string; sub: string; fill?: number }) {
  return (
    <div className="park-profile-cap">
      <span className="park-profile-captitle">{title}</span>
      <span className="park-profile-capvalue">{value}</span>
      {fill === undefined ? null : (
        <span className="park-profile-bar" aria-hidden="true">
          <span className="park-profile-fill" style={{ width: `${fill}%` }} />
        </span>
      )}
      <span className="park-profile-ssub">{sub}</span>
    </div>
  );
}

export function SpendingLimits({
  spend,
  onTeam,
}: { spend: { spent: number; budget: number; currency: string }; onTeam: () => void }) {
  const live = useLiveTeam(useParkApi());
  const view: TeamView | null = live.state.phase === "ready" ? live.state.view : null;
  const mine = view?.members.find((m) => m.id === view.me.id);
  const yours =
    live.state.phase === "probing"
      ? "Checking"
      : !view
        ? "Not available yet"
        : mine?.limit_minor == null
          ? "No limit set"
          : `Up to ${rupees(mine.limit_minor)}`;
  const pct =
    spend.budget > 0
      ? Math.min(100, Math.max(0, Math.round((spend.spent / spend.budget) * 100)))
      : 0;
  return (
    <section aria-label="Spending and limits" className="park-profile-card">
      <div>
        <h2 className="park-profile-title">Spending and limits</h2>
        <p className="park-profile-blurb">
          Spending money always waits for a yes. These are the numbers Tilo checks against.
        </p>
      </div>
      <div className="park-profile-caps">
        <Cap
          title="Spent so far"
          value={money(spend.spent, spend.currency)}
          sub={
            spend.budget > 0 ? `of ${money(spend.budget, spend.currency)} budget` : "No budget set"
          }
          fill={pct}
        />
        <Cap title="You can say yes to" value={yours} sub="An Owner sets this on the Team page" />
        <Cap
          title="Each day and each world"
          value="Not available yet"
          sub="Daily and per-world caps are not kept yet"
        />
      </div>
      <Status live={live} />
      <div className="park-profile-foot">
        <button type="button" className="park-profile-btn park-profile-btn--quiet" onClick={onTeam}>
          Open the Team page
        </button>
      </div>
    </section>
  );
}

export function AskBefore() {
  const live = useLiveTeam(useParkApi());
  const view = live.state.phase === "ready" ? live.state.view : null;
  const off = !live.isOwner || live.busy;
  return (
    <section aria-label="Ask before" className="park-profile-card park-profile-card--list">
      <div>
        <h2 className="park-profile-title">Ask me before Tilo…</h2>
        <p className="park-profile-blurb">
          These show up in Needs you. Turn one off and Tilo goes ahead without asking.
        </p>
      </div>
      {view
        ? view.switches.map((s) => {
            const [label, note] = ASK_COPY[s.key] ?? [s.key, ""];
            return (
              <div key={s.key} className="park-profile-askrow">
                <div className="park-profile-grow">
                  <div className="park-profile-stitle">{label}</div>
                  <div className="park-profile-ssub">{note}</div>
                </div>
                <Switch
                  label={label}
                  description={s.must_ask ? note : undefined}
                  checked={s.on}
                  disabled={off || s.must_ask}
                  onChange={(next) => void live.send({ kind: "switch", key: s.key, on: next })}
                />
              </div>
            );
          })
        : null}
      {view && view.switches.length === 0 ? (
        <p className="park-profile-note">No rules yet.</p>
      ) : null}
      <Status live={live} />
    </section>
  );
}
