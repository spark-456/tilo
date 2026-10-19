// CONNECTORS-DESIGN (FR-ACC-01/03/04; design "Tilo S Connectors", the right-hand manage panel): one live app's
// access level as Always / Ask me / Read only / Never (the four server levels), its grant facts, and honest "not
// available yet" lines for what no route serves (usage, sync history). Only an Owner can change the level, through
// the same PUT the Team page uses; everyone else reads who sets it. Focus lands on the panel's heading on open
// and goes back to the app's Manage button on close.
import { useEffect, useRef } from "react";
import type { Connector } from "../../api/types";
import { expiryText, monogram, scopesText, stateText, toneOf } from "./LiveConnectors";
import type { LevelControl } from "./LiveConnectorsWithLevels";
import { LevelPicker, WORDS, levelLabel } from "./ToolAccess";
import { icon } from "./icons";

export function ManagePanel({
  c,
  control,
  onClose,
}: { c: Connector; control: LevelControl; onClose: () => void }) {
  const head = useRef<HTMLHeadingElement>(null);
  const { levels, failure, busy, setLevel } = control;
  useEffect(() => {
    head.current?.focus();
  }, []);
  const level = levels.kind === "known" ? levels.byId[c.id] : undefined;
  const close = () => {
    onClose();
    document.getElementById(`manage-${c.id}`)?.focus();
  };
  return (
    <section
      className="park-connectors-panel"
      aria-label={`${c.name} access`}
      onKeyDown={(e) => e.key === "Escape" && close()}
    >
      <div className="park-connectors-panel-head">
        <span className="park-connectors-avail-mono" aria-hidden="true">
          {monogram(c.name)}
        </span>
        <div className="park-connectors-panel-titles">
          <h2 className="park-connectors-panel-name" tabIndex={-1} ref={head}>
            {c.name}
          </h2>
          <p className={`park-connectors-livestate park-connectors-livestate--${toneOf(c)}`}>
            {stateText(c)}
          </p>
        </div>
        <button
          type="button"
          className="park-connectors-panel-close"
          aria-label={`Close ${c.name} panel`}
          onClick={close}
        >
          {icon("x", 15)}
        </button>
      </div>
      <h3 className="park-connectors-h3">What Tilo may do</h3>
      {levels.kind === "known" && level !== undefined ? (
        <>
          <LevelPicker
            connector={c.name}
            level={level}
            disabled={busy}
            group="panel"
            onPick={(next) => void setLevel(c.id, next)}
          />
          <p className="park-connectors-lvsub">{WORDS[level] ?? levelLabel(level)}</p>
        </>
      ) : (
        <p className="park-connectors-lvsub">
          {levels.kind === "not_owner"
            ? "Set by the workspace owner"
            : levels.kind === "loading"
              ? "Loading…"
              : "Access level not available yet"}
        </p>
      )}
      <output className="park-connectors-panel-note">{failure}</output>
      <dl className="park-connectors-facts">
        <dt>Granted scopes</dt>
        <dd>{scopesText(c)}</dd>
        <dt>Grant expiry</dt>
        <dd>{expiryText(c)}</dd>
        <dt>Usage</dt>
        <dd>Usage not available yet</dd>
        <dt>Sync history</dt>
        <dd>Sync history not available yet</dd>
      </dl>
      <p className="park-connectors-note">
        Payments, sharing outside the team and anything that can’t be undone still ask a person.
      </p>
    </section>
  );
}
