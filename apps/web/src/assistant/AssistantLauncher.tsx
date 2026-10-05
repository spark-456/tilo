// The "Ask Tilo" launcher (FR-PA-12). It is an item of the primary navigation (the left rail and the
// phone's bottom tabs), so it sits in the page flow and can never cover a control or a row. The
// panel it opens is AssistantPanel.
import { NavIcon } from "../screens/NavIcon";
import { setAssistantOpen, useAssistantOpen } from "./openState";

export function AssistantLauncher() {
  const open = useAssistantOpen();
  return (
    <button
      type="button"
      className="nav-btn"
      data-testid="assistant-open"
      data-assistant-control
      aria-expanded={open}
      aria-haspopup="dialog"
      onClick={() => setAssistantOpen(!open)}
    >
      <span className="nav-label">Ask Tilo</span>
      <span className="nav-icon-box">
        <NavIcon name="assistant" />
      </span>
    </button>
  );
}
