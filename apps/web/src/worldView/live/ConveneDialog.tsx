// TW-4: Convene dialog (pick Lead + agents) -> meeting.called -> agents walk to Hall slots,
// Hall chip "In session", Chat opens the meeting thread.
import type { Event, Layout } from "@tilo/contracts";
import { useMemo, useState } from "react";
import { Icon } from "../../design/tilo-t";
import type { RoomClient } from "../../park/api/live/meetingHall";
import { ROOM_MAX_AGENTS, type Seat, teamSeat } from "../../park/api/live/roomTalk";
import type { WorldFacts } from "../../world/useWorldFacts";
import { agentColorKey } from "./ChatPopUp";
import "./live.css";

const DEFAULT_PROMPT = "Swap the Saturday workshop for a boat trip on the Douro. Same budget.";

interface ConveneDialogProps {
  worldId: string;
  facts: WorldFacts;
  events: readonly Event[];
  rooms: RoomClient | null;
  onClose: () => void;
  onCall: (seat: Seat, prompt: string) => void;
}

export function ConveneDialog({ facts, events, rooms, onClose, onCall }: ConveneDialogProps) {
  const layout = facts.layout as Layout | null;
  const heads = useMemo(
    () => (layout?.semantic.agents ?? []).filter((a) => a.rank === "director" || a.rank === "lead"),
    [layout],
  );
  const [lead, setLead] = useState(heads.find((a) => a.rank === "lead")?.id ?? heads[0]?.id ?? "");
  const [picked, setPicked] = useState<string[]>([]);
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);

  const allAgentIds = useMemo(() => (layout?.semantic.agents ?? []).map((a) => a.id), [layout]);

  // Who the API would seat with this lead (its district's workers, or the Director's Leads)
  const eligible = useMemo(() => {
    if (!layout) return [];
    const all = layout.semantic.agents.map((a) => a.id);
    return teamSeat(layout, events, lead, all)?.agents ?? [];
  }, [layout, events, lead]);

  const chosen = picked.filter((id) => eligible.includes(id)).slice(0, ROOM_MAX_AGENTS);

  const nameOf = (id: string) => facts.names.get(id) ?? id;
  const roleOf = (id: string) => {
    const sem = layout?.semantic.agents.find((a) => a.id === id);
    return sem?.rank ? sem.rank.charAt(0).toUpperCase() + sem.rank.slice(1) : "Specialist";
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!lead) return;
    onCall({ lead, agents: chosen }, prompt);
  };

  return (
    <>
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: backdrop click to dismiss */}
      <div className="tw-scrim" onClick={onClose} aria-hidden="true" />
      {/* biome-ignore lint/a11y/useSemanticElements: modal dialog rendered as custom styled div */}
      <div role="dialog" aria-label="Convene team" className="tw-convene-dialog">
        <header className="tw-convene-dialog__head">
          <div className="tw-convene-dialog__titles">
            <h2 className="tw-convene-dialog__title">Convene team</h2>
            <p className="tw-convene-dialog__sub">
              The agents you pick stop where they are and walk to the Meeting Hall to hear you out.
            </p>
          </div>
          <button
            type="button"
            className="tw-convene-dialog__x"
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        {heads.length === 0 ? (
          <p className="tw-room__off">This world has no Lead to call yet.</p>
        ) : (
          <form className="tw-team__form" onSubmit={handleSubmit}>
            <div className="tw-convene-section">
              <span className="tw-convene-label">WHO LEADS</span>
              <div className="tw-convene-lead-row">
                <span
                  className="tw-chat-av"
                  data-ag-color={agentColorKey(lead, allAgentIds)}
                  aria-hidden="true"
                >
                  <span className="tw-chat-visor">
                    <span className="tw-chat-eye" />
                    <span className="tw-chat-eye" />
                  </span>
                </span>
                <div className="tw-convene-agent-meta">
                  <strong className="tw-convene-agent-name">{nameOf(lead)}</strong>
                  <span className="tw-convene-agent-role">{roleOf(lead)}</span>
                </div>
                <span className="tw-convene-lock">Always joins</span>
              </div>
            </div>

            <div className="tw-convene-section">
              <span className="tw-convene-label">WHO JOINS</span>
              <div className="tw-convene-list">
                {eligible.length === 0 ? (
                  <p className="tw-card__quiet">Nobody else can join this lead's meeting yet.</p>
                ) : (
                  eligible.map((id) => {
                    const isChecked = chosen.includes(id);
                    return (
                      <label
                        key={id}
                        className={`tw-convene-row tw-team__pick ${isChecked ? "tw-convene-row--on" : ""}`}
                      >
                        <span
                          className="tw-chat-av"
                          data-ag-color={agentColorKey(id, allAgentIds)}
                          aria-hidden="true"
                        >
                          <span className="tw-chat-visor">
                            <span className="tw-chat-eye" />
                            <span className="tw-chat-eye" />
                          </span>
                        </span>
                        <div className="tw-convene-agent-meta">
                          <strong className="tw-convene-agent-name">{nameOf(id)}</strong>
                          <span className="tw-convene-agent-role">{roleOf(id)}</span>
                        </div>
                        <input
                          type="checkbox"
                          checked={isChecked}
                          disabled={!isChecked && chosen.length >= ROOM_MAX_AGENTS}
                          onChange={(e) =>
                            setPicked(
                              e.target.checked ? [...chosen, id] : chosen.filter((x) => x !== id),
                            )
                          }
                        />
                      </label>
                    );
                  })
                )}
              </div>
            </div>

            <div className="tw-convene-section">
              <span className="tw-convene-label">WHAT SHOULD CHANGE?</span>
              <textarea
                aria-label="What should change?"
                className="tw-convene-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>

            <div className="tw-convene-actions">
              <button type="submit" className="tw-team__go" disabled={!rooms}>
                <Icon name="people" size={16} />
                <span>Call meeting · {chosen.length + 1} agents</span>
              </button>
              <button type="button" className="tw-convene-cancel" onClick={onClose}>
                Cancel
              </button>
            </div>

            {!rooms ? (
              <p className="tw-room__off">
                Meetings need the live Tilo service, which this view is not connected to.
              </p>
            ) : null}
          </form>
        )}
      </div>
    </>
  );
}
