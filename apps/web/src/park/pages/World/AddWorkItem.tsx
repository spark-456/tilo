// BQ-CTX-TEAMWORLD (ADR-0040 decisions 6 and 10, FR-TEAM-04): add a work item from a world's page. The page is the
// world of an owner or a team reader, so its world is the only one offered; a personal item (no world) stays the
// default and the choice to make it the team's says plainly who can see it, before anything is sent. "Added" is
// said only after the server's own answer; a failure says what it is, and Try again resends the same attempt (one
// Idempotency-Key), so an item that was created is not created twice. Nothing here is a sample and nothing moves.
import { type FormEvent, useId, useRef, useState } from "react";
import {
  type AddedItem,
  type FailurePlan,
  type WorkItemClient,
  addWorkItem,
  newAttemptKey,
  planFailure,
} from "../../api/live/workItems";
import { Button } from "../../components";
import "./TeamWorkItem.css";

type Phase =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "failed"; plan: FailurePlan }
  | { kind: "added"; item: AddedItem };

const WHO_SEES =
  "Every member of the team this world is shared with can see the item’s title, status and due date.";
const NOT_SHARED = "If this world is not shared with a team, only you can see it.";
const WHO_SEES_ADDED =
  "Members of the team this world is shared with can see its title, status and due date.";

export function AddWorkItem({
  client,
  worldId,
  onAdded,
}: {
  client: WorkItemClient;
  worldId: string;
  onAdded?: () => void;
}) {
  const group = useId();
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [inWorld, setInWorld] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [local, setLocal] = useState("");
  const attempt = useRef<{ sig: string; key: string | null } | null>(null);
  const sending = phase.kind === "sending";

  const send = async () => {
    if (sending) return;
    if (title.trim() === "") {
      setLocal("Give the item a title.");
      return;
    }
    setLocal("");
    const worldOf = inWorld ? worldId : null;
    // The same text and place is the same attempt: its retry carries the same key.
    const sig = JSON.stringify([title.trim(), due.trim(), worldOf]);
    if (attempt.current?.sig !== sig) attempt.current = { sig, key: newAttemptKey() };
    setPhase({ kind: "sending" });
    try {
      const item = await addWorkItem(
        client,
        { title, dueText: due, worldId: worldOf },
        attempt.current.key,
      );
      attempt.current = null;
      setTitle("");
      setDue("");
      setInWorld(false); // the personal choice is the default each time
      setPhase({ kind: "added", item });
      onAdded?.();
    } catch (e) {
      setPhase({ kind: "failed", plan: planFailure(e) });
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send();
  };
  const added = phase.kind === "added" ? phase.item : null;
  return (
    <section className="park-world-proposals" aria-label="Add a work item">
      <h2>Add a work item</h2>
      <form className="park-world-additem" onSubmit={submit} noValidate>
        <label className="park-world-slackfield">
          <span className="park-world-slacklabel">Title</span>
          <input
            className="park-world-slacknote"
            aria-label="Title"
            type="text"
            maxLength={140}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label className="park-world-slackfield">
          <span className="park-world-slacklabel">Due (optional)</span>
          <input
            className="park-world-slacknote"
            aria-label="Due (optional)"
            type="text"
            maxLength={60}
            placeholder="A date, or a phrase such as next Friday"
            value={due}
            onChange={(e) => setDue(e.target.value)}
          />
        </label>
        <fieldset className="park-world-additem-who">
          <legend>Who can see it</legend>
          <label className="park-world-additem-choice">
            <input
              type="radio"
              name={group}
              aria-label="Only me"
              checked={!inWorld}
              onChange={() => setInWorld(false)}
            />
            <span>
              Only me
              <span className="park-world-additem-hint">It goes on your own list.</span>
            </span>
          </label>
          <label className="park-world-additem-choice">
            <input
              type="radio"
              name={group}
              aria-label="This world’s team"
              checked={inWorld}
              onChange={() => setInWorld(true)}
            />
            <span>
              This world’s team
              <span className="park-world-additem-hint">{`${WHO_SEES} ${NOT_SHARED}`}</span>
            </span>
          </label>
        </fieldset>
        {local ? <p role="alert">{local}</p> : null}
        {phase.kind === "failed" ? <p role="alert">{phase.plan.words}</p> : null}
        {sending ? <output>Adding the item…</output> : null}
        {added ? (
          <output>
            {added.worldId
              ? `Added “${added.title}” to this world’s work items. ${WHO_SEES_ADDED}`
              : `Added “${added.title}” to your own list.`}
          </output>
        ) : null}
        <div className="park-world-slackactions">
          <Button variant="secondary" size="sm" type="submit" disabled={sending}>
            Add item
          </Button>
          {phase.kind === "failed" && phase.plan.retry ? (
            <Button variant="secondary" size="sm" onClick={() => void send()}>
              Try again
            </Button>
          ) : null}
        </div>
      </form>
    </section>
  );
}
