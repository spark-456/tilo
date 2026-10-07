// WEB-10 Team page: the two lower cards, "When agents stop and ask" (five switches, local state) and
// "What each role can do" (the role matrix). Plan 8b: the switches have no Api; they are page state.
import type { ReactNode } from "react";
import type { Team } from "../../api/types";
import { Switch } from "../../components";
import { icon } from "./teamKit";

interface RulesProps {
  rules: Team["rules"];
  on: Record<string, boolean>;
  art: ReactNode;
  /** FR-TEAM-04: Must-ask rule keys: shown on, and they can't be switched off. */
  locked: readonly string[];
  /** Every switch change this session, newest last (sample: nothing is stored). */
  log: readonly { key: string; when: string; to: boolean }[];
  onToggle: (key: string, next: boolean) => void;
}

export function RulesCard({ rules, on, art, locked, log, onToggle }: RulesProps) {
  return (
    <section className="park-team-card park-team-rules" aria-label="Approval rules">
      <div className="park-team-cardhead">
        <div className="park-team-tile">{art}</div>
        <div className="park-team-heading">
          <h2 className="park-team-h2">When agents stop and ask</h2>
          <div className="park-team-hint">These rules apply in every world.</div>
        </div>
      </div>
      {rules.map(([key, when, who, dflt]) => (
        <div key={key} className="park-team-rule">
          <div className="park-team-ruletext">
            <div className="park-team-what">{when}</div>
            <div className="park-team-ruleby">{who}</div>
          </div>
          <Switch
            label={when}
            checked={locked.includes(key) || (on[key] ?? dflt)}
            disabled={locked.includes(key)}
            onChange={(next) => onToggle(key, next)}
          />
        </div>
      ))}
      {log.length ? (
        <ul className="park-team-ruleby park-team-rulelog" aria-label="Rule changes">
          {log.map((e, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: an append-only list, never reordered
            <li key={i}>
              {e.when}: {e.to ? "On" : "Off"}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function MatrixCard({ team }: { team: Team }) {
  return (
    <section className="park-team-card park-team-matrix" aria-label="What each role can do">
      <h2 className="park-team-h2 park-team-h2--matrix">What each role can do</h2>
      <table className="park-team-blk">
        <thead className="park-team-blk">
          <tr className="park-team-mrow park-team-mhead">
            <td />
            {team.roles.map((r) => (
              <th key={r} scope="col" className="park-team-mcell">
                {r}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="park-team-blk">
          {team.matrix.map(([label, bits]) => (
            <tr key={label} className="park-team-mrow park-team-mbody">
              <th scope="row" className="park-team-mlabel">
                {label}
              </th>
              {[1, 2, 4, 8].map((b) => {
                const granted = (bits & b) !== 0;
                return (
                  <td key={b} className="park-team-mcell">
                    <span
                      className={
                        granted ? "park-team-check park-team-check--on" : "park-team-check"
                      }
                      data-granted={granted}
                    >
                      {icon(granted ? "check" : "dot", granted ? 13 : 9)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
